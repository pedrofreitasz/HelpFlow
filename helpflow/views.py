import csv
import io
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, session, abort, send_file, current_app
from flask_login import current_user, login_required
from sqlalchemy import or_, func
from .extensions import db, limiter
from .models import (User, Company, Membership, Location, QRPoint, Ticket, Event, Attachment,
                     Invitation, Notification, STATUSES, CATEGORIES, PRIORITIES, now, token)
from .services import (field, email_field, positive_int, ValidationError, slugify, manager_required,
                       scoped, ticket_access, audit, notify_ticket, upload, due_time, digest)

bp = Blueprint('main', __name__)


@bp.get('/health')
def health():
    db.session.execute(db.text('SELECT 1'))
    return {'status': 'ok', 'service': 'HelpFlow'}


@bp.get('/')
def home():
    companies = db.session.scalars(db.select(Company).where(Company.public_portal.is_(True)).order_by(Company.name)).all()
    return render_template('home.html', companies=companies)


@bp.get('/c/<slug>')
def portal(slug):
    company = db.first_or_404(db.select(Company).where(Company.slug == slug, Company.public_portal.is_(True)))
    query = db.select(Ticket).where(Ticket.company_id == company.id, Ticket.is_public.is_(True))
    search = request.args.get('q', '').strip()[:100]
    if search:
        query = query.join(Location).where(or_(Ticket.reference.ilike(f'%{search}%'), Location.name.ilike(f'%{search}%')))
    if request.args.get('status') in STATUSES:
        query = query.where(Ticket.status == request.args['status'])
    tickets = db.paginate(query.order_by(Ticket.created_at.desc()), per_page=15, error_out=False)
    return render_template('portal.html', company=company, tickets=tickets, search=search)


@bp.get('/scan')
def scan():
    code = request.args.get('code', '').strip()
    if code:
        # Only opaque codes or this application's QR URL are accepted.
        if '/q/' in code:
            from urllib.parse import urlparse
            parsed = urlparse(code)
            if parsed.netloc not in (urlparse(current_app.config['PUBLIC_BASE_URL']).netloc, request.host):
                raise ValidationError('Esse QR Code pertence a outro site.')
            code = parsed.path.rsplit('/', 1)[-1]
        point = db.session.scalar(db.select(QRPoint).where(QRPoint.code == code, QRPoint.active.is_(True)))
        if not point:
            raise ValidationError('Código não encontrado ou desativado. Confira a etiqueta.')
        return redirect(url_for('main.qr_report', code=point.code))
    return render_template('scan.html')


@bp.route('/q/<code>', methods=['GET', 'POST'])
@limiter.limit('10 per minute', methods=['POST'])
def qr_report(code):
    point = db.first_or_404(db.select(QRPoint).where(QRPoint.code == code))
    if not point.active or not point.location.available:
        abort(410)
    if request.method == 'POST':
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login', next=request.path))
        return create_ticket(point.company, point.location)
    return render_template('report.html', company=point.company, point=point, location=point.location,
                           locations=[], submission_key=token())


@bp.route('/c/<slug>/report', methods=['GET', 'POST'])
@login_required
@limiter.limit('10 per minute', methods=['POST'])
def report(slug):
    company = db.first_or_404(db.select(Company).where(Company.slug == slug))
    if not company.public_portal and not (g.membership and g.membership.company_id == company.id):
        abort(404)
    locations = db.session.scalars(db.select(Location).where(Location.company_id == company.id, Location.active.is_(True)).order_by(Location.name)).all()
    locations = [location for location in locations if location.available]
    if request.method == 'POST':
        location_id = positive_int(request.form.get('location_id'), 'local')
        location = next((x for x in locations if x.id == location_id), None)
        if not location:
            raise ValidationError('Selecione um local desta empresa.')
        return create_ticket(company, location)
    return render_template('report.html', company=company, point=None, location=None,
                           locations=locations, submission_key=token())


