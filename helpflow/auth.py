from datetime import timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from flask_login import login_user, logout_user, current_user, login_required
from .extensions import db, limiter
from .models import User, Membership, PasswordReset, Invitation, Notification, token, now
from .services import field, email_field, password_field, ValidationError, digest, safe_next, audit

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit('15 per minute', methods=['POST'])
def login():
    next_url = safe_next(request.values.get('next'))
    if request.method == 'POST':
        email = email_field()
        user = db.session.scalar(db.select(User).where(User.email == email))
        if not user or not user.check_password(request.form.get('password', '')):
            return render_template('auth.html', mode='login', error='E-mail ou senha incorretos.', next_url=next_url), 400
        session.clear()
        login_user(user)
        session.permanent = True
        member = db.session.scalar(db.select(Membership).where(Membership.user_id == user.id, Membership.active.is_(True)).order_by(Membership.id))
        if member:
            session['company_id'] = member.company_id
        return redirect(next_url)
    return render_template('auth.html', mode='login', next_url=next_url)


@bp.route('/register', methods=['GET', 'POST'])
@limiter.limit('8 per hour', methods=['POST'])
def register():
    next_url = safe_next(request.values.get('next'))
    if request.method == 'POST':
        name, email, password = field('name', 2, 100), email_field(), password_field()
        if db.session.scalar(db.select(User).where(User.email == email)):
            raise ValidationError('Este e-mail já está cadastrado. Entre ou recupere sua senha.')
        user = User(name=name, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        session.clear()
        login_user(user)
        session.permanent = True
        flash('Conta criada. Você já pode relatar problemas ou criar uma empresa.', 'success')
        return redirect(next_url)
    return render_template('auth.html', mode='register', next_url=next_url)


@bp.post('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('main.home'))


@bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit('5 per hour', methods=['POST'])
def forgot():
    if request.method == 'POST':
        user = db.session.scalar(db.select(User).where(User.email == email_field()))
        if user:
            raw = token()
            db.session.add(PasswordReset(user_id=user.id, token_hash=digest(raw), expires_at=now() + timedelta(hours=1)))
            db.session.add(Notification(email=user.email, title='Redefina sua senha',
                body='Este link vale por uma hora. Ignore se você não solicitou.', path='/reset-password/' + raw))
            db.session.commit()
        flash('Se o e-mail estiver cadastrado, as instruções serão enviadas.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth.html', mode='forgot', next_url='/workspace')


@bp.route('/reset-password/<raw>', methods=['GET', 'POST'])
@limiter.limit('10 per hour', methods=['POST'])
def reset(raw):
    reset_request = db.session.scalar(db.select(PasswordReset).where(
        PasswordReset.token_hash == digest(raw), PasswordReset.used_at.is_(None), PasswordReset.expires_at > now()))
    if not reset_request:
        abort(410)
    if request.method == 'POST':
        user = db.session.get(User, reset_request.user_id)
        user.set_password(password_field())
        for item in db.session.scalars(db.select(PasswordReset).where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None))):
            item.used_at = now()
        db.session.commit()
        logout_user()
        session.clear()
        flash('Senha alterada. Entre novamente.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth.html', mode='reset', next_url='/workspace')


@bp.route('/invite/<raw>', methods=['GET', 'POST'])
def accept_invite(raw):
    invite = db.session.scalar(db.select(Invitation).where(Invitation.token_hash == digest(raw),
        Invitation.used_at.is_(None), Invitation.expires_at > now()))
    if not invite or not invite.membership.active:
        abort(410)
    member = invite.membership
    if request.method == 'POST':
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login', next=request.path))
        if current_user.email != member.email:
            raise ValidationError(f'Entre com o e-mail convidado: {member.email}.')
        member.user_id = current_user.id
        invite.used_at = now()
        audit(member.company_id, f'{member.name} aceitou o convite de {member.role}.')
        db.session.commit()
        session['company_id'] = member.company_id
        flash('Convite aceito.', 'success')
        return redirect(url_for('main.workspace'))
    return render_template('invite.html', invite=invite, member=member)


@bp.route('/account', methods=['GET', 'POST'])
@login_required
@limiter.limit('10 per hour', methods=['POST'])
def account():
    if request.method == 'POST':
        if request.form.get('action') == 'password':
            if not current_user.check_password(request.form.get('current_password', '')):
                raise ValidationError('A senha atual está incorreta.')
            current_user.set_password(password_field())
            for item in db.session.scalars(db.select(PasswordReset).where(PasswordReset.user_id == current_user.id, PasswordReset.used_at.is_(None))):
                item.used_at = now()
            db.session.commit()
            logout_user()
            session.clear()
            flash('Senha alterada. Entre novamente nos seus dispositivos.', 'success')
            return redirect(url_for('auth.login'))
        elif request.form.get('action') == 'name':
            current_user.name = field('name', 2, 100)
            db.session.commit()
            flash('Nome atualizado.', 'success')
            return redirect(request.path)
        abort(400)
    return render_template('account.html')
