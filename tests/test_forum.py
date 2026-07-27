from tests.conftest import register_and_login, register_user, login_user


def test_forum_index_loads(client):
    resp = client.get('/forum')
    assert resp.status_code == 200


def test_create_thread_requires_login(client):
    resp = client.get('/forum/new', follow_redirects=False)
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_create_thread_and_reply(client, db):
    from models import ForumThread, ForumPost
    register_and_login(client, username='userA', email='a@example.com')
    resp = client.post('/forum/new', data={
        'title': 'Best time to visit Cappadocia?', 'country': 'Turkey',
        'content': 'Planning a trip in spring, any tips?',
    }, follow_redirects=False)
    assert resp.status_code == 302
    thread_id = int(resp.headers['Location'].rsplit('/', 1)[-1])

    with client.application.app_context():
        thread = ForumThread.query.get(thread_id)
        assert thread is not None
        assert ForumPost.query.filter_by(thread_id=thread_id).count() == 1

    client.get('/logout')
    register_user(client, username='userB', email='b@example.com')
    login_user(client, username='userB', password='TestPass123')
    client.post(f'/forum/{thread_id}', data={'content': 'April is great!'})

    with client.application.app_context():
        assert ForumPost.query.filter_by(thread_id=thread_id).count() == 2

    resp = client.get(f'/forum/{thread_id}')
    assert b'April is great!' in resp.data


def test_reply_requires_login(client, db):
    from models import ForumThread
    register_and_login(client)
    resp = client.post('/forum/new', data={
        'title': 'Test thread', 'country': '', 'content': 'Test content',
    }, follow_redirects=False)
    thread_id = int(resp.headers['Location'].rsplit('/', 1)[-1])
    client.get('/logout')

    resp = client.post(f'/forum/{thread_id}', data={'content': 'anonymous reply'}, follow_redirects=False)
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
