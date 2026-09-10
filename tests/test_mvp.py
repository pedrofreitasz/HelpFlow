import io
import json
import re
import shutil
import subprocess
from datetime import timedelta
from pathlib import Path
import pytest
from PIL import Image
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from helpflow import create_app
from helpflow.extensions import db
from helpflow.models import User, Company, Membership, Location, QRPoint, Ticket, Attachment, Invitation, Notification, PasswordReset, now, token
from helpflow.cli import check_overdue, check_documents, deliver_mail
from scripts.transfer_database import transfer
from scripts.restore_backup import restore
from conftest import sign_in


def photo():
    output = io.BytesIO()
    Image.new('RGB', (64, 64), '#cccccc').save(output, 'PNG')
    output.seek(0)
    return output, 'prova.png'


def version(app, ticket_id):
    with app.app_context():
        return db.session.get(Ticket, ticket_id).updated_at.isoformat()


def payload(**kwargs):
    return dict(title='Vazamento de teste', description='Há água vazando abaixo da pia da copa.',
                category='Hidráulica', priority='Normal', submission_key=token(), **kwargs)


@pytest.mark.parametrize('path', ['/', '/login', '/register', '/forgot-password', '/scan', '/c/edificio-aurora', '/health'])
def test_public_pages(client, path):
    assert client.get(path).status_code == 200


def test_all_manager_pages(app, client):
    sign_in(client)
    for path in ['/dashboard', '/tickets', '/companies', '/locations', '/locations?edit=2', '/points',
        '/points/print', '/points/1.png', '/people', '/people?kind=team', '/people/3', '/settings',
        '/notifications', '/account', '/tickets/1', '/c/edificio-aurora/report', '/reports.csv']:
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers['X-Content-Type-Options'] == 'nosniff'


def test_login_logout_password_and_csrf(app, client):
    assert client.post('/login', data={'email': 'marina@aurora.com.br', 'password': 'bad'}).status_code == 400
    sign_in(client)
    assert client.post('/account', data={'action': 'password', 'current_password': 'bad', 'password': 'NewPassword2026!'}).status_code == 400
    assert client.post('/logout').status_code == 302
    assert client.get('/dashboard').status_code == 302
    app.config['WTF_CSRF_ENABLED'] = True
    assert client.post('/login', data={'email': 'marina@aurora.com.br', 'password': 'Testing2026!'}).status_code == 400
    page = client.get('/login').text
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    assert client.post('/login', data={'email': 'marina@aurora.com.br', 'password': 'Testing2026!', 'csrf_token': csrf}).status_code == 302
    assert client.post('/logout').status_code == 400


def test_register_company_and_switch(app, client):
    response = client.post('/register', data={'name': 'Joana Lima', 'email': 'joana@example.com', 'password': 'Testing2026!', 'next': '//evil.example/'})
    assert response.location == '/workspace'
    assert client.get('/workspace').location == '/tickets?mine=1'
    assert client.post('/companies', data={'name': 'Joana Facilities'}).status_code == 302
    with app.app_context():
        company = db.session.scalar(db.select(Company).where(Company.slug == 'joana-facilities'))
        own = company.id
        member = db.session.scalar(db.select(Membership).where(Membership.company_id == own))
        assert member.role == 'owner'
        assert member.user.check_password('Testing2026!')
        assert 'Testing2026!' not in member.user.password_hash
    assert client.post('/companies/1/switch').status_code == 403
    assert client.post(f'/companies/{own}/switch').status_code == 302
    assert client.get('/tickets/1').status_code == 404


def test_public_summary_redacts_personal_data(app, client):
    page = client.get('/c/edificio-aurora').text
    assert 'Hidráulica' in page
    assert 'Ana Costa' not in page
    assert 'ana@email.com' not in page
    assert 'Solicitamos uma avaliação' not in page
    assert 'Vazamento sob a pia' not in page
    assert client.get('/tickets/1').status_code == 302
    with app.app_context():
        t = db.session.get(Ticket, 1)
        reference = t.reference
        t.is_public = False
        db.session.commit()
    assert reference not in client.get('/c/edificio-aurora').text


