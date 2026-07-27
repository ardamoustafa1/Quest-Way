from tests.conftest import register_user, login_user, register_and_login


def test_register_creates_user(client, db):
    from models import User
    resp = register_user(client)
    assert resp.status_code == 302
    with client.application.app_context():
        user = User.query.filter_by(username='testuser').first()
        assert user is not None
        assert user.email == 'test@example.com'
        assert user.email_verified is False
        assert user.referral_code  # otomatik üretilmiş olmalı


def test_register_duplicate_username_rejected(client):
    register_user(client, email='first@example.com')
    resp = register_user(client, email='second@example.com')
    assert b'Username already exists' in resp.data


def test_password_is_hashed_not_plaintext(client, db):
    from models import User
    register_user(client)
    with client.application.app_context():
        user = User.query.filter_by(username='testuser').first()
        assert user.password_hash != 'TestPass123'
        assert user.check_password('TestPass123') is True
        assert user.check_password('WrongPassword') is False


def test_login_success_redirects_home(client):
    register_user(client)
    resp = login_user(client)
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/'


def test_login_wrong_password_rejected(client):
    register_user(client)
    resp = login_user(client, password='WrongPassword')
    assert b'Invalid username or password' in resp.data


def test_login_nonexistent_user_rejected(client):
    resp = login_user(client, username='ghost')
    assert b'Invalid username or password' in resp.data


def test_logout_requires_login(client):
    resp = client.get('/logout', follow_redirects=False)
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_logout_after_login(client):
    register_and_login(client)
    resp = client.get('/logout', follow_redirects=False)
    assert resp.status_code == 302
    # Logout sonrası korumalı bir sayfa tekrar login'e yönlendirmeli
    resp2 = client.get('/profile', follow_redirects=False)
    assert '/login' in resp2.headers['Location']


def test_banned_user_cannot_login(client, db):
    from models import User
    register_user(client)
    with client.application.app_context():
        user = User.query.filter_by(username='testuser').first()
        user.is_active = False
        db.session.commit()
    resp = login_user(client)
    assert b'suspended' in resp.data


def test_email_verification_token_flow(client, db):
    from models import User
    from app import token_serializer
    register_user(client)
    with client.application.app_context():
        user = User.query.filter_by(username='testuser').first()
        assert user.email_verified is False
        token = token_serializer.dumps(user.email, salt='email-verify')

    resp = client.get(f'/verify-email/{token}', follow_redirects=False)
    assert resp.status_code == 302

    with client.application.app_context():
        user = User.query.filter_by(username='testuser').first()
        assert user.email_verified is True


def test_email_verification_bad_token_rejected(client):
    resp = client.get('/verify-email/not-a-real-token', follow_redirects=False)
    assert resp.status_code == 302


def test_forgot_password_does_not_leak_account_existence(client):
    register_user(client)
    resp_existing = client.post('/forgot-password', data={'email': 'test@example.com'}, follow_redirects=True)
    resp_missing = client.post('/forgot-password', data={'email': 'nobody@example.com'}, follow_redirects=True)
    # Her iki durumda da aynı jenerik mesaj dönmeli — hesabın var olup olmadığı sızdırılmamalı
    assert b'password reset link has been sent' in resp_existing.data
    assert b'password reset link has been sent' in resp_missing.data


def test_reset_password_changes_password(client, db):
    from models import User
    from app import token_serializer
    register_user(client)
    with client.application.app_context():
        token = token_serializer.dumps('test@example.com', salt='password-reset')

    resp = client.post(f'/reset-password/{token}', data={
        'password': 'NewPass456', 'password2': 'NewPass456',
    }, follow_redirects=False)
    assert resp.status_code == 302

    # Eski şifre artık çalışmamalı, yeni şifre çalışmalı
    login_old = login_user(client, password='TestPass123')
    assert b'Invalid username or password' in login_old.data
    login_new = login_user(client, password='NewPass456')
    assert login_new.status_code == 302