def create_ticket(company, location):
    title, description = field('title', 3, 160), field('description', 10, 5000)
    category, priority = request.form.get('category'), request.form.get('priority', 'Normal')
    if category not in CATEGORIES or priority not in PRIORITIES:
        raise ValidationError('Selecione categoria e prioridade válidas.')
    key = field('submission_key', 20, 64)
    duplicate = db.session.scalar(db.select(Ticket).where(Ticket.submit_key == key))
    if duplicate:
        if duplicate.requester_id != current_user.id:
            abort(409)
        return redirect(url_for('main.ticket_detail', ticket_id=duplicate.id))
    ticket = Ticket(company_id=company.id, location_id=location.id, requester_id=current_user.id,
        title=title, description=description, category=category, priority=priority,
        due_at=due_time(company, priority), submit_key=key)
    db.session.add(ticket)
    db.session.flush()
    upload(request.files.get('photo'), company.id, 'before', ticket_id=ticket.id)
    audit(company.id, 'Chamado aberto.', ticket, 'status')
    notify_ticket(ticket, 'Novo chamado recebido')
    db.session.commit()
    flash(f'Chamado {ticket.reference} recebido. Você pode acompanhar por aqui.', 'success')
    return redirect(url_for('main.ticket_detail', ticket_id=ticket.id))


@bp.get('/workspace')
@login_required
def workspace():
    if not g.company:
        return redirect(url_for('main.tickets', mine=1))
    return redirect(url_for('main.dashboard' if g.membership.role in ('owner', 'manager') else 'main.tickets'))


@bp.route('/companies', methods=['GET', 'POST'])
@login_required
def companies():
    if request.method == 'POST':
        name = field('name', 2, 120)
        slug = slugify(name)
        if db.session.scalar(db.select(Company).where(Company.slug == slug)):
            slug += '-' + token()[:6].lower()
        company = Company(name=name, slug=slug)
        db.session.add(company)
        db.session.flush()
        db.session.add(Membership(company_id=company.id, user_id=current_user.id, name=current_user.name,
                                  email=current_user.email, role='owner'))
        audit(company.id, 'Empresa criada.')
        db.session.commit()
        session['company_id'] = company.id
        flash('Empresa criada. Cadastre o primeiro local para começar.', 'success')
        return redirect(url_for('main.locations'))
    return render_template('companies.html')


@bp.post('/companies/<int:company_id>/switch')
@login_required
def switch_company(company_id):
    member = db.session.scalar(db.select(Membership).where(Membership.company_id == company_id,
        Membership.user_id == current_user.id, Membership.active.is_(True)))
    if not member:
        abort(403)
    session['company_id'] = company_id
    return redirect(url_for('main.workspace'))


def filtered_tickets(own=False):
    query = db.select(Ticket)
    if own:
        query = query.where(Ticket.requester_id == current_user.id)
    elif g.membership:
        query = query.where(Ticket.company_id == g.company.id)
        if g.membership.role == 'provider':
            query = query.where(Ticket.provider_id == g.membership.id)
        elif g.membership.role == 'resident':
            query = query.where(Ticket.requester_id == current_user.id)
    else:
        query = query.where(Ticket.requester_id == current_user.id)
    search = request.args.get('q', '').strip()[:100]
    if search:
        query = query.join(Location).where(or_(Ticket.reference.ilike(f'%{search}%'),
            Ticket.title.ilike(f'%{search}%'), Location.name.ilike(f'%{search}%')))
    if request.args.get('status') in STATUSES:
        query = query.where(Ticket.status == request.args['status'])
    if request.args.get('priority') in PRIORITIES:
        query = query.where(Ticket.priority == request.args['priority'])
    if request.args.get('overdue') == '1':
        query = query.where(Ticket.due_at < now(), Ticket.status.not_in(['Concluído', 'Cancelado', 'Em revisão']))
    for param, comparator in [('from', Ticket.created_at.__ge__), ('to', Ticket.created_at.__lt__)]:
        if request.args.get(param):
            try:
                value = datetime.strptime(request.args[param], '%Y-%m-%d')
                if param == 'to':
                    value += timedelta(days=1)
                value = value.replace(tzinfo=ZoneInfo(current_app.config['TIMEZONE'])).astimezone(timezone.utc).replace(tzinfo=None)
                query = query.where(comparator(value))
            except ValueError:
                raise ValidationError('Informe datas válidas para o filtro.')
    return query