def test_qr_report_login_idempotency_and_image(app, client):
    with app.app_context():
        point = db.session.get(QRPoint, 1)
        code = point.code
    assert client.get('/q/' + code).status_code == 200
    assert '/login' in client.post('/q/' + code, data=payload()).location
    sign_in(client, 'ana@email.com')
    data = payload()
    saved = client.post('/q/' + code, data=dict(data, photo=photo()), content_type='multipart/form-data')
    assert saved.status_code == 302
    repeated = client.post('/q/' + code, data=data)
    assert repeated.location == saved.location
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Ticket.id))) == 6
        t = db.session.scalar(db.select(Ticket).where(Ticket.submit_key == data['submission_key']))
        assert t.location_id == 2 and t.company_id == 1
        assert not t.is_public
        file = db.session.scalar(db.select(Attachment).where(Attachment.ticket_id == t.id))
        assert file.mime == 'image/jpeg'
        file_id = file.id
        assert Path(app.config['UPLOAD_FOLDER'], file.storage_name).exists()
    assert client.get(f'/files/{file_id}').status_code == 200
    client.post('/logout')
    assert client.get(f'/files/{file_id}').status_code == 302
    sign_in(client, 'contato@climapro.com.br')
    assert client.get(f'/files/{file_id}').status_code == 404


def test_qr_generation_decoder_replacement_and_limit(app, client):
    sign_in(client)
    image_data = client.get('/points/1.png').data
    assert image_data[:8] == b'\x89PNG\r\n\x1a\n'
    with app.app_context():
        code = db.session.get(QRPoint, 1).code
    if shutil.which('node'):
        image = Image.open(io.BytesIO(image_data)).convert('RGBA')
        decoder = Path(__file__).resolve().parents[1] / 'helpflow/static/vendor/jsQR.js'
        js = "const qr=require(process.argv[1]);let s='';process.stdin.on('data',d=>s+=d);process.stdin.on('end',()=>{let p=JSON.parse(s);let r=qr(new Uint8ClampedArray(p.pixels),p.w,p.h);process.stdout.write(r.data);});"
        result = subprocess.run(['node', '-e', js, str(decoder)], input=json.dumps({'w': image.width, 'h': image.height, 'pixels': list(image.tobytes())}), text=True, capture_output=True, check=True)
        assert result.stdout == 'http://localhost:5000/q/' + code
    assert client.get('/scan', query_string={'code': 'https://evil.example/q/' + code}).status_code == 400
    assert client.get('/scan', query_string={'code': 'http://localhost:5000/q/' + code}).location == '/q/' + code
    assert client.post('/points/1/action', data={'action': 'replace'}).status_code == 302
    assert client.get('/q/' + code).status_code == 404
    with app.app_context():
        new_code = db.session.get(QRPoint, 1).code
        db.session.get(Company, 1).point_limit = 5
        db.session.commit()
    assert client.post('/points', data={'location_id': 2}).status_code == 400
    assert client.post('/points/1/action', data={'action': 'disable'}).status_code == 302
    assert client.get('/q/' + new_code).status_code == 410


def test_tenant_scope_and_provider_permissions(app, client):
    sign_in(client)
    client.post('/companies/2/switch')
    for path in ['/tickets/1', '/people/3', '/locations?edit=2', '/points/1.png']:
        assert client.get(path).status_code == 404
    assert client.post('/tickets/1/manage', data={'action': 'assign', 'version': version(app, 1), 'provider_id': 3}).status_code == 404
    client.post('/logout')
    sign_in(client, 'lucas@eletrika.com.br')
    assert client.get('/tickets/2').status_code == 200
    assert client.get('/tickets/4').status_code == 404
    for path in ['/dashboard', '/people', '/locations', '/settings', '/reports.csv']:
        assert client.get(path).status_code == 403
    assert client.post('/tickets/2/manage', data={'action': 'approve'}).status_code == 403
    assert client.post('/companies/2/switch').status_code == 403


