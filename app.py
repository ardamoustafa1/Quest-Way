from flask import Flask, render_template, request, url_for, redirect, flash, session, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, or_
from flask_caching import Cache
from flask_mail import Mail, Message
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_migrate import Migrate
from groq import Groq
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import sys
import json
import requests
from urllib.parse import quote_plus
from dotenv import load_dotenv

# When this file is run directly (`python3 app.py`, used for local dev),
# Python executes it as '__main__', not as a module named 'app'. The
# blueprints in blueprints/*.py do `from app import ...` to reach the shared
# extensions/helpers defined below — under '__main__' that statement would
# try to load and re-execute this whole file a second time under a fresh
# 'app' module identity, which recurses into the same registration line and
# fails with a circular-import error. Aliasing this already-executing module
# under the 'app' key up front means `from app import ...` (from anywhere,
# including this file's own blueprint imports below) always resolves to the
# one instance actually running, regardless of how the process was started.
# No-op when imported normally (e.g. `gunicorn app:app`), since __name__ is
# already 'app' there.
sys.modules.setdefault('app', sys.modules[__name__])

# Load .env for local development (no-op in production where env vars
# are already set by the hosting platform)
load_dotenv()

# Sentry hata izleme — SENTRY_DSN set edilmemişse tamamen no-op'tur (uygulama
# normal şekilde çalışmaya devam eder, sadece hata raporlanmaz). Ücretsiz bir
# Sentry hesabı açıp SENTRY_DSN ortam değişkenini eklediğinde otomatik aktif olur.
SENTRY_DSN = os.environ.get('SENTRY_DSN')
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[FlaskIntegration()],
        traces_sample_rate=0.1,
        environment=os.environ.get('RENDER') and 'render' or os.environ.get('VERCEL') and 'vercel' or 'development',
    )

# For Vercel: disable instance folder (read-only filesystem)
if os.environ.get('VERCEL'):
    app = Flask(__name__, instance_path=None, instance_relative_config=False)
else:
    app = Flask(__name__)

# Database & secret key configuration
# DATABASE_URL (Supabase Postgres connection string) is the single source of
# truth for every environment. Locally it comes from .env; on Render/Vercel
# it must be set as a platform environment variable. Falls back to a local
# SQLite file only when nothing is configured (pure local dev convenience).
secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    import secrets
    secret_key = secrets.token_hex(32)
    print("⚠ WARNING: SECRET_KEY not set, using a generated key (sessions will not survive a restart). Set SECRET_KEY as an environment variable.")
app.config['SECRET_KEY'] = secret_key

database_url = os.environ.get('DATABASE_URL')
if database_url:
    # Normalize legacy 'postgres://' scheme (still returned by some providers)
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
elif os.environ.get('VERCEL'):
    # Vercel's filesystem is read-only/ephemeral: SQLite cannot persist data.
    print("⚠ WARNING: DATABASE_URL not set on Vercel. Using in-memory SQLite — no data will persist between requests.")
    database_url = 'sqlite:///:memory:'
else:
    database_url = 'sqlite:///travel_guide.db'

app.config['SQLALCHEMY_DATABASE_URI'] = database_url

if os.environ.get('VERCEL'):
    # Disable instance_path creation for Vercel (read-only filesystem)
    app.config['INSTANCE_PATH'] = '/tmp'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 12 * 1024 * 1024  # 12MB toplam istek boyutu (3 foto x 3MB + form verisi payı)

# Cache konfigürasyonu — REDIS_URL set edilmişse Redis'e, değilse in-process
# memory cache'e düşer. Redis olmadan da çalışır ama tek worker/instance'ta
# geçerlidir; birden fazla worker'da (gerçek prod trafiğinde) her worker'ın
# kendi cache'i olur, bu yüzden Redis eklendiğinde otomatik ona geçilecek şekilde kuruldu.
REDIS_URL = os.environ.get('REDIS_URL')
if REDIS_URL:
    app.config['CACHE_TYPE'] = 'RedisCache'
    app.config['CACHE_REDIS_URL'] = REDIS_URL
else:
    app.config['CACHE_TYPE'] = 'SimpleCache'
app.config['CACHE_DEFAULT_TIMEOUT'] = 300  # 5 dakika
cache = Cache(app)

# E-posta konfigürasyonu (doğrulama + şifre sıfırlama).
# MAIL_USERNAME/MAIL_PASSWORD ortam değişkenleri set edilmemişse mail_configured
# False olur ve send_email() gerçek gönderim yerine konsola loglar (dev fallback) —
# uygulama SMTP olmadan da çökmeden çalışmaya devam eder.
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER', app.config['MAIL_USERNAME'])
mail_configured = bool(app.config['MAIL_USERNAME'] and app.config['MAIL_PASSWORD'])
mail = Mail(app)

def rate_limit_key():
    """Giriş yapmış kullanıcı için user_id, değilse IP — paylaşılan ofis/NAT arkasındaki
    kullanıcıların birbirini limitlememesi için login sonrası user_id'ye geçiliyor."""
    if current_user.is_authenticated:
        return f"user:{current_user.id}"
    return get_remote_address()

limiter = Limiter(key_func=rate_limit_key, app=app, storage_uri=(REDIS_URL or "memory://"), default_limits=[])

@app.errorhandler(429)
def handle_rate_limit(e):
    if request.path.startswith('/api/'):
        return jsonify({'error': 'Too many requests — please slow down and try again shortly.'}), 429
    flash('You are doing that too often — please wait a bit and try again.', 'error')
    return redirect(request.referrer or url_for('main.index'))