@bp.get('/tickets')
@login_required
def tickets():
    own = request.args.get('mine') == '1'
    result = db.paginate(filtered_tickets(own).order_by(Ticket.updated_at.desc()), per_page=20, error_out=False)
    return render_template('tickets.html', tickets=result, own=own)


@bp.get('/dashboard')
@manager_required
def dashboard():
    tickets = db.session.scalars(filtered_tickets().order_by(Ticket.created_at.desc())).all()
    active = [t for t in tickets if t.status not in ('Concluído', 'Cancelado')]
    done = [t for t in tickets if t.status == 'Concluído' and t.completed_at]
    avg_hours = round(sum((t.completed_at - t.created_at).total_seconds() / 3600 for t in done) / len(done), 1) if done else None
    on_time = round(100 * sum(t.completed_at <= t.due_at for t in done) / len(done)) if done else None
    recent = sorted(active, key=lambda t: (not t.overdue, t.due_at))[:6]
    by_location = {}
    for t in tickets:
        by_location[t.location.label] = by_location.get(t.location.label, 0) + 1
    activity = db.session.scalars(db.select(Event).where(Event.company_id == g.company.id).order_by(Event.created_at.desc()).limit(5)).all()
    return render_template('dashboard.html', all_tickets=tickets, active=active, done=done,
        avg_hours=avg_hours, on_time=on_time, recent=recent, activity=activity,
        location_counts=sorted(by_location.items(), key=lambda x: -x[1])[:5])


@bp.get('/tickets/<int:ticket_id>')
@login_required
def ticket_detail(ticket_id):
    ticket = ticket_access(ticket_id)
    events = db.session.scalars(db.select(Event).where(Event.ticket_id == ticket.id).order_by(Event.created_at, Event.id)).all()
    attachments = db.session.scalars(db.select(Attachment).where(Attachment.ticket_id == ticket.id)).all()
    providers = db.session.scalars(db.select(Membership).where(Membership.company_id == ticket.company_id,
        Membership.role == 'provider', Membership.active.is_(True)).order_by(Membership.name)).all()
    manager = bool(g.membership and g.company.id == ticket.company_id and g.membership.role in ('owner', 'manager'))
    provider = bool(g.membership and g.membership.id == ticket.provider_id and g.membership.role == 'provider')
    return render_template('ticket_detail.html', ticket=ticket, events=events, attachments=attachments,
        providers=providers, manager=manager, provider=provider)


@bp.post('/tickets/<int:ticket_id>/manage')
@manager_required
def manage_ticket(ticket_id):
    ticket = scoped(Ticket, ticket_id)
    action = request.form.get('action')
    if ticket.updated_at.isoformat() != request.form.get('version'):
        abort(409)
    if action == 'assign':
        if ticket.status in ('Concluído', 'Cancelado', 'Em revisão'):
            raise ValidationError('Reabra o chamado antes de atribuir outro prestador.')
        provider = scoped(Membership, positive_int(request.form.get('provider_id'), 'prestador'))
        if provider.role != 'provider' or not provider.active:
            raise ValidationError('Selecione um prestador ativo.')
        ticket.provider = provider
        ticket.status = 'Atribuído'
        text = f'Ordem atribuída a {provider.name}.'
    elif action == 'approve':
        if ticket.status != 'Novo':
            abort(409)
        ticket.status = 'Aprovado'
        text = 'Chamado aprovado pela gestão.'
    elif action == 'accept':
        if ticket.status != 'Em revisão':
            abort(409)
        ticket.status = 'Concluído'
        ticket.completed_at = now()
        ticket.rating = positive_int(request.form.get('rating', 5), 'avaliação', 1, 5)
        text = f'Conclusão aprovada. Avaliação: {ticket.rating}/5.'
    elif action == 'reopen':
        reason = field('reason', 5, 1000)
        if ticket.status not in ('Em revisão', 'Concluído', 'Cancelado'):
            abort(409)
        ticket.status = 'Atribuído' if ticket.provider_id else 'Novo'
        ticket.completed_at = None
        ticket.rating = None
        text = f'Chamado reaberto: {reason}'
    elif action == 'cancel':
        reason = field('reason', 5, 1000)
        ticket.status = 'Cancelado'
        text = f'Chamado cancelado: {reason}'
    elif action == 'details':
        priority = request.form.get('priority')
        if priority not in PRIORITIES:
            raise ValidationError('Selecione uma prioridade válida.')
        ticket.priority = priority
        ticket.is_public = request.form.get('is_public') == 'on'
        try:
            local_due = datetime.strptime(request.form.get('due_at', ''), '%Y-%m-%dT%H:%M')
            ticket.due_at = local_due.replace(tzinfo=ZoneInfo(current_app.config['TIMEZONE'])).astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            raise ValidationError('Informe o prazo de atendimento.')
        text = 'Prioridade, prazo e visibilidade atualizados.'
    else:
        abort(400)
    ticket.updated_at = now()
    audit(ticket.company_id, text, ticket, 'status')
    notify_ticket(ticket, text)
    db.session.commit()
    flash(text, 'success')
    return redirect(url_for('main.ticket_detail', ticket_id=ticket.id))


