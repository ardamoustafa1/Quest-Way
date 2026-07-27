from flask import Blueprint, render_template, request, url_for, redirect, flash
from flask_login import login_user, logout_user, login_required, current_user
from itsdangerous import SignatureExpired, BadSignature
from models import db, User, Review, WishlistItem, Itinerary
from forms import LoginForm, RegisterForm, ForgotPasswordForm, ResetPasswordForm
from app import (
    limiter, promote_admin_if_configured, token_serializer, send_verification_email,
    generate_referral_code, compute_user_badges, get_user_level_info, send_email,
    REFERRAL_BONUS_NEW_USER, REFERRAL_BONUS_REFERRER,
)

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("15/hour", methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            if not user.is_active:
                flash('This account has been suspended. Contact support if you believe this is a mistake.', 'error')
                return render_template('auth/login.html', form=form)
            promote_admin_if_configured(user)
            login_user(user, remember=form.remember_me.data)
            flash('Login successful!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('main.index'))
        flash('Invalid username or password', 'error')
    
    return render_template('auth/login.html', form=form)

@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("10/hour", methods=['POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = RegisterForm()
    ref_code = request.values.get('ref', '').strip()

    if form.validate_on_submit():
        # Check if username already exists
        existing_user = User.query.filter_by(username=form.username.data).first()
        if existing_user:
            flash('Username already exists. Please choose a different username.', 'error')
            return render_template('auth/register.html', form=form, ref_code=ref_code)

        # Check if email already exists
        existing_email = User.query.filter_by(email=form.email.data).first()
        if existing_email:
            flash('Email already registered. Please use a different email.', 'error')
            return render_template('auth/register.html', form=form, ref_code=ref_code)

        try:
            referrer = User.query.filter_by(referral_code=ref_code).first() if ref_code else None

            user = User(
                username=form.username.data,
                email=form.email.data,
                first_name=form.first_name.data,
                last_name=form.last_name.data,
                referral_code=generate_referral_code(),
                referred_by_user_id=referrer.id if referrer else None,
                points=REFERRAL_BONUS_NEW_USER if referrer else 0,
            )
            user.set_password(form.password.data)
            db.session.add(user)
            if referrer:
                referrer.points = (referrer.points or 0) + REFERRAL_BONUS_REFERRER
            db.session.commit()
            send_verification_email(user)
            if referrer:
                flash(f'Registration successful! You joined via {referrer.username}\'s invite and got {REFERRAL_BONUS_NEW_USER} bonus points. We sent you a verification link — please check your email, then log in.', 'success')
            else:
                flash('Registration successful! We sent you a verification link — please check your email, then log in.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()
            flash('An error occurred during registration. Please try again.', 'error')
            return render_template('auth/register.html', form=form, ref_code=ref_code)

    return render_template('auth/register.html', form=form, ref_code=ref_code)

@auth_bp.route('/verify-email/<token>')
def verify_email(token):
    try:
        email = token_serializer.loads(token, salt='email-verify', max_age=3600)
    except SignatureExpired:
        flash('That verification link has expired. Please request a new one from your profile.', 'error')
        return redirect(url_for('auth.login'))
    except BadSignature:
        flash('That verification link is invalid.', 'error')
        return redirect(url_for('auth.login'))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash('Account not found.', 'error')
        return redirect(url_for('auth.login'))

    user.email_verified = True
    db.session.commit()
    flash('Email verified! Thanks for confirming your account.', 'success')
    return redirect(url_for('auth.login'))

@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("5/hour", methods=['POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            token = token_serializer.dumps(user.email, salt='password-reset')
            link = url_for('auth.reset_password', token=token, _external=True)
            send_email(
                user.email,
                'Reset your QuestWay password',
                f"Hi {user.first_name or user.username},\n\nClick this link to reset your password (valid for 1 hour):\n{link}\n\nIf you didn't request this, you can safely ignore this email.",
            )
        # Kullanıcı var mı yok mu bilgisini sızdırmamak için mesaj her durumda aynı
        flash('If that email is registered, a password reset link has been sent.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/forgot_password.html', form=form)

@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))

    try:
        email = token_serializer.loads(token, salt='password-reset', max_age=3600)
    except SignatureExpired:
        flash('That reset link has expired. Please request a new one.', 'error')
        return redirect(url_for('auth.forgot_password'))
    except BadSignature:
        flash('That reset link is invalid.', 'error')
        return redirect(url_for('auth.forgot_password'))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash('Account not found.', 'error')
        return redirect(url_for('auth.forgot_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash('Your password has been reset. Please log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/reset_password.html', form=form)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.index'))

@auth_bp.route('/profile')
@login_required
def profile():
    user_reviews = Review.query.filter_by(user_id=current_user.id).order_by(Review.created_at.desc()).limit(5).all()
    user_wishlist = WishlistItem.query.filter_by(user_id=current_user.id).order_by(WishlistItem.added_at.desc()).limit(5).all()
    user_itineraries = Itinerary.query.filter_by(user_id=current_user.id).order_by(Itinerary.created_at.desc()).limit(5).all()
    earned_badges, locked_badges = compute_user_badges(current_user)
    level_info = get_user_level_info(current_user.points)

    return render_template('user/profile.html',
                         reviews=user_reviews,
                         wishlist=user_wishlist,
                         itineraries=user_itineraries,
                         earned_badges=earned_badges,
                         locked_badges=locked_badges,
                         level_info=level_info)

@auth_bp.route('/resend-verification', methods=['POST'])
@login_required
def resend_verification():
    if current_user.email_verified:
        flash('Your email is already verified.', 'info')
    else:
        send_verification_email(current_user)
        flash('Verification email sent — please check your inbox.', 'success')
    return redirect(url_for('auth.profile'))