# Security header'ları (Flask-Talisman). script-src artık 'unsafe-inline' YERİNE
# per-request nonce kullanıyor: her <script> bloğu template'te nonce="{{ csp_nonce() }}"
# taşıyor (bkz. templates/), ve tüm eski onclick=/onsubmit= gibi inline event handler'lar
# addEventListener'a taşındı (nonce'lar sadece <script> bloklarını kapsar, inline
# attribute handler'ları kapsamaz). Bu, XSS ile enjekte edilen script'lerin artık
# tarayıcı tarafından gerçekten engellendiği anlamına geliyor. style-src'de
# 'unsafe-inline' bilinçli olarak bırakıldı — düzinelerce template'te inline
# style="" kullanılıyor ve CSS-only XSS riski script'e göre çok daha düşük.
# HTTPS zorlaması sadece gerçek production'da (Render/Vercel) açık, local http
# geliştirmeyi bozmuyor.
IS_PRODUCTION = bool(os.environ.get('RENDER') or os.environ.get('VERCEL'))
Talisman(
    app,
    force_https=IS_PRODUCTION,
    strict_transport_security=IS_PRODUCTION,
    session_cookie_secure=IS_PRODUCTION,
    content_security_policy={
        'default-src': "'self'",
        'script-src': ["'self'", 'https://cdnjs.cloudflare.com', 'https://unpkg.com',
                        'https://pagead2.googlesyndication.com', 'https://www.googletagmanager.com'],
        'style-src': ["'self'", "'unsafe-inline'", 'https://fonts.googleapis.com', 'https://cdnjs.cloudflare.com',
                       'https://unpkg.com'],
        'font-src': ["'self'", 'https://fonts.gstatic.com', 'https://cdnjs.cloudflare.com'],
        'img-src': ["'self'", 'data:', 'https:'],
        'connect-src': ["'self'", 'https:'],
    },
    content_security_policy_nonce_in=['script-src'],
)

# Groq (Llama) — AI itinerary generator + chat asistanı
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')
GROQ_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')
groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# Supabase Storage (review fotoğrafları). SUPABASE_URL + SUPABASE_SERVICE_KEY
# set edilmemişse supabase_client None kalır ve encode_review_images() otomatik
# olarak eski base64-in-DB davranışına düşer — hiçbir şey kırılmaz.
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')
SUPABASE_STORAGE_BUCKET = os.environ.get('SUPABASE_STORAGE_BUCKET', 'review-photos')
supabase_client = None
if SUPABASE_URL and SUPABASE_SERVICE_KEY:
    from supabase import create_client
    supabase_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    try:
        existing_buckets = {b.name for b in supabase_client.storage.list_buckets()}
        if SUPABASE_STORAGE_BUCKET not in existing_buckets:
            supabase_client.storage.create_bucket(SUPABASE_STORAGE_BUCKET, options={'public': True})
    except Exception as e:
        print(f"Supabase Storage bucket check/create failed: {e}")

# Zamanlanmış hatırlatma e-postaları için gizli anahtar. Flask'ın kendi
# scheduler'ı yok, bu yüzden /internal/send-trip-reminders dışarıdan
# (Render Cron Job, GitHub Actions cron, cron-job.org vb.) günde bir kez
# tetiklenmesi gereken bir endpoint. CRON_SECRET set edilmemişse endpoint
# kapalı kalır (güvenlik varsayılanı: açık değil).
CRON_SECRET = os.environ.get('CRON_SECRET')

# Admin/moderasyon. ADMIN_EMAILS ortam değişkeninde (virgülle ayrılmış) listelenen
# e-postalarla giriş yapan hesaplar otomatik olarak is_admin=True olur — DB'ye elle
# müdahale etmeye gerek kalmadan, sadece Vercel/Render env var'ı ekleyerek kendini
# admin yapabilirsin.
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get('ADMIN_EMAILS', '').split(',') if e.strip()}


def promote_admin_if_configured(user):
    if user.email and user.email.lower() in ADMIN_EMAILS and not user.is_admin:
        user.is_admin = True
        db.session.commit()


def admin_required(view_func):
    from functools import wraps

    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required.', 'error')
            return redirect(url_for('main.index'))
        return view_func(*args, **kwargs)
    return wrapped

# Booking/affiliate linkleri. AFFILIATE_ID env var'ları set edilmeden de linkler
# tamamen çalışır (kullanıcıyı doğru arama sonucuna götürür) — sadece henüz
# komisyon kazanılmaz. Gerçek bir Booking.com/Viator partner hesabı açıp
# BOOKING_AFFILIATE_ID / VIATOR_AFFILIATE_ID env var'larını eklediğinde,
# kod değişikliği gerekmeden otomatik olarak affiliate linklerine döner.
BOOKING_AFFILIATE_ID = os.environ.get('BOOKING_AFFILIATE_ID', '')
VIATOR_AFFILIATE_ID = os.environ.get('VIATOR_AFFILIATE_ID', '')


def booking_url(place_name, city='', country=''):
    query = quote_plus(f"{place_name} {city or country}".strip())
    url = f"https://www.booking.com/searchresults.html?ss={query}"
    if BOOKING_AFFILIATE_ID:
        url += f"&aid={BOOKING_AFFILIATE_ID}"
    return url


def viator_url(place_name, city='', country=''):
    query = quote_plus(f"{place_name} {city or country}".strip())
    url = f"https://www.viator.com/searchResults/all?text={query}"
    if VIATOR_AFFILIATE_ID:
        url += f"&pid={VIATOR_AFFILIATE_ID}"
    return url

REFERRAL_BONUS_REFERRER = 50
REFERRAL_BONUS_NEW_USER = 20

@app.context_processor
def inject_booking_helpers():
    return dict(booking_url=booking_url, viator_url=viator_url,
                REFERRAL_BONUS_REFERRER=REFERRAL_BONUS_REFERRER,
                REFERRAL_BONUS_NEW_USER=REFERRAL_BONUS_NEW_USER)

# Import models first to get db instance
from models import db, User, Review, ReviewHelpfulVote, WishlistItem, Itinerary, ItineraryItem, ItineraryCollaborator, ItineraryExpense, ItineraryPoll, ItineraryPollOption, ItineraryPollVote, ForumThread, ForumPost, WeatherData, CurrencyRate
from forms import LoginForm, RegisterForm, ForgotPasswordForm, ResetPasswordForm, ReviewForm, WishlistForm, ItineraryForm, ItineraryItemForm, ItineraryExpenseForm, AIItineraryForm, ForumThreadForm, ForumReplyForm, SearchForm, ContactForm

# Initialize extensions
login_manager = LoginManager()

# Initialize extensions with app
db.init_app(app)
migrate = Migrate(app, db)
login_manager.init_app(app)
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access this page.'

token_serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])


def send_email(to, subject, body):
    """SMTP yapılandırılmışsa gerçek e-posta gönder, değilse konsola logla.

    SMTP credential'ı olmadan (henüz sağlanmadı) uygulamanın çökmemesi ve
    doğrulama/reset akışının yine de test edilebilmesi için tasarlandı.
    """
    if not mail_configured:
        print(f"\n===== [DEV MODE — email not sent, no SMTP configured] =====\nTo: {to}\nSubject: {subject}\n\n{body}\n=============================================================\n", flush=True)
        return True
    try:
        msg = Message(subject=subject, recipients=[to], body=body)
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Email send error: {e}")
        return False

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