@bp.post('/tickets/<int:ticket_id>/work')
@login_required
def work_ticket(ticket_id):
    ticket = ticket_access(ticket_id)
    if not g.membership or g.membership.role != 'provider' or ticket.provider_id != g.membership.id:
        abort(403)
    if ticket.updated_at.isoformat() != request.form.get('version'):
        abort(409)
    action = request.form.get('action')
    if action == 'start' and ticket.status in ('Atribuído', 'Aguardando'):
        ticket.status = 'Em andamento'
        ticket.started_at = ticket.started_at or now()
        text = 'Atendimento iniciado pelo prestador.'
    elif action == 'wait' and ticket.status == 'Em andamento':
        ticket.status = 'Aguardando'
        text = 'Atendimento aguardando: ' + field('note', 5, 1000)
    elif action == 'finish' and ticket.status == 'Em andamento':
        note = field('note', 5, 2000)
        if not request.files.get('photo') or not request.files['photo'].filename:
            raise ValidationError('Anexe uma foto do serviço para solicitar a aprovação.')
        upload(request.files.get('photo'), ticket.company_id, 'after', ticket_id=ticket.id)
        ticket.status = 'Em revisão'
        text = 'Serviço enviado para aprovação: ' + note
    else:
        raise ValidationError('Esta ação não está disponível no estado atual do chamado.')
    ticket.updated_at = now()
    audit(ticket.company_id, text, ticket, 'status')
    notify_ticket(ticket, 'Chamado atualizado: ' + ticket.status)
    db.session.commit()
    flash(text, 'success')
    return redirect(url_for('main.ticket_detail', ticket_id=ticket.id))


@bp.post('/tickets/<int:ticket_id>/comment')
@login_required
@limiter.limit('15 per minute')
def comment(ticket_id):
    ticket = ticket_access(ticket_id)
    text = field('message', 1, 3000)
    audit(ticket.company_id, text, ticket, 'comment')
    upload(request.files.get('photo'), ticket.company_id, 'before', ticket_id=ticket.id)
    ticket.updated_at = now()
    notify_ticket(ticket, 'Nova mensagem no chamado')
    db.session.commit()
    return redirect(url_for('main.ticket_detail', ticket_id=ticket.id) + '#history')


