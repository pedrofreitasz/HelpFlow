import os
import secrets
from pathlib import Path
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy.orm.exc import StaleDataError
from sqlalchemy.exc import IntegrityError
from flask import Flask, g, session, render_template, request
from flask_login import current_user
from dotenv import load_dotenv
from sqlalchemy import event
from sqlalchemy.engine import Engine
import sqlite3
from .extensions import db, login_manager, csrf, migrate, limiter


@event.listens_for(Engine, 'connect')
def sqlite_constraints(connection, _):
    if isinstance(connection, sqlite3.Connection):
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=10000')


def create_app(config=None):
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / '.env')
    app = Flask(__name__, instance_path=str(root / 'instance'))
    Path(app.instance_path).mkdir(exist_ok=True)
    production = os.getenv('APP_ENV') == 'production'
    secret = os.getenv('SECRET_KEY')
    if not secret:
        if production and not config:
            raise RuntimeError('Configure SECRET_KEY em produção.')
        secret_file = Path(app.instance_path) / '.secret'
        if not secret_file.exists():
            secret_file.write_text(secrets.token_hex(32), encoding='utf-8')
        secret = secret_file.read_text(encoding='utf-8')
    uri = os.getenv('DATABASE_URL') or 'sqlite:///helpflow.db'
    if uri.startswith(('postgres://', 'postgresql://')):
        uri = 'postgresql+psycopg://' + uri.split('://', 1)[1]
    app.config.update(
        SECRET_KEY=secret, SQLALCHEMY_DATABASE_URI=uri,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={'pool_pre_ping': True},
        MAX_CONTENT_LENGTH=12 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=production, PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        REMEMBER_COOKIE_HTTPONLY=True, REMEMBER_COOKIE_SECURE=production,
        PUBLIC_BASE_URL=os.getenv('PUBLIC_BASE_URL', 'http://localhost:5000').rstrip('/'),
        UPLOAD_FOLDER=os.getenv('UPLOAD_FOLDER') or str(root / 'instance' / 'uploads'),
        MAIL_MODE=os.getenv('MAIL_MODE', 'outbox'),
        TIMEZONE=os.getenv('TIMEZONE', 'America/Sao_Paulo'),
        RATELIMIT_STORAGE_URI=os.getenv('RATELIMIT_STORAGE_URI', 'memory://'),
        WTF_CSRF_TIME_LIMIT=12 * 3600,
    )
    if config:
        app.config.update(config)
    Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Entre para continuar. Seu local será mantido.'
    csrf.init_app(app)
    limiter.init_app(app)
    migrate.init_app(app, db, directory=str(root / 'migrations'), render_as_batch=True)
    from .models import User, Membership, Company, Notification, STATUSES, CATEGORIES, PRIORITIES

    @login_manager.user_loader
    def load_user(value):
        try:
            user_id, version = value.split(':', 1)
            user = db.session.get(User, int(user_id))
            return user if user and secrets.compare_digest(user.auth_version, version) else None
        except (ValueError, TypeError):
            return None

    @app.before_request
    def load_company():
        g.membership = None
        g.company = None
        if current_user.is_authenticated:
            company_id = session.get('company_id')
            if company_id:
                g.membership = db.session.scalar(db.select(Membership).where(
                    Membership.company_id == company_id, Membership.user_id == current_user.id,
                    Membership.active.is_(True)))
                if g.membership:
                    g.company = g.membership.company
                else:
                    session.pop('company_id', None)

    @app.context_processor
    def common():
        g.membership = g.get('membership')
        g.company = g.get('company')
        links = []
        unread = 0
        if current_user.is_authenticated:
            links = db.session.scalars(db.select(Membership).where(
                Membership.user_id == current_user.id, Membership.active.is_(True)).order_by(Membership.id)).all()
            unread = db.session.scalar(db.select(db.func.count(Notification.id)).where(
                Notification.user_id == current_user.id, Notification.read_at.is_(None)))
        return dict(memberships=links, unread=unread, statuses=STATUSES,
                    categories=CATEGORIES, priorities=PRIORITIES,
                    is_manager=bool(g.membership and g.membership.role in ('owner', 'manager')),
                    role_labels={'owner': 'Responsável', 'manager': 'Gestor', 'provider': 'Prestador', 'resident': 'Colaborador'},
                    base_url=app.config['PUBLIC_BASE_URL'])

    @app.template_filter('datebr')
    def datebr(value):
        if not value:
            return '—'
        if hasattr(value, 'hour'):
            return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(app.config['TIMEZONE'])).strftime('%d/%m/%Y %H:%M')
        return value.strftime('%d/%m/%Y')

    @app.template_filter('local_input')
    def local_input(value):
        return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(app.config['TIMEZONE'])).strftime('%Y-%m-%dT%H:%M')

    @app.after_request
    def headers(response):
        if response.status_code >= 400:
            for path in g.get('new_uploads', []):
                path.unlink(missing_ok=True)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Permissions-Policy'] = 'camera=(self), microphone=()'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'self'; form-action 'self'; base-uri 'self'"
        if current_user.is_authenticated or request.endpoint in ('auth.login', 'auth.reset'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    from .auth import bp as auth_bp
    from .views import bp as main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    from .cli import register_cli
    register_cli(app)
    from .services import ValidationError

    @app.errorhandler(StaleDataError)
    def stale(error):
        db.session.rollback()
        return render_template('error.html', code=409, message='Outra pessoa atualizou este chamado. Recarregue antes de continuar.'), 409

    @app.errorhandler(IntegrityError)
    def conflict(error):
        db.session.rollback()
        return render_template('error.html', code=409, message='Este cadastro já existe ou foi enviado ao mesmo tempo. Consulte a lista antes de repetir.'), 409

    @app.errorhandler(ValidationError)
    def validation(error):
        db.session.rollback()
        return render_template('error.html', code=400, message=str(error)), 400

    for code, message in {400: 'A solicitação expirou ou contém dados inválidos. Recarregue a página e tente novamente.',
                          403: 'Sua conta não tem acesso a esta ação.',
                          404: 'Este item não está disponível para sua conta.',
                          409: 'Este registro foi atualizado. Recarregue antes de continuar.',
                          410: 'Este link expirou ou foi desativado.',
                          413: 'O envio ultrapassa 12 MB. Cada arquivo pode ter até 5 MB.',
                          429: 'Muitas tentativas. Aguarde um minuto antes de tentar novamente.',
                          500: 'Não foi possível concluir a ação. Tente novamente em instantes.'}.items():
        def handler(error, code=code, message=message):
            db.session.rollback()
            if code == 500:
                app.logger.error('Request failed: %s', request.path, exc_info=error)
            return render_template('error.html', code=code, message=message), code
        app.register_error_handler(code, handler)
    return app