from travel_data import data
def init_db():
    print("Database connection started!")

def create_sample_reviews():
    """Örnek review'lar oluştur"""
    from datetime import datetime, timedelta
    
    sample_reviews = [
        {
            'id': 1,
            'title': 'Amazing Experience in Paris',
            'content': 'QuestWay helped me discover hidden gems in Paris that I never would have found on my own. The recommendations were spot on!',
            'rating': 5,
            'country': 'France',
            'city': 'Paris',
            'place_name': 'Eiffel Tower',
            'place_type': 'attraction',
            'created_at': datetime.now() - timedelta(days=2),
            'author': {'username': 'Sarah M.'}
        },
        {
            'id': 2,
            'title': 'Perfect Tokyo Adventure',
            'content': 'The itinerary suggestions were incredible. I had the most authentic Japanese experience thanks to QuestWay\'s local insights.',
            'rating': 5,
            'country': 'Japan',
            'city': 'Tokyo',
            'place_name': 'Shibuya',
            'place_type': 'attraction',
            'created_at': datetime.now() - timedelta(days=7),
            'author': {'username': 'Mike R.'}
        },
        {
            'id': 3,
            'title': 'Beautiful Rome Experience',
            'content': 'Rome was absolutely stunning! The historical sites and local food recommendations were perfect.',
            'rating': 4,
            'country': 'Italy',
            'city': 'Rome',
            'place_name': 'Colosseum',
            'place_type': 'attraction',
            'created_at': datetime.now() - timedelta(days=5),
            'author': {'username': 'Anna L.'}
        },
        {
            'id': 4,
            'title': 'Great Food in Barcelona',
            'content': 'The restaurant recommendations were amazing. I had the best paella of my life!',
            'rating': 4,
            'country': 'Spain',
            'city': 'Barcelona',
            'place_name': 'La Boqueria',
            'place_type': 'restaurant',
            'created_at': datetime.now() - timedelta(days=3),
            'author': {'username': 'Carlos M.'}
        },
        {
            'id': 5,
            'title': 'Excellent Hotel in Berlin',
            'content': 'The hotel was perfectly located and the service was outstanding. Highly recommended!',
            'rating': 5,
            'country': 'Germany',
            'city': 'Berlin',
            'place_name': 'Hotel Adlon',
            'place_type': 'hotel',
            'created_at': datetime.now() - timedelta(days=1),
            'author': {'username': 'Thomas K.'}
        }
    ]
    
    # Sample review objelerini oluştur
    class SampleReview:
        def __init__(self, data):
            for key, value in data.items():
                setattr(self, key, value)
    
    return [SampleReview(review) for review in sample_reviews]

@cache.memoize(timeout=300)  # 5 dakika cache
def calculate_review_stats_cached(country_filter, rating_filter, sort_filter):
    """Review istatistiklerini hesapla (cache'li)"""
    try:
        # Base query
        query = Review.query
        
        # Country filter
        if country_filter:
            query = query.filter(Review.country == country_filter)
        
        # Rating filter
        if rating_filter:
            query = query.filter(Review.rating >= int(rating_filter))
        
        # Filtrelenmiş review'ları al (limit olmadan)
        all_reviews = query.all()
        
        if not all_reviews:
            # Eğer hiç review yoksa, örnek review'lardan istatistik hesapla
            sample_reviews = create_sample_reviews()
            total_reviews = len(sample_reviews)
            avg_rating = sum(review.rating for review in sample_reviews) / total_reviews
            countries = len(set(review.country for review in sample_reviews))
        else:
            total_reviews = len(all_reviews)
            avg_rating = sum(review.rating for review in all_reviews) / total_reviews
            countries = len(set(review.country for review in all_reviews if review.country))
        
        return {
            'total_reviews': total_reviews,
            'average_rating': round(avg_rating, 1),
            'countries_covered': countries
        }
    except Exception as e:
        print(f"Stats hesaplama hatası: {e}")
        return {
            'total_reviews': 0,
            'average_rating': 0.0,
            'countries_covered': 0
        }

def calculate_review_stats(query):
    """Review istatistiklerini hesapla (eski fonksiyon - geriye uyumluluk için)"""
    try:
        # Filtrelenmiş review'ları al (limit olmadan)
        all_reviews = query.all()
        
        if not all_reviews:
            # Eğer hiç review yoksa, örnek review'lardan istatistik hesapla
            sample_reviews = create_sample_reviews()
            total_reviews = len(sample_reviews)
            avg_rating = sum(review.rating for review in sample_reviews) / total_reviews
            countries = len(set(review.country for review in sample_reviews))
        else:
            total_reviews = len(all_reviews)
            avg_rating = sum(review.rating for review in all_reviews) / total_reviews
            countries = len(set(review.country for review in all_reviews if review.country))
        
        return {
            'total_reviews': total_reviews,
            'average_rating': round(avg_rating, 1),
            'countries_covered': countries
        }
    except Exception as e:
        print(f"Stats hesaplama hatası: {e}")
        return {
            'total_reviews': 0,
            'average_rating': 0.0,
            'countries_covered': 0
        }

# Yorumları listeleme


# Review'ı faydalı bul / geri al (toggle)

# Yorum silme (gerçek Review modeli üzerinden, sadece sahibi silebilir)

# Ads.txt route for Google AdSense


# Ana sayfa

# Ülke seçme

# Detay sayfası

# Harita için konum arama (Leaflet + OpenStreetMap tarafından kullanılıyor)


# User Authentication Routes

def generate_referral_code():
    import secrets
    while True:
        code = secrets.token_hex(4).upper()  # 8 karakter, örn. 'A1B2C3D4'
        if not User.query.filter_by(referral_code=code).first():
            return code


def send_verification_email(user):
    token = token_serializer.dumps(user.email, salt='email-verify')
    link = url_for('auth.verify_email', token=token, _external=True)
    send_email(
        user.email,
        'Verify your QuestWay account',
        f"Hi {user.first_name or user.username},\n\nPlease verify your email by visiting this link (valid for 1 hour):\n{link}\n\nIf you didn't create a QuestWay account, ignore this email.",
    )