@bp.route('/locations', methods=['GET', 'POST'])
@manager_required
def locations():
    locations = db.session.scalars(db.select(Location).where(Location.company_id == g.company.id).order_by(Location.name)).all()
    if request.method == 'POST':
        location = scoped(Location, positive_int(request.form['id'])) if request.form.get('id') else Location(company_id=g.company.id)
        location.name = field('name', 2, 120)
        location.reference = field('reference', 0, 200)
        location.kind = request.form.get('kind', 'Ambiente')
        if location.kind not in ('Unidade', 'Ambiente', 'Equipamento'):
            raise ValidationError('Tipo de local inválido.')
        location.active = request.form.get('active') == 'on'
        if request.form.get('parent_id'):
            parent = scoped(Location, positive_int(request.form['parent_id']))
            if parent.parent_id or parent.id == location.id or not parent.active:
                raise ValidationError('Use uma unidade raiz como local superior.')
            if location.id and any(x.parent_id == location.id for x in locations):
                raise ValidationError('Este local tem ambientes vinculados e deve permanecer na raiz.')
            location.parent_id = parent.id
        else:
            location.parent_id = None
        db.session.add(location)
        audit(g.company.id, f'Local salvo: {location.name}.')
        db.session.commit()
        flash('Local salvo.', 'success')
        return redirect(url_for('main.locations'))
    edit = scoped(Location, positive_int(request.args['edit'])) if request.args.get('edit') else None
    return render_template('locations.html', locations=locations, edit=edit)


@bp.route('/points', methods=['GET', 'POST'])
@manager_required
def points():
    if request.method == 'POST':
        location = scoped(Location, positive_int(request.form.get('location_id'), 'local'))
        if not location.available:
            raise ValidationError('O local está desativado.')
        count = db.session.scalar(db.select(func.count(QRPoint.id)).where(QRPoint.company_id == g.company.id, QRPoint.active.is_(True)))
        if count >= g.company.point_limit:
            raise ValidationError('O limite de pontos do plano foi atingido. Desative um ponto antes de criar outro.')
        point = QRPoint(company_id=g.company.id, location_id=location.id)
        db.session.add(point)
        audit(g.company.id, f'QR Code criado para {location.label}.')
        db.session.commit()
        flash('QR Code criado e pronto para impressão.', 'success')
        return redirect(url_for('main.points'))
    points = db.session.scalars(db.select(QRPoint).where(QRPoint.company_id == g.company.id).order_by(QRPoint.created_at.desc())).all()
    locations = db.session.scalars(db.select(Location).where(Location.company_id == g.company.id, Location.active.is_(True)).order_by(Location.name)).all()
    return render_template('points.html', points=points, locations=locations)


@bp.post('/points/<int:point_id>/action')
@manager_required
def point_action(point_id):
    point = scoped(QRPoint, point_id)
    action = request.form.get('action')
    if action == 'replace':
        point.code = token()
        text = 'QR substituído. A etiqueta anterior deixou de funcionar.'
    elif action == 'disable':
        point.active = False
        text = 'QR desativado.'
    else:
        abort(400)
    audit(g.company.id, text + ' ' + point.location.label)
    db.session.commit()
    flash(text, 'success')
    return redirect(url_for('main.points'))


@bp.get('/points/<int:point_id>.png')
@manager_required
def qr_png(point_id):
    import qrcode
    point = scoped(QRPoint, point_id)
    image = qrcode.make(current_app.config['PUBLIC_BASE_URL'] + '/q/' + point.code, box_size=9, border=4)
    output = io.BytesIO()
    image.save(output, format='PNG')
    output.seek(0)
    return send_file(output, mimetype='image/png', as_attachment=request.args.get('download') == '1', download_name=f'HelpFlow-{point.location.name}.png')


@bp.get('/points/print')
@manager_required
def print_points():
    query = db.select(QRPoint).where(QRPoint.company_id == g.company.id, QRPoint.active.is_(True))
    if request.args.get('id'):
        query = query.where(QRPoint.id == positive_int(request.args['id']))
    return render_template('print.html', points=db.session.scalars(query).all())