def test_ticket_complete_lifecycle_and_reassignment(app, client):
    sign_in(client)
    old = version(app, 1)
    assert client.post('/tickets/1/manage', data={'action': 'approve', 'version': old}).status_code == 302
    assert client.post('/tickets/1/manage', data={'action': 'approve', 'version': old}).status_code == 409
    assert client.post('/tickets/1/manage', data={'action': 'assign', 'provider_id': 3, 'version': version(app, 1)}).status_code == 302
    client.post('/logout')
    sign_in(client, 'lucas@eletrika.com.br')
    assert client.post('/tickets/1/work', data={'action': 'start', 'version': version(app, 1)}).status_code == 302
    assert client.post('/tickets/1/work', data={'action': 'wait', 'note': 'Aguardando chegada da peça.', 'version': version(app, 1)}).status_code == 302
    client.post('/tickets/1/work', data={'action': 'start', 'version': version(app, 1)})
    assert client.post('/tickets/1/work', data={'action': 'finish', 'note': 'Peça substituída.', 'version': version(app, 1)}).status_code == 400
    assert client.post('/tickets/1/work', data={'action': 'finish', 'note': 'Peça substituída.', 'photo': photo(), 'version': version(app, 1)}, content_type='multipart/form-data').status_code == 302
    with app.app_context():
        assert db.session.get(Ticket, 1).status == 'Em revisão'
    client.post('/logout')
    sign_in(client)
    assert client.post('/tickets/1/manage', data={'action': 'accept', 'rating': 4, 'version': version(app, 1)}).status_code == 302
    with app.app_context():
        assert db.session.get(Ticket, 1).status == 'Concluído'
        assert db.session.get(Ticket, 1).rating == 4
    assert client.post('/tickets/1/manage', data={'action': 'reopen', 'reason': 'O vazamento retornou.', 'version': version(app, 1)}).status_code == 302
    assert client.post('/tickets/1/manage', data={'action': 'assign', 'provider_id': 4, 'version': version(app, 1)}).status_code == 302
    with app.app_context():
        notifications = db.session.scalars(db.select(Notification).where(Notification.title.like('Ordem atribuída%'))).all()
        assert any(n.user_id == 4 for n in notifications)
    client.post('/logout')
    sign_in(client, 'lucas@eletrika.com.br')
    assert client.get('/tickets/1').status_code == 404


def test_real_concurrent_update_guard(app):
    with app.app_context():
        with Session(db.engine) as a, Session(db.engine) as b:
            first, second = a.get(Ticket, 1), b.get(Ticket, 1)
            first.title = 'Primeira edição salva'
            a.commit()
            second.title = 'Edição antiga não pode sobrescrever'
            with pytest.raises(StaleDataError):
                b.commit()
            b.rollback()


def test_invite_register_accept_and_deactivate(app, client):
    sign_in(client)
    created = client.post('/people', data={'name': 'Novo Técnico', 'email': 'tecnico@example.com', 'specialty': 'Hidráulica', 'phone': '11999990000'})
    assert created.status_code == 302
    with client.session_transaction() as state:
        invite_url = state['last_invite']['url'].replace('http://localhost:5000', '')
    with app.app_context():
        member = db.session.scalar(db.select(Membership).where(Membership.email == 'tecnico@example.com'))
        member_id = member.id
        assert member.user_id is None
        assert db.session.scalar(db.select(Invitation).where(Invitation.membership_id == member_id)).token_hash not in invite_url
    assert client.post(invite_url).status_code == 400
    client.post('/logout')
    client.post('/register', data={'name': 'Novo Técnico', 'email': 'tecnico@example.com', 'password': 'Testing2026!'})
    assert client.post(invite_url).status_code == 302
    assert client.get(invite_url).status_code == 410
    assert client.get('/people').status_code == 403
    provider_client = client
    manager = app.test_client()
    sign_in(manager)
    assert manager.post(f'/people/{member_id}', data={'action': 'edit', 'name': 'Novo Técnico', 'specialty': 'Hidráulica', 'phone': '', 'notes': ''}).status_code == 302
    assert provider_client.post('/companies/1/switch').status_code == 403


def test_provider_deactivation_requires_reassignment(app, client):
    sign_in(client)
    assert client.post('/people/3', data={'action': 'edit', 'name': 'Lucas Ferreira'}).status_code == 400
    assert client.post('/people/1', data={'action': 'edit', 'name': 'Marina Silva'}).status_code == 400


def test_documents_settings_logo_and_local_deactivation(app, client):
    sign_in(client)
    assert client.post('/people/3', data={'action': 'document', 'file': (io.BytesIO(b'%PDF-1.4\n%%EOF'), 'contrato.pdf'), 'expires_at': '2026-01-01'}, content_type='multipart/form-data').status_code == 302
    assert 'Vencido' in client.get('/people/3').text
    with app.app_context():
        assert check_documents() == 1
        assert check_documents() == 0
    assert client.post('/settings', data={'name': 'Aurora Facilities', 'accent': '#245a9c', 'sla_hours': 36, 'public_portal': 'on', 'logo': photo()}, content_type='multipart/form-data').status_code == 302
    with app.app_context():
        company = db.session.get(Company, 1)
        assert company.sla_hours == 36 and company.logo_id
        code = db.session.get(QRPoint, 1).code
    assert client.post('/locations', data={'id': 2, 'name': 'Copa', 'kind': 'Ambiente', 'parent_id': 1}).status_code == 302
    assert client.get('/q/' + code).status_code == 410
    assert client.post('/points', data={'location_id': 2}).status_code == 400


