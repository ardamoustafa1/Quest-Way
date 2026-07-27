import os
from tests.conftest import register_and_login, register_user, login_user


def test_admin_dashboard_blocks_non_admin(client):
    register_and_login(client)
    resp = client.get('/admin', follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/'


def test_admin_dashboard_blocks_anonymous(client):
    resp = client.get('/admin', follow_redirects=False)
    assert resp.status_code == 302


def test_admin_auto_promotion_via_admin_emails(client, db, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, 'ADMIN_EMAILS', {'admin@example.com'})

    register_user(client, username='promoted', email='admin@example.com')
    login_user(client, username='promoted', password='TestPass123')

    from models import User
    with client.application.app_context():
        user = User.query.filter_by(username='promoted').first()
        assert user.is_admin is True

    resp = client.get('/admin')
    assert resp.status_code == 200


def test_admin_can_delete_review(client, db, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, 'ADMIN_EMAILS', {'admin@example.com'})

    # Normal kullanıcı review yazıyor
    register_and_login(client, username='author', email='author@example.com')
    client.post('/add_review', data={
        'title': 'To be deleted', 'content': 'This review will be removed by an admin during the test.',
        'rating': '3', 'country': 'Turkey', 'city': 'Ankara',
        'place_name': 'Anitkabir', 'place_type': 'famous_places',
    })
    client.get('/logout')

    from models import Review
    with client.application.app_context():
        review_id = Review.query.filter_by(title='To be deleted').first().id

    register_user(client, username='admin', email='admin@example.com')
    login_user(client, username='admin', password='TestPass123')

    resp = client.post(f'/admin/reviews/{review_id}/delete', follow_redirects=False)
    assert resp.status_code == 302
    with client.application.app_context():
        assert Review.query.get(review_id) is None


def test_admin_can_ban_user(client, db, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, 'ADMIN_EMAILS', {'admin@example.com'})

    register_user(client, username='tobebanned', email='banned@example.com')

    from models import User
    with client.application.app_context():
        target_id = User.query.filter_by(username='tobebanned').first().id

    register_user(client, username='admin', email='admin@example.com')
    login_user(client, username='admin', password='TestPass123')
    client.post(f'/admin/users/{target_id}/toggle-active')

    with client.application.app_context():
        assert User.query.get(target_id).is_active is False

    client.get('/logout')
    resp = login_user(client, username='tobebanned', password='TestPass123')
    assert b'suspended' in resp.data