@bp.route('/people', methods=['GET', 'POST'])
@manager_required
def people():
    kind = request.args.get('kind', 'providers')
    if kind not in ('providers', 'team'):
        abort(400)
    if request.method == 'POST':
        email, name = email_field(), field('name', 2, 100)
        role = 'provider' if kind == 'providers' else request.form.get('role', 'resident')
        if role not in ('provider', 'resident', 'manager'):
            abort(400)
        if role == 'manager' and g.membership.role != 'owner':
            abort(403)
        if db.session.scalar(db.select(Membership).where(Membership.company_id == g.company.id, Membership.email == email)):
            raise ValidationError('Esta pessoa já faz parte da empresa. Edite o cadastro existente.')
        member = Membership(company_id=g.company.id, email=email, name=name, role=role,
            specialty=field('specialty', 0, 120), phone=field('phone', 0, 40))
        db.session.add(member)
        db.session.flush()
        issue_invitation(member)
        audit(g.company.id, f'Convite criado para {member.name} ({role}).')
        db.session.commit()
        return redirect(url_for('main.person', member_id=member.id))
    query = db.select(Membership).where(Membership.company_id == g.company.id)
    query = query.where(Membership.role == 'provider') if kind == 'providers' else query.where(Membership.role != 'provider')
    members = db.session.scalars(query.order_by(Membership.name)).all()
    metrics = {}
    for member in members:
        tasks = db.session.scalars(db.select(Ticket).where(Ticket.company_id == g.company.id, Ticket.provider_id == member.id)).all()
        scores = [t.rating for t in tasks if t.rating]
        metrics[member.id] = {'active': sum(t.status not in ('Concluído', 'Cancelado') for t in tasks),
            'rating': round(sum(scores) / len(scores), 1) if scores else None}
    return render_template('people.html', members=members, kind=kind, metrics=metrics)


def issue_invitation(member):
    raw = token()
    for old in db.session.scalars(db.select(Invitation).where(Invitation.membership_id == member.id, Invitation.used_at.is_(None))):
        old.used_at = now()
    db.session.add(Invitation(membership_id=member.id, token_hash=digest(raw), expires_at=now() + timedelta(days=7)))
    db.session.add(Notification(company_id=member.company_id, user_id=member.user_id, email=member.email,
        title=f'Convite para {member.company.name}', body=f'{member.name}, acesse o link para aceitar seu convite no HelpFlow.', path='/invite/' + raw))
    session['last_invite'] = {'member_id': member.id, 'url': current_app.config['PUBLIC_BASE_URL'] + '/invite/' + raw}
    flash('Convite criado. Compartilhe o link com a pessoa convidada.', 'success')


@bp.route('/people/<int:member_id>', methods=['GET', 'POST'])
@manager_required
def person(member_id):
    member = scoped(Membership, member_id)
    if request.method == 'POST':
        if member.role == 'owner':
            raise ValidationError('O responsável da empresa não pode ser desativado por este formulário.')
        if g.membership.role != 'owner' and member.role == 'manager':
            abort(403)
        action = request.form.get('action')
        if action == 'invite':
            if not member.active:
                raise ValidationError('Reative a pessoa antes de gerar um convite.')
            issue_invitation(member)
        elif action == 'document':
            expires = request.form.get('expires_at')
            try:
                expires = datetime.strptime(expires, '%Y-%m-%d').date() if expires else None
            except ValueError:
                raise ValidationError('Data de vencimento inválida.')
            if not request.files.get('file') or not request.files['file'].filename:
                raise ValidationError('Escolha o documento.')
            upload(request.files.get('file'), g.company.id, 'document', membership_id=member.id, expires_at=expires)
            flash('Documento guardado.', 'success')
        elif action == 'edit':
            active = request.form.get('active') == 'on'
            if not active and db.session.scalar(db.select(Ticket.id).where(Ticket.provider_id == member.id,
                Ticket.status.not_in(['Concluído', 'Cancelado'])).limit(1)):
                raise ValidationError('Reatribua ou conclua as demandas abertas antes de desativar este prestador.')
            member.name = field('name', 2, 100)
            member.phone = field('phone', 0, 40)
            member.specialty = field('specialty', 0, 120)
            member.notes = field('notes', 0, 3000)
            member.active = active
            flash('Cadastro atualizado.', 'success')
        else:
            abort(400)
        audit(g.company.id, f'Cadastro atualizado: {member.name} ({action}).')
        db.session.commit()
        return redirect(request.path)
    documents = db.session.scalars(db.select(Attachment).where(Attachment.membership_id == member.id)).all()
    tasks = db.session.scalars(db.select(Ticket).where(Ticket.provider_id == member.id, Ticket.company_id == g.company.id).order_by(Ticket.updated_at.desc())).all()
    invite = session.get('last_invite', {})
    invite_url = invite.get('url') if invite.get('member_id') == member.id else None
    return render_template('person.html', member=member, documents=documents, tasks=tasks, invite_url=invite_url, today=now().date())


