from tests.conftest import register_user, login_user, register_and_login


def test_robots_txt(client):
    resp = client.get('/robots.txt')
    assert resp.status_code == 200
    assert b'Disallow: /admin' in resp.data
    assert b'Sitemap:' in resp.data


def test_sitemap_xml_contains_static_pages(client):
    resp = client.get('/sitemap.xml')
    assert resp.status_code == 200
    assert b'<urlset' in resp.data
    assert b'/details/Turkey/famous_places' in resp.data


def test_security_headers_present(client):
    resp = client.get('/')
    assert resp.headers.get('X-Frame-Options') == 'SAMEORIGIN'
    assert resp.headers.get('X-Content-Type-Options') == 'nosniff'
    assert 'Content-Security-Policy' in resp.headers


def test_referral_signup_awards_points_to_both(client, db):
    from models import User
    register_user(client, username='referrer', email='referrer@example.com')
    with client.application.app_context():
        ref_code = User.query.filter_by(username='referrer').first().referral_code

    client.post(f'/register?ref={ref_code}', data={
        'ref': ref_code, 'username': 'referred', 'email': 'referred@example.com',
        'first_name': 'Ref', 'last_name': 'Erred', 'password': 'TestPass123', 'password2': 'TestPass123',
    })

    with client.application.app_context():
        referrer = User.query.filter_by(username='referrer').first()
        referred = User.query.filter_by(username='referred').first()
        assert referrer.points == 50
        assert referred.points == 20
        assert referred.referred_by_user_id == referrer.id


def test_badge_earned_after_first_review(client, db):
    register_and_login(client)
    resp = client.get('/profile')
    assert b'locked' in resp.data  # henüz hiçbir rozet kazanılmamış

    client.post('/add_review', data={
        'title': 'First review', 'content': 'This is my very first review on this platform, quite exciting.',
        'rating': '5', 'country': 'Turkey', 'city': 'Istanbul',
        'place_name': 'Hagia Sophia', 'place_type': 'famous_places',
    })

    resp = client.get('/profile')
    assert b'Wrote your first review' in resp.data


def test_profile_shows_traveler_level(client):
    register_and_login(client)
    resp = client.get('/profile')
    assert b'Wanderer' in resp.data  # 0 puan -> ilk seviye