def test_bad_uploads_are_rejected_and_no_ticket_commits(app, client):
    sign_in(client, 'ana@email.com')
    with app.app_context():
        code = db.session.get(QRPoint, 1).code
    for binary in [b'<script>alert(1)</script>', b'x' * (5*1024*1024 + 1)]:
        assert client.post('/q/' + code, data=payload(photo=(io.BytesIO(binary), 'fake.jpg')), content_type='multipart/form-data').status_code == 400
    with app.app_context():
        assert db.session.scalar(db.select(db.func.count(Ticket.id))) == 5


def test_recovery_outbox_and_session_revocation(app, client):
    sign_in(client)
    other = app.test_client()
    assert other.post('/forgot-password', data={'email': 'marina@aurora.com.br'}).status_code == 302
    with app.app_context():
        message = db.session.scalar(db.select(Notification).where(Notification.title == 'Redefina sua senha'))
        path = message.path
        assert message.user_id is None
        assert deliver_mail() == 1
        assert deliver_mail() == 0
        assert list(Path(app.instance_path, 'outbox').glob('*.eml'))
    assert other.post(path, data={'password': 'Changed2026!'}).status_code == 302
    assert other.get(path).status_code == 410
    assert client.get('/dashboard').status_code == 302
    sign_in(other, password='Changed2026!')
    assert other.get('/dashboard').status_code == 200


def test_overdue_notifications_dedupe_and_tenant_switch(app, client):
    with app.app_context():
        first = check_overdue()
        assert first >= 2 and check_overdue() == 0
        item = db.session.scalar(db.select(Notification).where(Notification.user_id == 1))
        notification_id, path = item.id, item.path
    sign_in(client)
    client.post('/companies/2/switch')
    assert client.post(f'/notifications/{notification_id}/open').location == path
    assert client.get(path).status_code == 200
    with app.app_context():
        assert db.session.get(Notification, notification_id).read_at


def test_csv_filter_xss_timezone_and_pagination(app, client):
    sign_in(client)
    with app.app_context():
        ticket = db.session.get(Ticket, 1)
        ticket.title = '=HYPERLINK("bad") <script>alert(1)</script>'
        for i in range(22):
            db.session.add(Ticket(company_id=1, location_id=2, requester_id=2, title=f'Chamado {i}', description='Uma descrição suficientemente longa.', category='Hidráulica', due_at=now()+timedelta(hours=12), is_public=True))
        db.session.commit()
    assert '<script>alert(1)</script>' not in client.get('/tickets/1').text
    csv = client.get('/reports.csv').data.decode('utf-8-sig')
    assert "'=HYPERLINK" in csv
    assert 'Hidráulica' not in client.get('/reports.csv?status=Conclu%C3%ADdo').text
    assert client.get('/tickets?page=2').status_code == 200
    assert client.get('/c/edificio-aurora?page=2').status_code == 200
    assert client.get('/tickets?from=bad').status_code == 400
    assert client.post('/tickets/1/manage', data={'action': 'details', 'priority': 'Alta', 'due_at': '2026-09-12T12:00', 'version': version(app, 1), 'is_public': 'on'}).status_code == 302
    with app.app_context():
        assert db.session.get(Ticket, 1).due_at.hour == 15


def test_database_copy_backup_restore_and_restart(app, tmp_path, client):
    source = app.config['SQLALCHEMY_DATABASE_URI']
    if not source.startswith('sqlite:'):
        pytest.skip('Backup ZIP é exclusivo de SQLite; PostgreSQL usa pg_dump.')
    target = 'sqlite:///' + str(tmp_path / 'copy.db')
    totals = transfer(source, target)
    assert totals['ticket'] == 5 and totals['user'] == 4
    with pytest.raises(ValueError):
        transfer(source, target)
    with pytest.raises(ValueError):
        transfer(source, source)
    result = app.test_cli_runner().invoke(args=['backup', str(tmp_path / 'backup.zip')])
    assert result.exit_code == 0, result.output
    restored = restore(tmp_path / 'backup.zip', tmp_path / 'restored')
    with pytest.raises(ValueError):
        restore(tmp_path / 'backup.zip', restored)
    new_app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only', 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + str(restored / 'helpflow.db'), 'UPLOAD_FOLDER': str(restored / 'uploads'), 'WTF_CSRF_ENABLED': False, 'RATELIMIT_ENABLED': False})
    with new_app.app_context():
        assert db.session.scalar(db.select(db.func.count(Ticket.id))) == 5
        db.session.remove()
        db.engine.dispose()
    fresh = new_app.test_client()
    sign_in(fresh)
    assert fresh.get('/dashboard').status_code == 200
