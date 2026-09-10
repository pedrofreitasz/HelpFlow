import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
import os
import uuid
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from flask_migrate import upgrade
from helpflow import create_app
from helpflow.extensions import db
from helpflow.cli import seed_demo


@pytest.fixture
def app(tmp_path):
    pg_url = os.getenv('TEST_POSTGRESQL_URL')
    admin = None
    test_database = 'hf_test_' + uuid.uuid4().hex
    uri = 'sqlite:///' + str(tmp_path / 'test.db')
    if pg_url:
        admin = create_engine(pg_url, isolation_level='AUTOCOMMIT')
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{test_database}"'))
        uri = make_url(pg_url).set(database=test_database).render_as_string(hide_password=False)
    app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only',
        'SQLALCHEMY_DATABASE_URI': uri,
        'UPLOAD_FOLDER': str(tmp_path / 'uploads'), 'WTF_CSRF_ENABLED': False,
        'RATELIMIT_ENABLED': False, 'MAIL_MODE': 'outbox'})
    app.instance_path = str(tmp_path)
    with app.app_context():
        upgrade()
        seed_demo('Testing2026!')
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()
    if admin:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{test_database}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def sign_in(client, email='marina@aurora.com.br', password='Testing2026!'):
    response = client.post('/login', data={'email': email, 'password': password})
    assert response.status_code == 302
    return response