# Rozet tanımları: (key, isim, açıklama, ikon, kural fonksiyonu)
# Rozetler ayrı bir tablo yerine mevcut verilerden anlık hesaplanıyor —
# senkron kalması gereken ekstra bir tablo olmadığı için her zaman doğru.
BADGE_DEFINITIONS = [
    {
        'key': 'first_review', 'name': 'First Steps', 'icon': 'fa-flag-checkered',
        'description': 'Wrote your first review',
        'rule': lambda stats: stats['review_count'] >= 1,
    },
    {
        'key': 'storyteller', 'name': 'Storyteller', 'icon': 'fa-feather-pointed',
        'description': 'Wrote 5 or more reviews',
        'rule': lambda stats: stats['review_count'] >= 5,
    },
    {
        'key': 'explorer', 'name': 'Explorer', 'icon': 'fa-compass',
        'description': 'Reviewed places in 3 or more different countries',
        'rule': lambda stats: stats['country_count'] >= 3,
    },
    {
        'key': 'photographer', 'name': 'Photographer', 'icon': 'fa-camera',
        'description': 'Added a photo to a review',
        'rule': lambda stats: stats['has_photo'],
    },
    {
        'key': 'planner', 'name': 'Planner', 'icon': 'fa-route',
        'description': 'Created your first itinerary',
        'rule': lambda stats: stats['itinerary_count'] >= 1,
    },
    {
        'key': 'trusted_voice', 'name': 'Trusted Voice', 'icon': 'fa-thumbs-up',
        'description': "Received 5 or more 'helpful' votes across your reviews",
        'rule': lambda stats: stats['helpful_received'] >= 5,
    },
]


def compute_user_badges(user):
    all_reviews = Review.query.filter_by(user_id=user.id).all()
    stats = {
        'review_count': len(all_reviews),
        'country_count': len({r.country for r in all_reviews if r.country}),
        'has_photo': any(r.images for r in all_reviews),
        'itinerary_count': Itinerary.query.filter_by(user_id=user.id).count(),
        'helpful_received': sum(r.helpful_count or 0 for r in all_reviews),
    }
    earned = [b for b in BADGE_DEFINITIONS if b['rule'](stats)]
    locked = [b for b in BADGE_DEFINITIONS if b not in earned]
    return earned, locked

# Puan/seviye tabanlı sadakat sistemi. Rozetler (yukarıda) binary "kazandın/kazanmadı",
# bu ise sürekli birikip kullanıcıyı seviye atlatan bir katman.
LEVELS = [
    (0, 'Wanderer', 'fa-shoe-prints'),
    (100, 'Explorer', 'fa-compass'),
    (300, 'Adventurer', 'fa-mountain-sun'),
    (750, 'Globetrotter', 'fa-earth-americas'),
    (1500, 'Legend', 'fa-crown'),
]

POINTS_ADD_REVIEW = 10
POINTS_REVIEW_WITH_PHOTO_BONUS = 5
POINTS_CREATE_ITINERARY = 15
POINTS_FORUM_THREAD = 5
POINTS_FORUM_REPLY = 3
POINTS_HELPFUL_VOTE_RECEIVED = 2


def award_points(user, amount):
    if not user or amount == 0:
        return
    user.points = (user.points or 0) + amount


def get_user_level_info(points):
    points = points or 0
    current = LEVELS[0]
    next_level = None
    for i, (threshold, name, icon) in enumerate(LEVELS):
        if points >= threshold:
            current = (threshold, name, icon)
            next_level = LEVELS[i + 1] if i + 1 < len(LEVELS) else None
        else:
            break
    if next_level:
        span = next_level[0] - current[0]
        progress_pct = int(((points - current[0]) / span) * 100) if span > 0 else 100
    else:
        progress_pct = 100
    return {
        'name': current[1],
        'icon': current[2],
        'points': points,
        'next_name': next_level[1] if next_level else None,
        'next_threshold': next_level[0] if next_level else None,
        'progress_pct': progress_pct,
    }

# User Profile Routes


@cache.memoize(timeout=300)  # 5 dakika cache
def search_reviews_cached(query, country, place_type, rating_min):
    """Search reviews (cache'li).

    pg_trgm sayesinde yazım hatalarına dayanıklı (fuzzy) arama yapılıyor:
    'Pamukale' yazan biri de 'Pamukkale' geçen review'ları bulabiliyor.
    Tam substring eşleşmesi (ILIKE) hâlâ öncelikli tutuluyor, benzerlik skoru
    sadece sıralama ve typo-toleranslı eşleşme için kullanılıyor.
    """
    try:
        reviews_query = Review.query.join(User)

        conditions = []
        similarity_score = None

        if query and query.strip():
            q = query.strip()
            search_term = f"%{q}%"
            is_postgres = db.engine.dialect.name == 'postgresql'
            # pg_trgm sadece Postgres'te var — SQLite gibi başka dialect'lerde
            # (örn. test suite) düz ILIKE'a düşüyor, hata fırlatmıyor.
            if is_postgres:
                similarity_score = func.greatest(
                    func.similarity(Review.title, q),
                    func.similarity(Review.content, q),
                    func.similarity(func.coalesce(Review.place_name, ''), q),
                    func.similarity(func.coalesce(Review.city, ''), q),
                )
                conditions.append(
                    or_(
                        Review.title.ilike(search_term),
                        Review.content.ilike(search_term),
                        Review.place_name.ilike(search_term),
                        Review.city.ilike(search_term),
                        similarity_score > 0.25,
                    )
                )
            else:
                conditions.append(
                    or_(
                        Review.title.ilike(search_term),
                        Review.content.ilike(search_term),
                        Review.place_name.ilike(search_term),
                        Review.city.ilike(search_term),
                    )
                )

        if country and country != 'All':
            conditions.append(Review.country == country)

        if place_type and place_type != 'All':
            conditions.append(Review.place_type == place_type)

        if rating_min and rating_min > 0:
            conditions.append(Review.rating >= rating_min)

        for condition in conditions:
            reviews_query = reviews_query.filter(condition)

        if similarity_score is not None:
            reviews_query = reviews_query.order_by(similarity_score.desc(), Review.created_at.desc())
        else:
            reviews_query = reviews_query.order_by(Review.created_at.desc())

        return reviews_query.limit(20).all()
    except Exception as e:
        print(f"Search hatası: {e}")
        return []

