from tests.conftest import register_and_login


def add_review(client, **overrides):
    data = {
        'title': 'Great trip', 'content': 'This is a long enough review content for validation purposes.',
        'rating': '5', 'country': 'Turkey', 'city': 'Istanbul',
        'place_name': 'Hagia Sophia', 'place_type': 'famous_places',
    }
    data.update(overrides)
    return client.post('/add_review', data=data, follow_redirects=False)


def test_add_review_requires_login(client):
    resp = client.get('/add_review', follow_redirects=False)
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_add_review_creates_record(client, db):
    from models import Review
    register_and_login(client)
    resp = add_review(client)
    assert resp.status_code == 302
    with client.application.app_context():
        review = Review.query.filter_by(title='Great trip').first()
        assert review is not None
        assert review.rating == 5
        assert review.country == 'Turkey'


def test_add_review_awards_points(client, db):
    from models import User
    register_and_login(client)
    add_review(client)
    with client.application.app_context():
        user = User.query.filter_by(username='testuser').first()
        assert user.points > 0


def test_reviews_page_loads(client):
    resp = client.get('/reviews')
    assert resp.status_code == 200


def test_reviews_page_shows_created_review(client):
    register_and_login(client)
    add_review(client, title='Unique Review Title XYZ')
    resp = client.get('/reviews')
    assert b'Unique Review Title XYZ' in resp.data


def test_helpful_vote_toggle(client, db):
    from models import Review
    register_and_login(client)
    add_review(client)
    with client.application.app_context():
        review = Review.query.filter_by(title='Great trip').first()
        review_id = review.id

    resp1 = client.post(f'/review/{review_id}/helpful')
    assert resp1.get_json()['voted'] is True
    assert resp1.get_json()['count'] == 1

    resp2 = client.post(f'/review/{review_id}/helpful')
    assert resp2.get_json()['voted'] is False
    assert resp2.get_json()['count'] == 0


def test_helpful_vote_requires_login(client, db):
    from models import Review
    register_and_login(client)
    add_review(client)
    with client.application.app_context():
        review_id = Review.query.filter_by(title='Great trip').first().id
    client.get('/logout')
    resp = client.post(f'/review/{review_id}/helpful', follow_redirects=False)
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_search_finds_review_by_keyword(client):
    register_and_login(client)
    add_review(client, title='Searchable Pamukkale review', content='The travertine terraces were amazing to see in person.')
    resp = client.post('/search', data={
        'query': 'Pamukkale', 'country': '', 'place_type': '', 'rating_min': '0',
    })
    assert b'Searchable Pamukkale review' in resp.data


def test_explore_feed_shows_only_reviews_with_photos(client, db):
    from models import Review
    register_and_login(client)
    add_review(client, title='No photo review')
    resp = client.get('/explore')
    assert resp.status_code == 200
    assert b'No photo review' not in resp.data  # fotoğrafsız review Explore'da görünmemeli
