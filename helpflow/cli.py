import os
import time
import smtplib
from datetime import timedelta
from pathlib import Path
from email.message import EmailMessage
import click
from flask import current_app
from .extensions import db
from .models import User, Company, Membership, Location, QRPoint, Ticket, Event, Notification, now


def seed_demo(password):
    if os.getenv('APP_ENV') == 'production':
        raise RuntimeError('Demonstração não permitida em produção.')
    if len(password) < 8:
        raise RuntimeError('Informe uma senha demo com pelo menos 8 caracteres.')
    if db.session.scalar(db.select(Company).where(Company.slug == 'edificio-aurora')):
        return False
    accounts = [('Marina Silva', 'marina@aurora.com.br'), ('Ana Costa', 'ana@email.com'),
                ('Lucas Ferreira', 'lucas@eletrika.com.br'), ('ClimaPro Serviços', 'contato@climapro.com.br')]
    users = []
    for name, email in accounts:
        user = db.session.scalar(db.select(User).where(User.email == email))
        if not user:
            user = User(name=name, email=email)
            user.set_password(password)
            db.session.add(user)
        users.append(user)
    company = Company(name='Edifício Aurora', slug='edificio-aurora', email_alerts=False)
    other = Company(name='Escritório Central', slug='escritorio-central', email_alerts=False)
    db.session.add_all([company, other])
    db.session.flush()
    members = []
    for user, role, specialty in zip(users, ['owner', 'resident', 'provider', 'provider'], ['', '', 'Elétrica', 'Climatização']):
        member = Membership(company_id=company.id, user_id=user.id, name=user.name, email=user.email,
                            role=role, specialty=specialty)
        db.session.add(member)
        members.append(member)
    db.session.add(Membership(company_id=other.id, user_id=users[0].id, name=users[0].name, email=users[0].email, role='owner'))
    db.session.flush()
    building = Location(company_id=company.id, name='Torre A', kind='Unidade', reference='Entrada principal')
    db.session.add(building)
    db.session.flush()
    data = [('Copa · 8º andar', 'Vazamento sob a pia', 'Hidráulica', 'Novo', None, 3),
            ('Garagem · B2', 'Lâmpada piscando no corredor', 'Elétrica', 'Atribuído', members[2].id, 20),
            ('Sala Ipê', 'Maçaneta precisa de ajuste', 'Manutenção geral', 'Aprovado', None, 7),
            ('Sala 402', 'Ar-condicionado não resfria', 'Climatização', 'Em andamento', members[3].id, 28),
            ('Recepção', 'Luminária da entrada substituída', 'Elétrica', 'Concluído', members[2].id, 60)]
    for index, (local, title, category, status, provider, hours) in enumerate(data):
        location = Location(company_id=company.id, parent_id=building.id, name=local, kind='Ambiente')
        db.session.add(location)
        db.session.flush()
        db.session.add(QRPoint(company_id=company.id, location_id=location.id))
        ticket = Ticket(company_id=company.id, location_id=location.id, requester_id=users[1].id,
            title=title, description=title + '. Solicitamos uma avaliação no local para resolver o problema.',
            category=category, status=status, provider_id=provider, priority='Alta' if hours == 28 else 'Normal',
            due_at=now() + timedelta(hours=12-hours), created_at=now()-timedelta(hours=hours),
            updated_at=now()-timedelta(hours=max(hours-5, 0)), is_public=True)
        if status == 'Concluído':
            ticket.completed_at=now()-timedelta(hours=55)
            ticket.rating=5
        if status == 'Em andamento':
            ticket.started_at=now()-timedelta(hours=24)
        db.session.add(ticket)
        db.session.flush()
        db.session.add(Event(company_id=company.id, ticket_id=ticket.id, actor_id=users[1].id,
            text='Chamado cadastrado na demonstração.', kind='status', created_at=ticket.created_at))
    db.session.commit()
    return True


def check_overdue():
    count = 0
    tickets = db.session.scalars(db.select(Ticket).where(Ticket.due_at < now(),
        Ticket.status.not_in(['Concluído', 'Cancelado', 'Em revisão']))).all()
    for ticket in tickets:
        members = db.session.scalars(db.select(Membership).where(Membership.company_id == ticket.company_id,
            Membership.active.is_(True), Membership.user_id.is_not(None),
            db.or_(Membership.role.in_(['owner', 'manager']), Membership.id == ticket.provider_id))).all()
        for member in members:
            key = f'overdue:{ticket.id}:{member.user_id}:{ticket.due_at.isoformat()}'
            if not db.session.scalar(db.select(Notification.id).where(Notification.dedupe_key == key)):
                db.session.add(Notification(company_id=ticket.company_id, user_id=member.user_id,
                    email=member.email, title='Prazo de atendimento vencido', body=f'{ticket.reference} · {ticket.title}',
                    path=f'/tickets/{ticket.id}', dedupe_key=key, send_email=ticket.company.email_alerts))
                count += 1
    db.session.commit()
    return count