# Advanced Search Route

# Wishlist Routes


# AJAX endpoints for wishlist


# Itinerary Routes


def build_user_travel_preferences(user):
    """Kullanıcının geçmiş review + wishlist verisinden kısa bir 'tercih profili' metni üretir.

    Yeni bir tablo/alan gerekmiyor — veri zaten Review/WishlistItem'da duruyor,
    sadece AI prompt'una bağlam olarak özetleniyor. Rakiplerin 'preference
    memory' dediği şeyin en ucuz versiyonu.
    """
    if not user or not user.is_authenticated:
        return None

    reviews = Review.query.filter_by(user_id=user.id).order_by(Review.created_at.desc()).limit(10).all()
    wishlist = WishlistItem.query.filter_by(user_id=user.id).order_by(WishlistItem.added_at.desc()).limit(10).all()
    if not reviews and not wishlist:
        return None

    lines = []
    if reviews:
        avg_rating = sum(r.rating for r in reviews) / len(reviews)
        place_types = [r.place_type for r in reviews if r.place_type]
        top_type = max(set(place_types), key=place_types.count) if place_types else None
        lines.append(f"Past reviews (avg rating given: {avg_rating:.1f}/5):")
        for r in reviews[:6]:
            lines.append(f"  - {r.place_name or r.title} ({r.place_type}, {r.country}), rated {r.rating}/5")
        if top_type:
            lines.append(f"  This traveler reviews {top_type} places most often — they likely enjoy that category.")
    if wishlist:
        lines.append("Wishlist (places they want to visit but haven't yet):")
        for w in wishlist[:6]:
            lines.append(f"  - {w.place_name} ({w.place_type}, {w.country})")

    return "\n".join(lines)


def generate_ai_itinerary(country, days, budget_level, interests, user=None):
    """Groq (Llama) ile gerçek QuestWay yer verisine dayalı gün-gün itinerary üretir.

    Halüsinasyonu azaltmak için modele sadece `data` sözlüğündeki gerçek yer
    isimlerini kullanması söyleniyor; JSON şeması sıkı tutuluyor ve parse
    hatasında (nadir de olsa modelin JSON dışına çıkması ihtimaline karşı)
    açık bir hata fırlatılıyor — sessizce sahte/boş bir plan gösterilmiyor.
    """
    country_data = data.get(country, {})
    places_context = []
    for section, label in [('famous_places', 'attraction'), ('top_hotels', 'hotel'),
                            ('top_restaurants', 'restaurant'), ('famous_dishes', 'food')]:
        for place in country_data.get(section, [])[:8]:
            places_context.append(f"- ({label}) {place['name']}: {place.get('description', '')}")

    interests_text = ', '.join(interests) if interests else 'general sightseeing'
    preference_profile = build_user_travel_preferences(user)
    preference_block = (
        f"\nThis traveler's history on QuestWay (use this to personalize choices and tone, "
        f"e.g. lean towards similar place types, avoid repeating exact places they've already visited):\n{preference_profile}\n"
        if preference_profile else ""
    )

    prompt = f"""You are a professional travel planner for QuestWay. Build a {days}-day itinerary for {country}
with a {budget_level} budget, focused on: {interests_text}.
{preference_block}
Use ONLY these real places QuestWay already has data on (prefer them heavily, you may add well-known
generic activities like "walk around the old town" if needed to fill gaps):
{chr(10).join(places_context) if places_context else '(no curated places available, use general knowledge of ' + country + ')'}

Return STRICT JSON only, no markdown, no commentary, matching exactly this schema:
{{
  "days": [
    {{
      "day": 1,
      "items": [
        {{"time_slot": "morning", "place_name": "...", "place_type": "attraction", "description": "one sentence", "estimated_duration": 90}}
      ]
    }}
  ]
}}
time_slot must be one of: morning, afternoon, evening. place_type must be one of: attraction, hotel, restaurant, transport, other.
estimated_duration is in minutes. Include 2-3 items per day."""

    completion = groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=2000,
        response_format={"type": "json_object"},
    )
    raw = completion.choices[0].message.content
    parsed = json.loads(raw)
    if 'days' not in parsed or not isinstance(parsed['days'], list):
        raise ValueError(f"Unexpected AI response shape: {raw[:200]}")
    return parsed

CHAT_SYSTEM_PROMPT = (
    "You are the QuestWay Travel Assistant, a friendly and concise AI chat helper embedded on the "
    "QuestWay travel guide website. QuestWay has destination guides, hotel/restaurant/attraction "
    "recommendations, user reviews, wishlists, and an itinerary planner for the following countries: "
    + ", ".join(data.keys()) + ". "
    "Answer travel questions helpfully and briefly (2-4 sentences unless asked for a list). "
    "When relevant, suggest the user try QuestWay's Search, Reviews, or AI Itinerary Planner pages. "
    "If you don't know something specific about a place, say so honestly instead of making it up."
)


def get_itinerary_permission(itinerary, user):
    """'owner' | 'edit' | 'view' | None — kullanıcının bu itinerary üzerindeki yetkisi."""
    if not user.is_authenticated:
        return 'view' if itinerary.is_public else None
    if itinerary.user_id == user.id:
        return 'owner'
    collab = ItineraryCollaborator.query.filter_by(itinerary_id=itinerary.id, user_id=user.id).first()
    if collab:
        return collab.permission
    if itinerary.is_public:
        return 'view'
    return None


def find_travel_buddies(itinerary, window_days=7, limit=6):
    """Aynı ülkeye yakın tarihlerde giden başka (herkese açık) gezginleri bul.

    Sadece is_public=True olan itinerary'ler taranıyor — mahremiyet zaten
    var olan is_public modeline saygı duyuyor, yeni bir gizlilik yüzeyi
    açmıyor. Tarihi olmayan itinerary'ler için sadece ülke eşleşmesi yeterli.
    """
    query = Itinerary.query.filter(
        Itinerary.is_public.is_(True),
        Itinerary.country == itinerary.country,
        Itinerary.user_id != itinerary.user_id,
        Itinerary.id != itinerary.id,
    )

    if itinerary.start_date:
        window_start = itinerary.start_date - timedelta(days=window_days)
        window_end = itinerary.start_date + timedelta(days=window_days)
        query = query.filter(
            or_(
                Itinerary.start_date.is_(None),
                Itinerary.start_date.between(window_start, window_end),
            )
        )

    return query.order_by(Itinerary.created_at.desc()).limit(limit).all()


