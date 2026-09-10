import hashlib
import io
import re
from datetime import timedelta
from functools import wraps
from pathlib import Path
from flask import abort, g, current_app, request
from flask_login import current_user, login_required
from email_validator import validate_email, EmailNotValidError
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename
from .extensions import db
from .models import Membership, Ticket, Event, Attachment, Notification, now, token


class ValidationError(ValueError):
    pass


def field(name, minimum=1, maximum=200, default=''):
    value = request.form.get(name, default).strip()
    if not minimum <= len(value) <= maximum:
        label = {'name': 'nome', 'title': 'título', 'description': 'descrição', 'email': 'e-mail',
                 'reason': 'motivo', 'message': 'mensagem', 'note': 'observação', 'phone': 'telefone',
                 'specialty': 'especialidade', 'reference': 'referência', 'notes': 'observações',
                 'submission_key': 'identificação do formulário'}.get(name, name)
        raise ValidationError(f'O campo {label} deve ter entre {minimum} e {maximum} caracteres.')
    return value


def email_field():
    try:
        return validate_email(field('email', 3, 254), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        raise ValidationError('Informe um e-mail válido.')


def positive_int(value, label='valor', minimum=1, maximum=1000000000):
    try:
        result = int(value)
        if minimum <= result <= maximum:
            return result
    except (ValueError, TypeError):
        pass
    raise ValidationError(f'Informe {label} entre {minimum} e {maximum}.')


def password_field():
    password = request.form.get('password', '')
    if not 8 <= len(password) <= 128:
        raise ValidationError('A senha deve ter entre 8 e 128 caracteres.')
    return password


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def safe_next(value):
    return value if value and value.startswith('/') and not value.startswith('//') and '\\' not in value else '/workspace'


def slugify(value):
    import unicodedata
    normalized = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', normalized).strip('-')[:60] or 'empresa'


def manager_required(func):
    @wraps(func)
    @login_required
    def wrapped(*args, **kwargs):
        if not g.membership or g.membership.role not in ('owner', 'manager'):
            abort(403)
        return func(*args, **kwargs)
    return wrapped


def scoped(model, item_id):
    if not g.company:
        abort(403)
    return db.first_or_404(db.select(model).where(model.id == item_id, model.company_id == g.company.id))


def ticket_access(ticket_id):
    ticket = db.get_or_404(Ticket, ticket_id)
    if ticket.requester_id == current_user.id:
        return ticket
    if not g.membership or ticket.company_id != g.membership.company_id:
        abort(404)
    if g.membership.role in ('owner', 'manager'):
        return ticket
    if g.membership.role == 'provider' and ticket.provider_id == g.membership.id:
        return ticket
    abort(404)


def audit(company_id, text, ticket=None, kind='change', actor_id=None):
    db.session.add(Event(company_id=company_id, ticket_id=ticket.id if ticket else None,
                         actor_id=actor_id or (current_user.id if current_user.is_authenticated else None),
                         kind=kind, text=text))


def notify_user(user, company_id, title, body, path, dedupe=None, email=True):
    db.session.add(Notification(user_id=user.id, company_id=company_id, email=user.email,
                                title=title, body=body, path=path, send_email=email, dedupe_key=dedupe))


def notify_ticket(ticket, title):
    recipients = {ticket.requester_id: ticket.requester}
    managers = db.session.scalars(db.select(Membership).where(Membership.company_id == ticket.company_id,
        Membership.role.in_(['owner', 'manager']), Membership.active.is_(True), Membership.user_id.is_not(None))).all()
    for member in managers:
        recipients[member.user_id] = member.user
    if ticket.provider and ticket.provider.user:
        recipients[ticket.provider.user_id] = ticket.provider.user
    for user in recipients.values():
        notify_user(user, ticket.company_id, title, f'{ticket.reference} · {ticket.title}',
                    f'/tickets/{ticket.id}', email=ticket.company.email_alerts)


def upload(file, company_id, kind, ticket_id=None, membership_id=None, expires_at=None):
    if not file or not file.filename:
        return None
    data = file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise ValidationError('Cada arquivo deve ter no máximo 5 MB.')
    name = secure_filename(file.filename)[:190] or 'arquivo'
    if kind == 'document' and name.lower().endswith('.pdf') and data.startswith(b'%PDF-'):
        ext, mime = '.pdf', 'application/pdf'
    else:
        try:
            with Image.open(io.BytesIO(data)) as image:
                if image.format not in ('PNG', 'JPEG', 'WEBP'):
                    raise ValidationError('Envie uma imagem JPG, PNG ou WebP, ou PDF para documentos.')
                if image.width * image.height > 25000000:
                    raise ValidationError('A imagem excede 25 megapixels.')
                image.load()
                image.thumbnail((2000, 2000))
                output = io.BytesIO()
                image.convert('RGB').save(output, format='JPEG', quality=88)
                data = output.getvalue()
                ext, mime = '.jpg', 'image/jpeg'
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise ValidationError('O arquivo não é uma imagem válida.')
    storage_name = token() + ext
    path = Path(current_app.config['UPLOAD_FOLDER'], storage_name)
    path.write_bytes(data)
    g.setdefault('new_uploads', []).append(path)
    attachment = Attachment(company_id=company_id, ticket_id=ticket_id, membership_id=membership_id,
        uploader_id=current_user.id, name=name, storage_name=storage_name, mime=mime,
        kind=kind, expires_at=expires_at)
    db.session.add(attachment)
    db.session.flush()
    return attachment


def due_time(company, priority):
    hours = {'Urgente': 4, 'Alta': 12, 'Normal': company.sla_hours, 'Baixa': company.sla_hours * 2}[priority]
    return now() + timedelta(hours=hours)