def check_documents():
    from .models import Attachment
    count = 0
    documents = db.session.scalars(db.select(Attachment).where(Attachment.kind == 'document',
        Attachment.expires_at.is_not(None), Attachment.expires_at <= now().date() + timedelta(days=7))).all()
    for document in documents:
        managers = db.session.scalars(db.select(Membership).where(Membership.company_id == document.company_id,
            Membership.active.is_(True), Membership.role.in_(['owner', 'manager']), Membership.user_id.is_not(None))).all()
        stage = 'expired' if document.expires_at < now().date() else 'soon'
        for manager in managers:
            key = f'document:{document.id}:{manager.user_id}:{document.expires_at}:{stage}'
            if not db.session.scalar(db.select(Notification.id).where(Notification.dedupe_key == key)):
                db.session.add(Notification(company_id=document.company_id, user_id=manager.user_id, email=manager.email,
                    title='Documento vencido' if stage == 'expired' else 'Documento vence em breve',
                    body=f'{document.name} - vencimento em {document.expires_at.strftime("%d/%m/%Y")}',
                    path=f'/people/{document.membership_id}', dedupe_key=key, send_email=manager.company.email_alerts))
                count += 1
    db.session.commit()
    return count


def deliver_mail():
    mode = current_app.config['MAIL_MODE']
    messages = db.session.scalars(db.select(Notification).where(Notification.sent_at.is_(None),
        Notification.send_email.is_(True), Notification.attempts < 5).order_by(Notification.id).limit(30)).all()
    sent = 0
    for item in messages:
        message = EmailMessage()
        message['From'] = os.getenv('SMTP_FROM', 'HelpFlow <no-reply@example.com>')
        message['To'] = item.email
        message['Subject'] = item.title
        message.set_content(item.body + '\n\n' + current_app.config['PUBLIC_BASE_URL'] + item.path)
        try:
            if mode == 'smtp':
                host = os.getenv('SMTP_HOST')
                if not host:
                    raise RuntimeError('Configure SMTP_HOST.')
                with smtplib.SMTP(host, int(os.getenv('SMTP_PORT', '587')), timeout=15) as smtp:
                    if os.getenv('SMTP_TLS', 'true') == 'true':
                        smtp.starttls()
                    if os.getenv('SMTP_USERNAME'):
                        smtp.login(os.environ['SMTP_USERNAME'], os.environ.get('SMTP_PASSWORD', ''))
                    smtp.send_message(message)
            elif mode == 'outbox':
                folder = Path(current_app.instance_path) / 'outbox'
                folder.mkdir(exist_ok=True)
                (folder / f'{item.id:06d}.eml').write_bytes(message.as_bytes())
            else:
                raise RuntimeError('MAIL_MODE deve ser smtp ou outbox.')
            item.sent_at = now()
            sent += 1
        except Exception:
            # Keep messages for explicit retry; never include credentials or message bodies in logs.
            current_app.logger.error('Falha ao processar notificação %s', item.id)
            item.attempts += 1
        db.session.commit()
    return sent


def register_cli(app):
    @app.cli.command('seed-demo')
    @click.option('--password', envvar='DEMO_PASSWORD', required=True)
    def seed(password):
        click.echo('Demonstração criada.' if seed_demo(password) else 'Demonstração já existe; nada foi alterado.')

    @app.cli.command('process-jobs')
    def jobs():
        click.echo(f'{check_overdue() + check_documents()} alertas criados; {deliver_mail()} mensagens processadas.')

    @app.cli.command('worker')
    def worker():
        click.echo('Worker HelpFlow ativo. Ctrl+C para parar.')
        while True:
            try:
                check_overdue()
                check_documents()
                deliver_mail()
            except Exception:
                db.session.rollback()
                app.logger.exception('Falha no ciclo do worker')
            finally:
                db.session.remove()
            time.sleep(30)

    @app.cli.command('backup')
    @click.argument('destination', type=click.Path(path_type=Path))
    def backup(destination):
        import sqlite3
        import zipfile
        import tempfile
        from contextlib import closing
        if db.engine.dialect.name != 'sqlite':
            raise click.ClickException('Para PostgreSQL, use pg_dump e copie instance/uploads. Veja README.')
        if destination.exists():
            raise click.ClickException('O destino já existe. Escolha outro arquivo.')
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / 'helpflow.db'
            with closing(sqlite3.connect(db.engine.url.database)) as source, closing(sqlite3.connect(snapshot)) as target:
                source.backup(target)
            with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(snapshot, 'helpflow.db')
                for item in Path(app.config['UPLOAD_FOLDER']).glob('*'):
                    if item.is_file():
                        archive.write(item, 'uploads/' + item.name)
        click.echo(f'Backup criado: {destination}')