def get_user_poll_votes(itinerary, user):
    """{option_id: True} — bu kullanıcının hangi anket seçeneklerine oy verdiği (template'te highlight için)."""
    if not user.is_authenticated:
        return {}
    option_ids = [o.id for poll in itinerary.polls for o in poll.options]
    if not option_ids:
        return {}
    votes = ItineraryPollVote.query.filter(
        ItineraryPollVote.option_id.in_(option_ids), ItineraryPollVote.user_id == user.id
    ).all()
    return {v.option_id: True for v in votes}


def compute_itinerary_balances(itinerary, expenses):
    """Splitwise mantığı: masraflar t participants arasında eşit bölünür.
    Katılımcılar = sahip + tüm collaborator'lar. Döner: (balances dict, settlement listesi).
    """
    participants = {itinerary.user_id: itinerary.user}
    for c in itinerary.collaborators:
        participants[c.user_id] = c.user
    n = len(participants)
    if n == 0 or not expenses:
        return {}, []

    total = sum(e.amount for e in expenses)
    fair_share = total / n

    paid_by_user = {uid: 0.0 for uid in participants}
    for e in expenses:
        paid_by_user[e.paid_by_user_id] = paid_by_user.get(e.paid_by_user_id, 0.0) + e.amount

    balances = {}
    for uid, user in participants.items():
        net = paid_by_user.get(uid, 0.0) - fair_share
        balances[uid] = {'user': user, 'paid': paid_by_user.get(uid, 0.0), 'net': net}

    # Greedy settlement: en çok alacaklıyı en çok borçluyla eşleştir
    creditors = sorted([(uid, b['net']) for uid, b in balances.items() if b['net'] > 0.01], key=lambda x: -x[1])
    debtors = sorted([(uid, -b['net']) for uid, b in balances.items() if b['net'] < -0.01], key=lambda x: -x[1])
    settlements = []
    i, j = 0, 0
    creditors, debtors = list(creditors), list(debtors)
    while i < len(debtors) and j < len(creditors):
        debtor_id, debt = debtors[i]
        creditor_id, credit = creditors[j]
        amount = min(debt, credit)
        settlements.append({
            'from_user': participants[debtor_id],
            'to_user': participants[creditor_id],
            'amount': amount,
        })
        debtors[i] = (debtor_id, debt - amount)
        creditors[j] = (creditor_id, credit - amount)
        if debtors[i][1] <= 0.01:
            i += 1
        if creditors[j][1] <= 0.01:
            j += 1

    return balances, settlements


def compute_eco_score(itinerary, items):
    """Kaba, deterministik bir sürdürülebilirlik skoru (0-100, yüksek = daha sürdürülebilir).

    Gerçek bir karbon API'sine bağlı değil (o ayrı bir maliyet/entegrasyon) —
    bunun yerine itinerary'nin şeklinden (kaç farklı şehir, transport ağırlığı,
    günlük aktivite yoğunluğu) kaba bir tahmin çıkarıyor. Sayı kesin bir bilim
    değil, bir yön göstergesi; AI kısmı sadece somut öneriler üretmek için kullanılıyor.
    """
    if not items:
        return None

    cities = {i.place_name for i in items if i.place_type == 'transport'}
    num_transport_items = sum(1 for i in items if i.place_type == 'transport')
    total_items = len(items)
    days = len({i.day_number for i in items}) or 1
    pace = total_items / days  # günde ortalama kaç aktivite (yüksek pace = daha çok hareket/transport)

    score = 100
    score -= min(40, num_transport_items * 8)  # her transport durağı puan kırar
    score -= min(20, max(0, int((pace - 3) * 5)))  # günde 3'ten fazla aktivite yorucu/hareketli sayılır
    score = max(10, min(100, score))

    if score >= 75:
        label = 'Low impact'
    elif score >= 45:
        label = 'Moderate impact'
    else:
        label = 'High impact'

    return {'score': score, 'label': label, 'pace_per_day': round(pace, 1), 'transport_stops': num_transport_items}


def notify_itinerary_activity_added(itinerary, actor, item):
    """Sahibe ve diğer collaborator'lara (ekleyen kişi hariç) e-posta bildirimi."""
    recipients = {itinerary.user: True}
    for c in itinerary.collaborators:
        recipients[c.user] = True
    recipients.pop(actor, None)

    for user in recipients:
        if not user or not user.email:
            continue
        send_email(
            user.email,
            f"{actor.username} added an activity to \"{itinerary.title}\"",
            f"Hi {user.first_name or user.username},\n\n{actor.username} just added \"{item.place_name}\" "
            f"(Day {item.day_number}) to the itinerary \"{itinerary.title}\".\n\n"
            f"View it: {url_for('itinerary.itinerary_detail', itinerary_id=itinerary.id, _external=True)}",
        )


# Enhanced Review Routes


def tri_state_bool(value):
    """SelectField('', 'yes', 'no') -> None/True/False."""
    if value == 'yes':
        return True
    if value == 'no':
        return False
    return None

def encode_review_images(files, max_images=3):
    """Yüklenen review fotoğraflarını sakla ve URL/data-URI listesi döndür.

    supabase_client yapılandırılmışsa (SUPABASE_URL + SUPABASE_SERVICE_KEY)
    dosyalar gerçek Supabase Storage bucket'ına yüklenir ve public URL'ler
    döner — DB şişmez, CDN üzerinden servis edilir. Yapılandırılmamışsa eski
    base64-in-DB davranışına (küçük ölçekte yeterli) sessizce düşer.
    """
    import base64
    import uuid

    results = []
    for file in (files or [])[:max_images]:
        if not file or not file.filename:
            continue
        mime = file.mimetype or 'image/jpeg'
        raw = file.read()

        if supabase_client:
            ext = (file.filename.rsplit('.', 1)[-1] if '.' in file.filename else 'jpg').lower()
            path = f"{uuid.uuid4().hex}.{ext}"
            try:
                supabase_client.storage.from_(SUPABASE_STORAGE_BUCKET).upload(
                    path, raw, file_options={'content-type': mime}
                )
                public_url = supabase_client.storage.from_(SUPABASE_STORAGE_BUCKET).get_public_url(path)
                results.append(public_url)
                continue
            except Exception as e:
                print(f"Supabase Storage upload failed, falling back to base64: {e}")

        data = base64.b64encode(raw).decode('ascii')
        results.append(f"data:{mime};base64,{data}")

    return results or None