@bp.route('/settings', methods=['GET', 'POST'])
@manager_required
def settings():
    if request.method == 'POST':
        g.company.name = field('name', 2, 120)
        accent = request.form.get('accent', '#236448')
        if accent not in ('#236448', '#245a9c', '#784933', '#313131'):
            raise ValidationError('Escolha uma das cores disponíveis.')
        g.company.accent = accent
        g.company.sla_hours = positive_int(request.form.get('sla_hours'), 'prazo', 1, 720)
        g.company.public_portal = request.form.get('public_portal') == 'on'
        g.company.email_alerts = request.form.get('email_alerts') == 'on'
        image = upload(request.files.get('logo'), g.company.id, 'logo')
        if image:
            g.company.logo_id = image.id
        audit(g.company.id, 'Preferências da empresa atualizadas.')
        db.session.commit()
        flash('Configurações salvas.', 'success')
        return redirect(request.path)
    count = db.session.scalar(db.select(func.count(QRPoint.id)).where(QRPoint.company_id == g.company.id, QRPoint.active.is_(True)))
    return render_template('settings.html', point_count=count)


@bp.get('/files/<int:file_id>')
@login_required
def attachment(file_id):
    from pathlib import Path
    item = db.get_or_404(Attachment, file_id)
    if item.ticket_id:
        ticket_access(item.ticket_id)
    else:
        if not g.membership or g.membership.company_id != item.company_id:
            abort(404)
        if g.membership.role not in ('owner', 'manager') and item.membership_id != g.membership.id and item.kind != 'logo':
            abort(404)
    return send_file(Path(current_app.config['UPLOAD_FOLDER']) / item.storage_name,
        mimetype=item.mime, as_attachment=item.mime == 'application/pdf' or request.args.get('download') == '1', download_name=item.name)


@bp.route('/notifications', methods=['GET', 'POST'])
@login_required
def notifications():
    if request.method == 'POST':
        db.session.execute(db.update(Notification).where(Notification.user_id == current_user.id,
            Notification.read_at.is_(None)).values(read_at=now()))
        db.session.commit()
        return redirect(request.path)
    items = db.session.scalars(db.select(Notification).where(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc()).limit(100)).all()
    return render_template('notifications.html', items=items)


@bp.post('/notifications/<int:notification_id>/open')
@login_required
def open_notification(notification_id):
    item = db.first_or_404(db.select(Notification).where(Notification.id == notification_id,
                                                        Notification.user_id == current_user.id))
    if item.company_id:
        member = db.session.scalar(db.select(Membership).where(Membership.company_id == item.company_id,
            Membership.user_id == current_user.id, Membership.active.is_(True)))
        if member:
            session['company_id'] = member.company_id
    item.read_at = now()
    db.session.commit()
    from .services import safe_next
    return redirect(safe_next(item.path))


@bp.get('/reports.csv')
@manager_required
def export_csv():
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['Protocolo', 'Problema', 'Local', 'Categoria', 'Prioridade', 'Status', 'Prestador', 'Criado', 'Prazo', 'Concluído', 'Avaliação'])
    def safe_cell(value):
        text = str(value or '')
        return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text
    for ticket in db.session.scalars(filtered_tickets().order_by(Ticket.created_at.desc())):
        writer.writerow([safe_cell(v) for v in [ticket.reference, ticket.title, ticket.location.label,
            ticket.category, ticket.priority, ticket.status, ticket.provider.name if ticket.provider else '',
            ticket.created_at, ticket.due_at, ticket.completed_at, ticket.rating]])
    return send_file(io.BytesIO(output.getvalue().encode('utf-8-sig')), mimetype='text/csv', as_attachment=True,
        download_name=f'HelpFlow-{g.company.slug}.csv')
