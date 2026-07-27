"""Test ortamı kurulumu.

Gerçek Supabase DB'ye dokunmamak için app.py import edilmeden ÖNCE env
değişkenleri geçici bir SQLite dosyasına ve test-güvenli değerlere
yönlendiriliyor. GROQ/Sentry/Redis/Supabase Storage gibi dış servisler
bilinçli olarak devre dışı bırakılıyor — böylece testler ağ bağlantısı
olmadan, hızlı ve deterministik çalışır; her ilgili route'un "yapılandırılmamış"
durumdaki zarif davranışı test edilir (gerçek API çağrıları değil).
"""
import os
import sys
import tempfile

# ÖNEMLİ: bu dosya hem pytest'in kendi conftest mekanizmasıyla hem de test
# dosyalarındaki `from tests.conftest import ...` ile AYRI birer modül olarak
# iki kez import edilebiliyor (tests/ paketinde __init__.py yok, namespace
# package). Aşağıdaki ortam/DB kurulumu yan etkili olduğu için (özellikle
# dosya silme) bir kez daha çalışırsa canlı SQLite dosyasını test ortasında
# silip "no such table" hatalarına yol açıyordu — bu yüzden idempotent hale
# getirildi (bir kez kurulur, sonraki importlarda atlanır).
if not os.environ.get('_QW_TEST_ENV_READY'):
    _TEST_DB_PATH = os.path.join(tempfile.gettempdir(), 'questway_test.db')
    if os.path.exists(_TEST_DB_PATH):
        os.remove(_TEST_DB_PATH)

    os.environ['DATABASE_URL'] = f'sqlite:///{_TEST_DB_PATH}'
    os.environ['SECRET_KEY'] = 'test-secret-key-not-for-production'
    # Boş string'e set ediyoruz, silmiyoruz: app.py kendi load_dotenv() çağrısında
    # .env dosyasını okuyor ve python-dotenv, os.environ'da zaten bir anahtar
    # varsa (boş string dahil) onu EZMİYOR — pop() ile tamamen silseydik,
    # load_dotenv() .env'deki gerçek GROQ_API_KEY'i yeniden içeri sızdırıyordu
    # (ki bu da AI route'larının 'yapılandırılmamış' davranışını test edemememize
    # yol açıyordu, çünkü groq_client sessizce gerçek client oluyordu).
    for var in ('GROQ_API_KEY', 'MAIL_USERNAME', 'MAIL_PASSWORD', 'RENDER', 'VERCEL',
                'SENTRY_DSN', 'REDIS_URL', 'SUPABASE_URL', 'SUPABASE_SERVICE_KEY',
                'CRON_SECRET', 'ADMIN_EMAILS'):
        os.environ[var] = ''
    os.environ['_QW_TEST_ENV_READY'] = '1'

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app import app as flask_app, db as _db, limiter as _limiter

flask_app.config.update(
    TESTING=True,
    WTF_CSRF_ENABLED=False,
    RATELIMIT_ENABLED=False,
    SERVER_NAME='localhost.test',
)
# app.config['RATELIMIT_ENABLED'] yukarıda set edilse de etkisiz kalıyor —
# Flask-Limiter `self.enabled`'ı app.py import edilirken (Limiter(app=app,...)
# çağrıldığı anda) config'ten OKUYUP SABİTLİYOR; bizim buradaki config.update()
# çağrımız o noktadan SONRA geliyor, geriye dönük etkisi yok. Bu yüzden testler
# çoklu dosyada birikince (örn. birçok register/login POST'u) gerçek rate
# limit'e takılıp bazı kayıtları sessizce 429'a düşürüyordu. Doğrudan limiter
# nesnesinin `.enabled` attribute'unu kapatmak gerçek çözüm.
_limiter.enabled = False


@pytest.fixture(scope='session', autouse=True)
def _create_schema():
    """Şemayı bir kez kur.

    ÖNEMLİ: app_context'i `yield` boyunca AÇIK tutmuyoruz. Açık tutulsaydı
    (önceki hatalı versiyon), Werkzeug test client'ın her isteği kendi app
    context'ini push etmek yerine bu session-scoped context'i yeniden
    kullanıyordu (Flask, aynı app için zaten aktif bir context varsa yenisini
    push etmiyor) — bu da Flask-Login'in kullanıcıyı cache'lediği `g` objesinin
    TÜM test session'ı boyunca aynı kalmasına, yani bir testte login olan
    kullanıcının sonraki tüm testlere sızmasına yol açıyordu.
    """
    with flask_app.app_context():
        _db.create_all()
    yield
    with flask_app.app_context():
        _db.drop_all()


@pytest.fixture(autouse=True)
def _clean_tables():
    """Her test tertemiz bir DB ile başlasın diye testten sonra tüm tabloları boşalt.

    Testin kendisi session'ı 'poisoned' (rollback bekleyen) bir duruma
    bırakmış olabilir — önce rollback() ile temizlemeden delete denemek,
    o session'ı kullanan TÜM sonraki testleri de kırıyordu.

    Ayrıca `table.delete()` ORM'i bypass eden bir bulk/Core işlemi olduğu
    için session'ın identity map'i (önceki testten kalma Python nesneleri)
    otomatik geçersizleşmiyor — `session.remove()` olmadan bir sonraki test
    aynı satırların ESKİ, artık DB'de var olmayan halini cache'ten
    görebiliyordu (ör. 'testuser' aslında silinmiş olsa da hâlâ bulunuyordu).
    """
    yield
    with flask_app.app_context():
        _db.session.rollback()
        for table in reversed(_db.metadata.sorted_tables):
            _db.session.execute(table.delete())
        _db.session.commit()
        _db.session.remove()


@pytest.fixture
def app():
    return flask_app


@pytest.fixture
def client(app):
    # `with` kullanmak önemli: Flask TESTING=True iken request/app context'i
    # "debug için" bir sonraki isteğe kadar canlı tutuyor (context preservation).
    # `with` bloğu olmadan (`app.test_client()` düz döndürülürse) bu context
    # temizlenmeden sonraki teste sızıyor ve current_user önceki testten
    # login olmuş kullanıcı olarak kalıyordu — testler arası login state
    # leakage'ının kök nedeni buydu.
    with app.test_client() as test_client:
        yield test_client


@pytest.fixture
def db(app):
    return _db


def register_user(client, username='testuser', email='test@example.com', password='TestPass123'):
    return client.post('/register', data={
        'username': username, 'email': email, 'first_name': 'Test', 'last_name': 'User',
        'password': password, 'password2': password,
    }, follow_redirects=False)


def login_user(client, username='testuser', password='TestPass123'):
    return client.post('/login', data={'username': username, 'password': password}, follow_redirects=False)


def register_and_login(client, **kwargs):
    register_user(client, **kwargs)
    username = kwargs.get('username', 'testuser')
    password = kwargs.get('password', 'TestPass123')
    return login_user(client, username=username, password=password)
