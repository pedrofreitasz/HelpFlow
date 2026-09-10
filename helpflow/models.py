from datetime import datetime, timezone
import secrets
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from .extensions import db


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def token():
    return secrets.token_urlsafe(24)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    auth_version = db.Column(db.String(64), default=token, nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        self.auth_version = token()
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    def get_id(self):
        return f'{self.id}:{self.auth_version}'


class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(80), unique=True, nullable=False)
    accent = db.Column(db.String(7), default='#236448', nullable=False)
    public_portal = db.Column(db.Boolean, default=True, nullable=False)
    email_alerts = db.Column(db.Boolean, default=True, nullable=False)
    sla_hours = db.Column(db.Integer, default=48, nullable=False)
    plan = db.Column(db.String(30), default='Piloto', nullable=False)
    point_limit = db.Column(db.Integer, default=50, nullable=False)
    logo_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False)


class Membership(db.Model):
    __table_args__ = (db.UniqueConstraint('company_id', 'email'),)
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(254), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    specialty = db.Column(db.String(120), default='', nullable=False)
    phone = db.Column(db.String(40), default='', nullable=False)
    notes = db.Column(db.Text, default='', nullable=False)
    company = db.relationship('Company')
    user = db.relationship('User')


class Location(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('location.id'))
    name = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(30), default='Ambiente', nullable=False)
    reference = db.Column(db.String(200), default='', nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    parent = db.relationship('Location', remote_side=[id])
    company = db.relationship('Company')
    @property
    def label(self):
        return f'{self.parent.name} / {self.name}' if self.parent else self.name
    @property
    def available(self):
        return self.active and (self.parent is None or self.parent.active)


class QRPoint(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False, index=True)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=False)
    code = db.Column(db.String(64), unique=True, default=token, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    location = db.relationship('Location')
    company = db.relationship('Company')


STATUSES = ['Novo', 'Aprovado', 'Atribuído', 'Em andamento', 'Aguardando', 'Em revisão', 'Concluído', 'Cancelado']
CATEGORIES = ['Elétrica', 'Hidráulica', 'Climatização', 'Limpeza', 'Segurança', 'Manutenção geral']
PRIORITIES = ['Baixa', 'Normal', 'Alta', 'Urgente']


class Ticket(db.Model):
    __table_args__ = (db.CheckConstraint('rating IS NULL OR (rating >= 1 AND rating <= 5)', name='rating_range'),)
    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(24), unique=True, nullable=False, default=lambda: 'HF-' + secrets.token_hex(4).upper())
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False, index=True)
    location_id = db.Column(db.Integer, db.ForeignKey('location.id'), nullable=False)
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    provider_id = db.Column(db.Integer, db.ForeignKey('membership.id'), index=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(40), nullable=False)
    priority = db.Column(db.String(20), default='Normal', nullable=False)
    status = db.Column(db.String(30), default='Novo', nullable=False, index=True)
    is_public = db.Column(db.Boolean, default=False, nullable=False)
    due_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    updated_at = db.Column(db.DateTime, default=now, nullable=False)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    rating = db.Column(db.Integer)
    submit_key = db.Column(db.String(64), unique=True, nullable=False, default=token)
    version_id = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {'version_id_col': version_id}
    company = db.relationship('Company')
    location = db.relationship('Location')
    requester = db.relationship('User')
    provider = db.relationship('Membership')
    @property
    def overdue(self):
        return self.status not in ('Concluído', 'Cancelado', 'Em revisão') and self.due_at < now()


class Event(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False, index=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    kind = db.Column(db.String(30), nullable=False)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    actor = db.relationship('User')


class Attachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False, index=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('ticket.id'), index=True)
    membership_id = db.Column(db.Integer, db.ForeignKey('membership.id'))
    uploader_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    storage_name = db.Column(db.String(80), unique=True, nullable=False)
    mime = db.Column(db.String(80), nullable=False)
    kind = db.Column(db.String(20), nullable=False)
    expires_at = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=now, nullable=False)


class Invitation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    membership_id = db.Column(db.Integer, db.ForeignKey('membership.id'), nullable=False)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)
    membership = db.relationship('Membership')


class PasswordReset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)


class Notification(db.Model):
    __table_args__ = (db.UniqueConstraint('dedupe_key'),)
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    email = db.Column(db.String(254), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    path = db.Column(db.String(300), nullable=False, default='/notifications')
    read_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    sent_at = db.Column(db.DateTime)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    send_email = db.Column(db.Boolean, default=True, nullable=False)
    dedupe_key = db.Column(db.String(160))
