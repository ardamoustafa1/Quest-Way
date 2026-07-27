from tests.conftest import register_and_login, register_user, login_user


def create_itinerary(client, **overrides):
    data = {'title': 'My Trip', 'country': 'Turkey', 'city': 'Istanbul'}
    data.update(overrides)
    return client.post('/create_itinerary', data=data, follow_redirects=False)


def get_itinerary_id(resp):
    # Location header formatı: /itinerary/<id>
    return int(resp.headers['Location'].rsplit('/', 1)[-1])


def test_create_itinerary_requires_login(client):
    resp = client.get('/create_itinerary', follow_redirects=False)
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_create_itinerary_success(client, db):
    from models import Itinerary
    register_and_login(client)
    resp = create_itinerary(client)
    assert resp.status_code == 302
    with client.application.app_context():
        assert Itinerary.query.filter_by(title='My Trip').first() is not None


def test_non_owner_cannot_view_private_itinerary(client):
    register_and_login(client, username='owner', email='owner@example.com')
    resp = create_itinerary(client)
    itinerary_id = get_itinerary_id(resp)

    client.get('/logout')
    register_and_login(client, username='stranger', email='stranger@example.com')
    resp = client.get(f'/itinerary/{itinerary_id}', follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/itineraries'


def test_public_itinerary_viewable_by_anyone(client):
    register_and_login(client, username='owner', email='owner@example.com')
    resp = create_itinerary(client, is_public='y')
    itinerary_id = get_itinerary_id(resp)

    client.get('/logout')
    register_and_login(client, username='stranger', email='stranger@example.com')
    resp = client.get(f'/itinerary/{itinerary_id}')
    assert resp.status_code == 200


def test_collaborator_permission_flow(client, db):
    from models import ItineraryCollaborator
    # collab'ı ÖNCE, herhangi biri login olmadan kaydediyoruz — register() zaten
    # login olmuş bir client ile çağrılırsa current_user.is_authenticated kontrolü
    # yeni kaydı hiç yapmadan '/' e yönlendirir.
    register_user(client, username='collab', email='collab@example.com')

    register_and_login(client, username='owner', email='owner@example.com')
    resp = create_itinerary(client)
    itinerary_id = get_itinerary_id(resp)

    # Owner collab'ı davet ediyor
    client.post(f'/itinerary/{itinerary_id}/share', data={'username': 'collab', 'permission': 'edit'})
    with client.application.app_context():
        collab = ItineraryCollaborator.query.filter_by(itinerary_id=itinerary_id).first()
        assert collab is not None
        assert collab.permission == 'edit'

    client.get('/logout')
    login_user(client, username='collab', password='TestPass123')

    # Artık görüntüleyebilmeli (davetten önce göremezdi)
    resp = client.get(f'/itinerary/{itinerary_id}')
    assert resp.status_code == 200

    # Edit izniyle aktivite ekleyebilmeli
    resp = client.post(f'/itinerary/{itinerary_id}/items', data={
        'day_number': '1', 'time_slot': 'morning', 'place_name': 'Blue Mosque',
        'place_type': 'attraction', 'description': 'Morning visit',
    }, follow_redirects=False)
    assert resp.status_code == 302

    from models import ItineraryItem
    with client.application.app_context():
        assert ItineraryItem.query.filter_by(place_name='Blue Mosque').first() is not None


def test_expense_split_math(client, db):
    from models import Itinerary
    register_user(client, username='userB', email='userB@example.com')

    register_and_login(client, username='ownerA', email='ownerA@example.com')
    resp = create_itinerary(client)
    itinerary_id = get_itinerary_id(resp)
    client.post(f'/itinerary/{itinerary_id}/share', data={'username': 'userB', 'permission': 'edit'})

    client.post(f'/itinerary/{itinerary_id}/expenses', data={
        'description': 'Hotel', 'amount': '100', 'currency': 'USD',
    })

    client.get('/logout')
    login_user(client, username='userB', password='TestPass123')
    client.post(f'/itinerary/{itinerary_id}/expenses', data={
        'description': 'Taxi', 'amount': '40', 'currency': 'USD',
    })

    resp = client.get(f'/itinerary/{itinerary_id}')
    # Toplam 140, 2 kişi -> pay 70. userB 40 ödedi, 30 borçlu.
    assert b'owes' in resp.data
    assert b'30.00' in resp.data


def test_poll_vote_switch(client, db):
    from models import ItineraryPoll
    register_and_login(client)
    resp = create_itinerary(client)
    itinerary_id = get_itinerary_id(resp)

    client.post(f'/itinerary/{itinerary_id}/polls', data={
        'question': 'Which hotel?', 'options': ['Hilton', 'Hyatt'],
    })
    with client.application.app_context():
        poll = ItineraryPoll.query.filter_by(itinerary_id=itinerary_id).first()
        option_ids = [o.id for o in poll.options]

    client.post(f'/polls/{poll.id}/vote', data={'option_id': option_ids[0]})
    from models import ItineraryPollVote
    with client.application.app_context():
        assert ItineraryPollVote.query.count() == 1

    # Oy değiştirme: aynı kullanıcı diğer seçeneğe oy verirse eski oy silinmeli
    client.post(f'/polls/{poll.id}/vote', data={'option_id': option_ids[1]})
    with client.application.app_context():
        votes = ItineraryPollVote.query.all()
        assert len(votes) == 1
        assert votes[0].option_id == option_ids[1]


def test_eco_score_requires_items(client):
    register_and_login(client)
    resp = create_itinerary(client)
    itinerary_id = get_itinerary_id(resp)
    resp = client.post(f'/itinerary/{itinerary_id}/eco-score', follow_redirects=True)
    assert b'Add some activities' in resp.data