# Forum Routes


# Admin / Moderasyon Paneli


# WMO weather codes -> human readable condition (used by Open-Meteo)
WMO_CONDITIONS = {
    0: 'Clear sky', 1: 'Mainly clear', 2: 'Partly cloudy', 3: 'Overcast',
    45: 'Fog', 48: 'Depositing rime fog',
    51: 'Light drizzle', 53: 'Moderate drizzle', 55: 'Dense drizzle',
    56: 'Light freezing drizzle', 57: 'Dense freezing drizzle',
    61: 'Slight rain', 63: 'Moderate rain', 65: 'Heavy rain',
    66: 'Light freezing rain', 67: 'Heavy freezing rain',
    71: 'Slight snow', 73: 'Moderate snow', 75: 'Heavy snow', 77: 'Snow grains',
    80: 'Slight rain showers', 81: 'Moderate rain showers', 82: 'Violent rain showers',
    85: 'Slight snow showers', 86: 'Heavy snow showers',
    95: 'Thunderstorm', 96: 'Thunderstorm with slight hail', 99: 'Thunderstorm with heavy hail',
}


@cache.memoize(timeout=3600)  # 1 saat - geocoding sonuçları neredeyse hiç değişmez
def geocode_place(place, country):
    """OpenStreetMap Nominatim ile şehir/ülke/POI (ör. 'Hagia Sophia') -> lat/lon.

    Open-Meteo'nun geocoding API'si sadece yerleşim yerlerini biliyor (POI'leri
    değil) ve isim çakışmalarında yanlış eşleşme verebiliyordu (örn. 'Turkey'
    araması ABD'deki bir kasabayı döndürüyordu). Nominatim hem şehir hem de
    landmark/POI aramalarını doğru şekilde karşılıyor.
    """
    query = f"{place}, {country}" if place and country and place != country else (place or country)
    resp = requests.get(
        'https://nominatim.openstreetmap.org/search',
        params={'q': query, 'format': 'json', 'limit': 1},
        headers={'User-Agent': 'QuestWay-TravelApp/1.0 (https://questway.app)'},
        timeout=5,
    )
    resp.raise_for_status()
    results = resp.json() or []
    if not results:
        return None
    match = results[0]
    return {'lat': float(match['lat']), 'lon': float(match['lon']), 'resolved_name': match.get('name') or place or country}


def fetch_current_weather(country, city):
    """Route dışından da çağrılabilen düz fonksiyon (paket listesi üretimi bunu kullanır)."""
    location = geocode_place(city, country)
    if not location:
        return None
    resp = requests.get(
        'https://api.open-meteo.com/v1/forecast',
        params={
            'latitude': location['lat'],
            'longitude': location['lon'],
            'current': 'temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code',
            'timezone': 'auto',
        },
        timeout=5,
    )
    resp.raise_for_status()
    current = resp.json().get('current', {})
    return {
        'city': location.get('resolved_name', city),
        'country': country,
        'temperature': current.get('temperature_2m'),
        'condition': WMO_CONDITIONS.get(current.get('weather_code'), 'Unknown'),
        'humidity': current.get('relative_humidity_2m'),
        'wind_speed': current.get('wind_speed_10m'),
        'source': 'open-meteo.com',
    }


def fetch_forecast_range(country, city, start_date, end_date):
    """Open-Meteo günlük tahmin (max ~16 gün ileriye). Aralık dışındaysa None döner."""
    location = geocode_place(city, country)
    if not location:
        return None
    resp = requests.get(
        'https://api.open-meteo.com/v1/forecast',
        params={
            'latitude': location['lat'],
            'longitude': location['lon'],
            'daily': 'temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max',
            'timezone': 'auto',
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
        },
        timeout=5,
    )
    resp.raise_for_status()
    daily = resp.json().get('daily')
    if not daily or not daily.get('time'):
        return None
    days = []
    for i, day in enumerate(daily['time']):
        days.append({
            'date': day,
            'temp_max': daily['temperature_2m_max'][i],
            'temp_min': daily['temperature_2m_min'][i],
            'condition': WMO_CONDITIONS.get(daily['weather_code'][i], 'Unknown'),
            'rain_chance': daily.get('precipitation_probability_max', [None] * len(daily['time']))[i],
        })
    return days


# Blueprints (route handlers live in blueprints/*.py; imported here, at the
# bottom, after every shared extension/helper/constant above is already
# defined on this module — the blueprint modules do `from app import ...`
# for those names, which only works because this import happens last).
from blueprints.main import main_bp
from blueprints.auth import auth_bp
from blueprints.wishlist import wishlist_bp
from blueprints.itinerary import itinerary_bp
from blueprints.review import review_bp
from blueprints.forum import forum_bp
from blueprints.admin import admin_bp
from blueprints.weather import weather_bp
from blueprints.cron import cron_bp

