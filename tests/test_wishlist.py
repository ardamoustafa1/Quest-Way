from tests.conftest import register_and_login


def test_add_to_wishlist_requires_login(client):
    resp = client.get('/add_to_wishlist', follow_redirects=False)
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_add_to_wishlist_creates_item(client, db):
    from models import WishlistItem
    register_and_login(client)
    resp = client.post('/add_to_wishlist', data={
        'place_name': 'Pamukkale', 'place_type': 'attraction',
        'country': 'Turkey', 'city': 'Denizli', 'description': 'Want to visit',
    }, follow_redirects=False)
    assert resp.status_code == 302
    with client.application.app_context():
        item = WishlistItem.query.filter_by(place_name='Pamukkale').first()
        assert item is not None


def test_remove_from_wishlist_only_own_item(client, db):
    from models import WishlistItem
    register_and_login(client, username='userA', email='a@example.com')
    client.post('/add_to_wishlist', data={
        'place_name': 'Pamukkale', 'place_type': 'attraction', 'country': 'Turkey',
    })
    with client.application.app_context():
        item_id = WishlistItem.query.filter_by(place_name='Pamukkale').first().id

    client.get('/logout')
    register_and_login(client, username='userB', email='b@example.com')
    # userB, userA'nın wishlist item'ını silmeye çalışıyor — silinmemeli
    client.post(f'/remove_from_wishlist/{item_id}')
    with client.application.app_context():
        assert WishlistItem.query.get(item_id) is not None


def test_quick_add_requires_login(client):
    resp = client.get('/quick-add', follow_redirects=False)
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_quick_add_without_groq_shows_error(client):
    # Test ortamında GROQ_API_KEY yok — bu yüzden nazik bir hata mesajı bekleniyor, 500 değil.
    register_and_login(client)
    resp = client.post('/quick-add', data={'caption': 'Visited the Eiffel Tower'}, follow_redirects=True)
    assert resp.status_code == 200
    assert b'not configured' in resp.data