app.register_blueprint(main_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(wishlist_bp)
app.register_blueprint(itinerary_bp)
app.register_blueprint(review_bp)
app.register_blueprint(forum_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(weather_bp)
app.register_blueprint(cron_bp)


# Initialize database
def create_tables():
    with app.app_context():
        db.create_all()
        print("Veritabanı tabloları oluşturuldu!")
        
        # Örnek veri ekle
        add_sample_data()

def add_sample_data():
    """Örnek review verisi ekle (yalnızca zaten kayıtlı bir kullanıcı varsa).

    Not: Herkese açık, bilinen şifreli bir demo hesabı (testuser/password123)
    canlı ortamda güvenlik açığı olacağı için otomatik oluşturulmuyor.
    """
    # Reviews varsa örnek veri ekleme
    if Review.query.count() == 0:
        user = User.query.first()
        if user:
            sample_reviews = [
                {
                    'title': 'Amazing Experience in Paris',
                    'content': 'Paris was absolutely magical! The Eiffel Tower at sunset was breathtaking, and the food was incredible. The Louvre was overwhelming but worth every minute. The city has such a romantic atmosphere that you can feel it everywhere you go.',
                    'place_name': 'Eiffel Tower',
                    'city': 'Paris',
                    'country': 'France',
                    'place_type': 'attraction',
                    'rating': 5,
                    'verified_visit': True
                },
                {
                    'title': 'Perfect Roman Holiday',
                    'content': 'Rome exceeded all my expectations! The Colosseum was incredible, and the Vatican was absolutely stunning. The food was amazing - best pasta I\'ve ever had. The city is full of history and every corner tells a story.',
                    'place_name': 'Colosseum',
                    'city': 'Rome',
                    'country': 'Italy',
                    'place_type': 'attraction',
                    'rating': 5,
                    'verified_visit': True
                },
                {
                    'title': 'Beautiful Barcelona',
                    'content': 'Barcelona is a vibrant city with amazing architecture. The Sagrada Familia is unlike anything I\'ve ever seen. The beaches are great and the nightlife is fantastic. Highly recommend visiting Park Güell for amazing city views.',
                    'place_name': 'Sagrada Familia',
                    'city': 'Barcelona',
                    'country': 'Spain',
                    'place_type': 'attraction',
                    'rating': 4,
                    'verified_visit': True
                },
                {
                    'title': 'Incredible Tokyo Experience',
                    'content': 'Tokyo is a city like no other! The mix of traditional and modern is fascinating. The food is incredible, from street food to fine dining. The people are so polite and helpful. Shibuya crossing is a must-see experience.',
                    'place_name': 'Shibuya Crossing',
                    'city': 'Tokyo',
                    'country': 'Japan',
                    'place_type': 'attraction',
                    'rating': 5,
                    'verified_visit': True
                },
                {
                    'title': 'Stunning Santorini',
                    'content': 'Santorini is absolutely beautiful! The white buildings against the blue sea create the most picturesque views. The sunsets are legendary and the food is delicious. Perfect for a romantic getaway.',
                    'place_name': 'Oia Village',
                    'city': 'Santorini',
                    'country': 'Greece',
                    'place_type': 'attraction',
                    'rating': 5,
                    'verified_visit': True
                },
                {
                    'title': 'Amazing London Trip',
                    'content': 'London is such a diverse and exciting city! The history is incredible, from the Tower of London to Westminster Abbey. The food scene has improved dramatically. The museums are world-class and mostly free!',
                    'place_name': 'Big Ben',
                    'city': 'London',
                    'country': 'United Kingdom',
                    'place_type': 'attraction',
                    'rating': 4,
                    'verified_visit': True
                },
                {
                    'title': 'Perfect Beach Resort',
                    'content': 'This resort in Bali was absolutely perfect! The beach was pristine, the service was excellent, and the food was amazing. The spa treatments were incredible. Perfect for relaxation and rejuvenation.',
                    'place_name': 'Four Seasons Resort Bali',
                    'city': 'Bali',
                    'country': 'Indonesia',
                    'place_type': 'hotel',
                    'rating': 5,
                    'verified_visit': True
                },
                {
                    'title': 'Delicious Local Restaurant',
                    'content': 'This small family restaurant in Florence served the best pasta I\'ve ever had! The atmosphere was cozy and authentic. The wine selection was excellent and the service was warm and friendly. A true hidden gem!',
                    'place_name': 'Trattoria Mario',
                    'city': 'Florence',
                    'country': 'Italy',
                    'place_type': 'restaurant',
                    'rating': 5,
                    'verified_visit': True
                },
                {
                    'title': 'Amazing Mountain Views',
                    'content': 'The Swiss Alps are absolutely breathtaking! The hiking trails offer incredible views and the fresh mountain air is invigorating. The cable car rides provide spectacular panoramas. A must-visit for nature lovers.',
                    'place_name': 'Matterhorn',
                    'city': 'Zermatt',
                    'country': 'Switzerland',
                    'place_type': 'mountain',
                    'rating': 5,
                    'verified_visit': True
                },
                {
                    'title': 'Vibrant Nightlife',
                    'content': 'Berlin has an incredible nightlife scene! The clubs are world-famous and the music scene is diverse. The city comes alive at night with amazing energy. Perfect for those who love to dance and party.',
                    'place_name': 'Berghain',
                    'city': 'Berlin',
                    'country': 'Germany',
                    'place_type': 'nightlife',
                    'rating': 4,
                    'verified_visit': True
                },
                {
                    'title': 'Family Fun Adventure',
                    'content': 'Disneyland Paris was perfect for our family vacation! The kids had an amazing time and there was something for everyone. The rides were fun and the parades were spectacular. Great memories were made!',
                    'place_name': 'Disneyland Paris',
                    'city': 'Paris',
                    'country': 'France',
                    'place_type': 'family',
                    'rating': 4,
                    'verified_visit': True
                },
                {
                    'title': 'Cultural Heritage Site',
                    'content': 'The Acropolis in Athens is a must-see for history lovers! The ancient ruins are incredibly well-preserved and the views of Athens are spectacular. The museum nearby has amazing artifacts. A true cultural treasure.',
                    'place_name': 'Acropolis',
                    'city': 'Athens',
                    'country': 'Greece',
                    'place_type': 'culture',
                    'rating': 5,
                    'verified_visit': True
                }
            ]
            
            for review_data in sample_reviews:
                review = Review(
                    user_id=user.id,
                    title=review_data['title'],
                    content=review_data['content'],
                    place_name=review_data['place_name'],
                    city=review_data['city'],
                    country=review_data['country'],
                    place_type=review_data['place_type'],
                    rating=review_data['rating'],
                    verified_visit=review_data['verified_visit']
                )
                db.session.add(review)
            
            db.session.commit()
            print("Sample review data added!")

# Production ortamı için database initialization
def init_app():
    """Initialize the application for production"""
    try:
        with app.app_context():
            db.create_all()
            print("Database tables created successfully!")
    except Exception as e:
        print(f"Database initialization error: {e}")

# Production ortamında çalışması için
if __name__ != '__main__':
    # Gunicorn tarafından çalıştırıldığında (Render için)
    # Vercel için init_app vercel.py'de yapılacak
    if not os.environ.get('VERCEL'):
        init_app()

if __name__ == '__main__':
    try:
        init_db()  # Start database connection
        create_tables()  # Create database tables
        print("Application started successfully!")
        app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5050)))
    except Exception as e:
        print(f"Application startup error: {e}")
        # Render'da uygulama çalışmaya devam etsin
        app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 5050)))