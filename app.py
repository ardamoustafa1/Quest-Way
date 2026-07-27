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
import json
import requests
from urllib.parse import quote_plus
from dotenv import load_dotenv

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
    return redirect(request.referrer or url_for('index'))

# Security header'ları (Flask-Talisman). Not: site birçok template'te inline
# <script>/<style> kullanıyor (tema/dil toggle'ı, chat widget, form validasyonu vb.);
# bunları nonce'lı hale getirmek onlarca template'in yeniden yazılmasını
# gerektirir. Bu yüzden CSP script/style-src'de 'unsafe-inline' bırakıldı —
# hiç CSP olmamasından çok daha iyi (dış kaynaklardan script/stil yüklenmesini
# hâlâ engelliyor), ama XSS'e karşı mükemmel koruma değil. HTTPS zorlaması
# sadece gerçek production'da (Render/Vercel) açık, local http geliştirmeyi bozmuyor.
IS_PRODUCTION = bool(os.environ.get('RENDER') or os.environ.get('VERCEL'))
Talisman(
    app,
    force_https=IS_PRODUCTION,
    strict_transport_security=IS_PRODUCTION,
    session_cookie_secure=IS_PRODUCTION,
    content_security_policy={
        'default-src': "'self'",
        'script-src': ["'self'", "'unsafe-inline'", 'https://cdnjs.cloudflare.com', 'https://unpkg.com',
                        'https://pagead2.googlesyndication.com', 'https://www.googletagmanager.com'],
        'style-src': ["'self'", "'unsafe-inline'", 'https://fonts.googleapis.com', 'https://cdnjs.cloudflare.com',
                       'https://unpkg.com'],
        'font-src': ["'self'", 'https://fonts.gstatic.com', 'https://cdnjs.cloudflare.com'],
        'img-src': ["'self'", 'data:', 'https:'],
        'connect-src': ["'self'", 'https:'],
    },
    content_security_policy_nonce_in=[],
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
            return redirect(url_for('index'))
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
login_manager.login_view = 'login'
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
@app.route('/explore')
def explore():
    country_filter = request.args.get('country', '')
    query = Review.query.filter(Review.images.isnot(None))
    if country_filter:
        query = query.filter(Review.country == country_filter)
    photo_reviews = query.order_by(Review.created_at.desc()).limit(60).all()
    return render_template('explore.html', reviews=photo_reviews, country_filter=country_filter)

@app.route('/reviews')
def reviews():
    try:
        # Filter parametrelerini al
        country_filter = request.args.get('country', '')
        rating_filter = request.args.get('rating', '')
        sort_filter = request.args.get('sort', 'newest')
        accessible_filter = request.args.get('accessible', '')

        # Base query
        query = Review.query

        # Country filter
        if country_filter:
            query = query.filter(Review.country == country_filter)

        # Rating filter
        if rating_filter:
            query = query.filter(Review.rating >= int(rating_filter))

        # Accessibility filter
        if accessible_filter == '1':
            query = query.filter(Review.wheelchair_accessible.is_(True))

        # Sort filter
        if sort_filter == 'newest':
            query = query.order_by(Review.created_at.desc())
        elif sort_filter == 'oldest':
            query = query.order_by(Review.created_at.asc())
        elif sort_filter == 'rating':
            query = query.order_by(Review.rating.desc())
        
        # Limit results
        reviews = query.limit(50).all()
        
        # Eğer hiç review yoksa, örnek review'lar oluştur
        if not reviews:
            reviews = create_sample_reviews()
        
        # İstatistikleri hesapla (cache'li)
        stats = calculate_review_stats_cached(country_filter, rating_filter, sort_filter)

        voted_review_ids = set()
        if current_user.is_authenticated:
            voted_review_ids = {
                v.review_id for v in ReviewHelpfulVote.query.filter_by(user_id=current_user.id).all()
            }

        return render_template('reviews.html', reviews=reviews,
                             country_filter=country_filter,
                             rating_filter=rating_filter,
                             sort_filter=sort_filter,
                             accessible_filter=accessible_filter,
                             stats=stats,
                             voted_review_ids=voted_review_ids)
    except Exception as e:
        print(f"Reviews hatası: {e}")
        # Hata durumunda örnek review'lar döndür
        reviews = create_sample_reviews()
        stats = calculate_review_stats_cached('', '', 'newest')  # Fallback stats
        return render_template('reviews.html', reviews=reviews, stats=stats, voted_review_ids=set(), accessible_filter='')

# Review'ı faydalı bul / geri al (toggle)
@app.route('/review/<int:review_id>/helpful', methods=['POST'])
@login_required
def toggle_review_helpful(review_id):
    review = Review.query.get_or_404(review_id)
    existing_vote = ReviewHelpfulVote.query.filter_by(review_id=review_id, user_id=current_user.id).first()

    if existing_vote:
        db.session.delete(existing_vote)
        review.helpful_count = max(0, (review.helpful_count or 0) - 1)
        if review.author:
            award_points(review.author, -POINTS_HELPFUL_VOTE_RECEIVED)
        voted = False
    else:
        db.session.add(ReviewHelpfulVote(review_id=review_id, user_id=current_user.id))
        review.helpful_count = (review.helpful_count or 0) + 1
        if review.author:
            award_points(review.author, POINTS_HELPFUL_VOTE_RECEIVED)
        voted = True

    db.session.commit()
    return jsonify({'success': True, 'voted': voted, 'count': review.helpful_count})

# Yorum silme (gerçek Review modeli üzerinden, sadece sahibi silebilir)
@app.route('/delete_comment/<int:comment_id>', methods=['POST'])
@login_required
def delete_comment(comment_id):
    review = Review.query.filter_by(id=comment_id, user_id=current_user.id).first()
    if review:
        db.session.delete(review)
        db.session.commit()
        flash('Review deleted.', 'success')
    return redirect(url_for('reviews'))

# Ads.txt route for Google AdSense
@app.route('/ads.txt')
def ads_txt():
    try:
        with open('ads.txt', 'r', encoding='utf-8') as f:
            content = f.read()
        return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except FileNotFoundError:
        return 'google.com, pub-9221145906123169, DIRECT, f08c47fec0942fa0', 200, {'Content-Type': 'text/plain; charset=utf-8'}

@app.route('/robots.txt')
def robots_txt():
    lines = [
        'User-agent: *',
        'Allow: /',
        'Disallow: /admin',
        'Disallow: /admin/',
        'Disallow: /profile',
        'Disallow: /wishlist',
        'Disallow: /itineraries',
        'Disallow: /itinerary/',
        'Disallow: /api/',
        'Disallow: /internal/',
        f"Sitemap: {url_for('sitemap_xml', _external=True)}",
    ]
    return '\n'.join(lines), 200, {'Content-Type': 'text/plain; charset=utf-8'}

@app.route('/sitemap.xml')
@cache.cached(timeout=3600)
def sitemap_xml():
    urls = []
    now = datetime.utcnow().strftime('%Y-%m-%d')

    static_pages = ['index', 'reviews', 'explore', 'forum_index', 'search', 'login', 'register']
    for endpoint in static_pages:
        urls.append({'loc': url_for(endpoint, _external=True), 'lastmod': now, 'priority': '0.8'})

    for country in data.keys():
        for section in data[country].keys():
            urls.append({
                'loc': url_for('details', country_name=country, section=section, _external=True),
                'lastmod': now, 'priority': '0.7',
            })

    for itinerary in Itinerary.query.filter_by(is_public=True).all():
        urls.append({
            'loc': url_for('itinerary_detail', itinerary_id=itinerary.id, _external=True),
            'lastmod': itinerary.updated_at.strftime('%Y-%m-%d') if itinerary.updated_at else now,
            'priority': '0.5',
        })
        if itinerary.recap_text:
            urls.append({
                'loc': url_for('view_trip_recap', itinerary_id=itinerary.id, _external=True),
                'lastmod': itinerary.updated_at.strftime('%Y-%m-%d') if itinerary.updated_at else now,
                'priority': '0.6',
            })

    for thread in ForumThread.query.all():
        urls.append({
            'loc': url_for('forum_thread', thread_id=thread.id, _external=True),
            'lastmod': thread.updated_at.strftime('%Y-%m-%d') if thread.updated_at else now,
            'priority': '0.4',
        })

    xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        xml_parts.append(f"<url><loc>{u['loc']}</loc><lastmod>{u['lastmod']}</lastmod><priority>{u['priority']}</priority></url>")
    xml_parts.append('</urlset>')

    return '\n'.join(xml_parts), 200, {'Content-Type': 'application/xml; charset=utf-8'}

# Ana sayfa
@app.route('/')
def index():
    countries = data.keys()  # 'data' sözlüğünden tüm ülke isimlerini alır
    return render_template('index.html', countries=countries)

# Ülke seçme
@app.route('/country', methods=['GET', 'POST'])
def country():
    if request.method == 'POST':
        selected_country = request.form.get('country')  # Seçilen ülkeyi al
    else:
        selected_country = request.args.get('country')  # GET request'ten ülkeyi al
    
    if not selected_country:
        return redirect(url_for('index'))
    
    return render_template('country.html', country=selected_country)

# Detay sayfası
@app.route('/details/<country_name>/<section>')
def details(country_name, section):
    if country_name not in data:
        return f"Error: Country '{country_name}' not found", 404

    section_key = section.replace(" ", "_").lower()
    if section_key not in data[country_name]:
        return f"Error: Section '{section}' not found for country '{country_name}'", 404

    content = data[country_name][section_key]  # İçerik alınır
    return render_template('details.html', country=country_name, section=section, content=content)

# Harita için konum arama (Leaflet + OpenStreetMap tarafından kullanılıyor)
@app.route('/api/location')
def api_location():
    place = request.args.get('place', '')
    country = request.args.get('country', '')
    if not place and not country:
        return jsonify({'error': 'place or country query param required'}), 400
    location = geocode_place(place, country)
    if not location:
        return jsonify({'error': 'Location not found'}), 404
    return jsonify(location)

@app.route('/internal/send-trip-reminders', methods=['POST'])
def send_trip_reminders():
    """Günde bir kez dışarıdan (cron) tetiklenmesi beklenen endpoint.

    'X-Cron-Secret' header'ı CRON_SECRET ortam değişkenine eşit olmalı.
    CRON_SECRET set edilmemişse endpoint tamamen kapalıdır.
    """
    if not CRON_SECRET or request.headers.get('X-Cron-Secret') != CRON_SECRET:
        return jsonify({'error': 'Unauthorized'}), 401

    today = datetime.utcnow().date()
    reminder_window_days = 3
    target_date = today + timedelta(days=reminder_window_days)

    upcoming = Itinerary.query.filter(
        Itinerary.start_date == target_date,
        Itinerary.reminder_sent.is_(False),
    ).all()

    sent_count = 0
    for itinerary in upcoming:
        recipients = {itinerary.user}
        for c in itinerary.collaborators:
            recipients.add(c.user)
        for user in recipients:
            if not user or not user.email:
                continue
            send_email(
                user.email,
                f"Your trip \"{itinerary.title}\" starts in {reminder_window_days} days!",
                f"Hi {user.first_name or user.username},\n\nJust a heads up — your trip to "
                f"{itinerary.city or ''} {itinerary.country} starts on {itinerary.start_date.strftime('%B %d, %Y')}.\n\n"
                f"Review your itinerary: {url_for('itinerary_detail', itinerary_id=itinerary.id, _external=True)}",
            )
        itinerary.reminder_sent = True
        sent_count += 1

    db.session.commit()
    return jsonify({'itineraries_notified': sent_count})

# User Authentication Routes
@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("15/hour", methods=['POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
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
            return redirect(next_page) if next_page else redirect(url_for('index'))
        flash('Invalid username or password', 'error')
    
    return render_template('auth/login.html', form=form)

def generate_referral_code():
    import secrets
    while True:
        code = secrets.token_hex(4).upper()  # 8 karakter, örn. 'A1B2C3D4'
        if not User.query.filter_by(referral_code=code).first():
            return code

@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("10/hour", methods=['POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

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
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            flash('An error occurred during registration. Please try again.', 'error')
            return render_template('auth/register.html', form=form, ref_code=ref_code)

    return render_template('auth/register.html', form=form, ref_code=ref_code)

def send_verification_email(user):
    token = token_serializer.dumps(user.email, salt='email-verify')
    link = url_for('verify_email', token=token, _external=True)
    send_email(
        user.email,
        'Verify your QuestWay account',
        f"Hi {user.first_name or user.username},\n\nPlease verify your email by visiting this link (valid for 1 hour):\n{link}\n\nIf you didn't create a QuestWay account, ignore this email.",
    )

@app.route('/verify-email/<token>')
def verify_email(token):
    try:
        email = token_serializer.loads(token, salt='email-verify', max_age=3600)
    except SignatureExpired:
        flash('That verification link has expired. Please request a new one from your profile.', 'error')
        return redirect(url_for('login'))
    except BadSignature:
        flash('That verification link is invalid.', 'error')
        return redirect(url_for('login'))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash('Account not found.', 'error')
        return redirect(url_for('login'))

    user.email_verified = True
    db.session.commit()
    flash('Email verified! Thanks for confirming your account.', 'success')
    return redirect(url_for('login'))

@app.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("5/hour", methods=['POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = ForgotPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            token = token_serializer.dumps(user.email, salt='password-reset')
            link = url_for('reset_password', token=token, _external=True)
            send_email(
                user.email,
                'Reset your QuestWay password',
                f"Hi {user.first_name or user.username},\n\nClick this link to reset your password (valid for 1 hour):\n{link}\n\nIf you didn't request this, you can safely ignore this email.",
            )
        # Kullanıcı var mı yok mu bilgisini sızdırmamak için mesaj her durumda aynı
        flash('If that email is registered, a password reset link has been sent.', 'success')
        return redirect(url_for('login'))

    return render_template('auth/forgot_password.html', form=form)

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    try:
        email = token_serializer.loads(token, salt='password-reset', max_age=3600)
    except SignatureExpired:
        flash('That reset link has expired. Please request a new one.', 'error')
        return redirect(url_for('forgot_password'))
    except BadSignature:
        flash('That reset link is invalid.', 'error')
        return redirect(url_for('forgot_password'))

    user = User.query.filter_by(email=email).first()
    if not user:
        flash('Account not found.', 'error')
        return redirect(url_for('forgot_password'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash('Your password has been reset. Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('auth/reset_password.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

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
@app.route('/profile')
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

@app.route('/resend-verification', methods=['POST'])
@login_required
def resend_verification():
    if current_user.email_verified:
        flash('Your email is already verified.', 'info')
    else:
        send_verification_email(current_user)
        flash('Verification email sent — please check your inbox.', 'success')
    return redirect(url_for('profile'))

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
@app.route('/search', methods=['GET', 'POST'])
def search():
    form = SearchForm()
    results = []
    search_performed = False
    
    if form.validate_on_submit():
        search_performed = True
        query = form.query.data
        country = form.country.data
        place_type = form.place_type.data
        rating_min = form.rating_min.data
        
        # Search in reviews (cache'li)
        results = search_reviews_cached(query, country, place_type, rating_min)
        
        # If no results found, try a broader search
        if not results and query and query.strip():
            # Try searching without case sensitivity and with partial matches
            search_term = f"%{query.strip().lower()}%"
            results = Review.query.join(User).filter(
                (Review.title.ilike(search_term)) | 
                (Review.content.ilike(search_term)) |
                (Review.place_name.ilike(search_term))
            ).order_by(Review.created_at.desc()).limit(20).all()
    
    # If no search performed, don't show any results
    # User should perform a search first
    
    return render_template('search/results.html', form=form, results=results, search_performed=search_performed)

# Wishlist Routes
@app.route('/wishlist')
@login_required
def wishlist():
    items = WishlistItem.query.filter_by(user_id=current_user.id).order_by(WishlistItem.added_at.desc()).all()
    return render_template('user/wishlist.html', items=items)

@app.route('/add_to_wishlist', methods=['GET', 'POST'])
@login_required
def add_to_wishlist():
    form = WishlistForm()
    if form.validate_on_submit():
        item = WishlistItem(
            user_id=current_user.id,
            place_name=form.place_name.data,
            place_type=form.place_type.data,
            country=form.country.data,
            city=form.city.data,
            description=form.description.data
        )
        db.session.add(item)
        db.session.commit()
        flash('Added to wishlist!', 'success')
        return redirect(url_for('wishlist'))
    
    return render_template('user/add_wishlist.html', form=form)

@app.route('/quick-add', methods=['GET', 'POST'])
@limiter.limit("10/hour", methods=['POST'])
@login_required
def quick_add():
    extracted_places = None
    source_text = ''

    if request.method == 'POST' and 'caption' in request.form:
        source_text = request.form.get('caption', '').strip()
        if not source_text:
            flash('Paste a caption or description first.', 'error')
        elif not groq_client:
            flash('Quick add is not configured (missing GROQ_API_KEY).', 'error')
        else:
            try:
                prompt = f"""Extract every distinct travel place mentioned in this social media caption/text
(attractions, restaurants, hotels, cities, landmarks). Text:
\"\"\"{source_text[:2000]}\"\"\"

Return STRICT JSON only: {{"places": [{{"name": "...", "place_type": "attraction|hotel|restaurant|other", "country": "best guess or null", "city": "best guess or null"}}]}}
If no real places are mentioned, return {{"places": []}}."""
                completion = groq_client.chat.completions.create(
                    model=GROQ_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=600,
                    response_format={"type": "json_object"},
                )
                result = json.loads(completion.choices[0].message.content)
                extracted_places = result.get('places', [])
                if not extracted_places:
                    flash('No places found in that text — try pasting more descriptive text.', 'info')
            except Exception as e:
                print(f"Quick-add extraction error: {e}")
                flash('Could not analyze that text right now. Please try again.', 'error')

    return render_template('user/quick_add.html', extracted_places=extracted_places, source_text=source_text)

@app.route('/quick-add/save', methods=['POST'])
@login_required
def quick_add_save():
    names = request.form.getlist('place_name')
    types = request.form.getlist('place_type')
    countries = request.form.getlist('country')
    cities = request.form.getlist('city')
    selected = set(request.form.getlist('selected'))  # indexes as strings

    added = 0
    for i, name in enumerate(names):
        if str(i) not in selected or not name.strip():
            continue
        db.session.add(WishlistItem(
            user_id=current_user.id,
            place_name=name.strip(),
            place_type=(types[i] if i < len(types) and types[i] else 'other'),
            country=(countries[i] if i < len(countries) and countries[i] else 'Unknown'),
            city=(cities[i] if i < len(cities) and cities[i] else None),
            description='Added via Quick Add from social media caption.',
        ))
        added += 1

    if added:
        db.session.commit()
        flash(f'Added {added} place(s) to your wishlist!', 'success')
    else:
        flash('No places selected.', 'error')
    return redirect(url_for('wishlist'))

@app.route('/remove_from_wishlist/<int:item_id>', methods=['POST'])
@login_required
def remove_from_wishlist(item_id):
    item = WishlistItem.query.filter_by(id=item_id, user_id=current_user.id).first()
    if item:
        db.session.delete(item)
        db.session.commit()
        flash('Removed from wishlist!', 'success')
    return redirect(url_for('wishlist'))

# AJAX endpoints for wishlist
@app.route('/api/add_to_wishlist', methods=['POST'])
def add_to_wishlist_ajax():
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'message': 'Please login first'})
    try:
        data = request.get_json()
        print(f"Received data: {data}")
        print(f"User ID: {current_user.id}")
        
        # Check if item already exists
        existing_item = WishlistItem.query.filter_by(
            user_id=current_user.id,
            place_name=data.get('place_name'),
            country=data.get('country'),
            city=data.get('city')
        ).first()
        
        if existing_item:
            print("Item already exists in wishlist")
            return jsonify({'success': False, 'message': 'Already in wishlist'})
        
        item = WishlistItem(
            user_id=current_user.id,
            place_name=data.get('place_name'),
            place_type=data.get('place_type', 'country'),
            country=data.get('country'),
            city=data.get('city'),
            description=data.get('description', ''),
            image_url=data.get('image_url', '')
        )
        
        db.session.add(item)
        db.session.commit()
        print("Item added to wishlist successfully")
        
        return jsonify({'success': True, 'message': 'Added to wishlist'})
    except Exception as e:
        print(f"Error adding to wishlist: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/remove_from_wishlist', methods=['POST'])
def remove_from_wishlist_ajax():
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'message': 'Please login first'})
    try:
        data = request.get_json()
        
        item = WishlistItem.query.filter_by(
            user_id=current_user.id,
            place_name=data.get('place_name'),
            country=data.get('country'),
            city=data.get('city')
        ).first()
        
        if item:
            db.session.delete(item)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Removed from wishlist'})
        else:
            return jsonify({'success': False, 'message': 'Item not found'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

# Itinerary Routes
@app.route('/itineraries')
@login_required
def itineraries():
    owned = Itinerary.query.filter_by(user_id=current_user.id).order_by(Itinerary.created_at.desc()).all()
    shared_ids = [c.itinerary_id for c in ItineraryCollaborator.query.filter_by(user_id=current_user.id).all()]
    shared = Itinerary.query.filter(Itinerary.id.in_(shared_ids)).order_by(Itinerary.created_at.desc()).all() if shared_ids else []
    return render_template('user/itineraries.html', itineraries=owned, shared_itineraries=shared)

@app.route('/create_itinerary', methods=['GET', 'POST'])
@login_required
def create_itinerary():
    form = ItineraryForm()
    if form.validate_on_submit():
        itinerary = Itinerary(
            title=form.title.data,
            description=form.description.data,
            country=form.country.data,
            city=form.city.data,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            is_public=form.is_public.data,
            user_id=current_user.id
        )
        db.session.add(itinerary)
        award_points(current_user, POINTS_CREATE_ITINERARY)
        db.session.commit()
        flash('Itinerary created successfully!', 'success')
        return redirect(url_for('itinerary_detail', itinerary_id=itinerary.id))
    
    return render_template('user/create_itinerary.html', form=form)

@app.route('/ai-itinerary-planner', methods=['GET', 'POST'])
@limiter.limit("10/hour", methods=['POST'])
@login_required
def ai_itinerary_planner():
    form = AIItineraryForm()
    generated_plan = None
    generated_country = None
    generated_days_json = None  # JS'de "Save" için ham JSON

    if not groq_client:
        flash('AI itinerary planner is not configured (missing GROQ_API_KEY).', 'error')
        return render_template('user/ai_itinerary_planner.html', form=form, plan=None)

    if form.validate_on_submit():
        country = form.country.data
        try:
            generated_plan = generate_ai_itinerary(
                country=country,
                days=form.days.data,
                budget_level=form.budget_level.data,
                interests=form.interests.data,
                user=current_user,
            )
            generated_country = country
            generated_days_json = json.dumps(generated_plan)
        except Exception as e:
            print(f"AI itinerary generation error: {e}")
            flash('Could not generate an itinerary right now. Please try again.', 'error')

    return render_template('user/ai_itinerary_planner.html', form=form, plan=generated_plan,
                            plan_country=generated_country, plan_json=generated_days_json)


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

@app.route('/api/chat', methods=['POST'])
@limiter.limit("30/hour")
@login_required
def api_chat():
    if not groq_client:
        return jsonify({'error': 'Chat assistant is not configured.'}), 503

    payload = request.get_json(silent=True) or {}
    user_message = (payload.get('message') or '').strip()
    history = payload.get('history') or []  # [{role, content}, ...] client tarafından tutulur

    if not user_message:
        return jsonify({'error': 'Message is required.'}), 400
    if len(user_message) > 1000:
        return jsonify({'error': 'Message is too long.'}), 400

    # Client geçmişini sınırla ve sadece beklenen alanları al (prompt injection'a karşı temizlik)
    safe_history = []
    for turn in history[-8:]:
        role = turn.get('role')
        content = turn.get('content', '')
        if role in ('user', 'assistant') and isinstance(content, str):
            safe_history.append({'role': role, 'content': content[:1000]})

    messages = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}] + safe_history + [
        {"role": "user", "content": user_message}
    ]

    try:
        completion = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=0.6,
            max_tokens=500,
        )
        reply = completion.choices[0].message.content
        return jsonify({'reply': reply})
    except Exception as e:
        print(f"Chat error: {e}")
        return jsonify({'error': 'The assistant is temporarily unavailable.'}), 503

@app.route('/ai-itinerary-planner/save', methods=['POST'])
@login_required
def save_ai_itinerary():
    country = request.form.get('country')
    plan_json = request.form.get('plan_json')
    if not country or not plan_json:
        flash('Nothing to save.', 'error')
        return redirect(url_for('ai_itinerary_planner'))

    try:
        plan = json.loads(plan_json)
    except (TypeError, ValueError):
        flash('Could not save that itinerary — the plan data was invalid.', 'error')
        return redirect(url_for('ai_itinerary_planner'))

    itinerary = Itinerary(
        title=f"AI Trip to {country}",
        description=f"Generated by QuestWay AI Planner for {country}.",
        country=country,
        user_id=current_user.id,
    )
    db.session.add(itinerary)
    db.session.flush()  # itinerary.id'yi item'lardan önce almak için

    order_index = 1
    for day in plan.get('days', []):
        day_number = day.get('day', 1)
        for item in day.get('items', []):
            db.session.add(ItineraryItem(
                itinerary_id=itinerary.id,
                day_number=day_number,
                time_slot=item.get('time_slot'),
                place_name=item.get('place_name', 'Untitled stop'),
                place_type=item.get('place_type', 'other'),
                description=item.get('description'),
                estimated_duration=item.get('estimated_duration'),
                order_index=order_index,
            ))
            order_index += 1

    db.session.commit()
    flash('Itinerary saved! You can now edit and share it.', 'success')
    return redirect(url_for('itinerary_detail', itinerary_id=itinerary.id))

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

@app.route('/itinerary/<int:itinerary_id>')
@login_required
def itinerary_detail(itinerary_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    permission = get_itinerary_permission(itinerary, current_user)
    if permission is None:
        flash('You do not have permission to view this itinerary.', 'error')
        return redirect(url_for('itineraries'))

    items = ItineraryItem.query.filter_by(itinerary_id=itinerary_id).order_by(ItineraryItem.day_number, ItineraryItem.order_index).all()
    item_form = ItineraryItemForm()
    expense_form = ItineraryExpenseForm()
    expenses = ItineraryExpense.query.filter_by(itinerary_id=itinerary_id).order_by(ItineraryExpense.created_at.desc()).all()
    balances, settlements = compute_itinerary_balances(itinerary, expenses)
    user_poll_votes = get_user_poll_votes(itinerary, current_user)
    travel_buddies = find_travel_buddies(itinerary) if permission == 'owner' else []
    return render_template('user/itinerary_detail.html', itinerary=itinerary, items=items,
                            permission=permission, item_form=item_form,
                            expense_form=expense_form, expenses=expenses,
                            balances=balances, settlements=settlements,
                            user_poll_votes=user_poll_votes, travel_buddies=travel_buddies)


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

@app.route('/itinerary/<int:itinerary_id>/polls', methods=['POST'])
@login_required
def create_itinerary_poll(itinerary_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    permission = get_itinerary_permission(itinerary, current_user)
    if permission not in ('owner', 'edit'):
        flash('You do not have permission to create polls on this itinerary.', 'error')
        return redirect(url_for('itinerary_detail', itinerary_id=itinerary_id))

    question = request.form.get('question', '').strip()
    option_texts = [o.strip() for o in request.form.getlist('options') if o.strip()]
    if not question or len(option_texts) < 2:
        flash('A poll needs a question and at least 2 options.', 'error')
        return redirect(url_for('itinerary_detail', itinerary_id=itinerary_id))

    poll = ItineraryPoll(itinerary_id=itinerary_id, question=question, created_by_user_id=current_user.id)
    db.session.add(poll)
    db.session.flush()
    for text in option_texts[:8]:
        db.session.add(ItineraryPollOption(poll_id=poll.id, text=text))
    db.session.commit()
    flash('Poll created!', 'success')
    return redirect(url_for('itinerary_detail', itinerary_id=itinerary_id))

@app.route('/polls/<int:poll_id>/vote', methods=['POST'])
@login_required
def vote_itinerary_poll(poll_id):
    poll = ItineraryPoll.query.get_or_404(poll_id)
    permission = get_itinerary_permission(poll.itinerary, current_user)
    if permission is None:
        flash('You do not have permission to vote on this poll.', 'error')
        return redirect(url_for('itineraries'))

    option_id = request.form.get('option_id', type=int)
    option = ItineraryPollOption.query.filter_by(id=option_id, poll_id=poll_id).first()
    if not option:
        flash('Invalid poll option.', 'error')
        return redirect(url_for('itinerary_detail', itinerary_id=poll.itinerary_id))

    # Bu kullanıcının bu anketteki önceki oyunu sil (tek oy hakkı / oy değiştirme)
    option_ids = [o.id for o in poll.options]
    ItineraryPollVote.query.filter(
        ItineraryPollVote.option_id.in_(option_ids), ItineraryPollVote.user_id == current_user.id
    ).delete(synchronize_session=False)
    db.session.add(ItineraryPollVote(option_id=option_id, user_id=current_user.id))
    db.session.commit()
    flash('Vote recorded!', 'success')
    return redirect(url_for('itinerary_detail', itinerary_id=poll.itinerary_id))

@app.route('/itinerary/<int:itinerary_id>/generate-recap', methods=['POST'])
@limiter.limit("10/hour")
@login_required
def generate_trip_recap(itinerary_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    if itinerary.user_id != current_user.id:
        flash('Only the trip owner can generate a trip recap.', 'error')
        return redirect(url_for('itinerary_detail', itinerary_id=itinerary_id))

    if not groq_client:
        flash('Trip recap is not configured (missing GROQ_API_KEY).', 'error')
        return redirect(url_for('itinerary_detail', itinerary_id=itinerary_id))

    items = ItineraryItem.query.filter_by(itinerary_id=itinerary_id).order_by(ItineraryItem.day_number, ItineraryItem.order_index).all()
    related_reviews = Review.query.filter_by(user_id=current_user.id, country=itinerary.country).order_by(Review.created_at.desc()).limit(10).all()

    items_text = "\n".join(f"  Day {i.day_number}: {i.place_name} ({i.place_type})" for i in items) or "(no activities logged)"
    reviews_text = "\n".join(f"  - \"{r.title}\": {r.content[:200]}" for r in related_reviews) or "(no reviews from this trip)"

    prompt = f"""Write a warm, engaging first-person trip recap (250-350 words) for a traveler's trip called
"{itinerary.title}" to {itinerary.city or ''} {itinerary.country}.

Itinerary activities:
{items_text}

Traveler's own reviews from this country:
{reviews_text}

Write it as if the traveler is sharing their trip story with friends — highlight 2-3 memorable moments,
keep it authentic and specific to the places listed above, not generic. Plain text only, no markdown headers."""

    try:
        completion = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=600,
        )
        itinerary.recap_text = completion.choices[0].message.content
        db.session.commit()
        flash('Trip recap generated!', 'success')
    except Exception as e:
        print(f"Trip recap generation error: {e}")
        flash('Could not generate a trip recap right now. Please try again.', 'error')

    return redirect(url_for('itinerary_detail', itinerary_id=itinerary_id))

@app.route('/itinerary/<int:itinerary_id>/recap')
def view_trip_recap(itinerary_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    permission = get_itinerary_permission(itinerary, current_user)
    if permission is None:
        flash('You do not have permission to view this trip recap.', 'error')
        return redirect(url_for('itineraries'))
    if not itinerary.recap_text:
        flash('This trip does not have a recap yet.', 'info')
        return redirect(url_for('itinerary_detail', itinerary_id=itinerary_id))

    photos = []
    for r in Review.query.filter_by(user_id=itinerary.user_id, country=itinerary.country).all():
        if r.images:
            photos.extend(r.images[:2])
    return render_template('user/trip_recap.html', itinerary=itinerary, photos=photos[:8])


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

@app.route('/itinerary/<int:itinerary_id>/expenses', methods=['POST'])
@login_required
def add_itinerary_expense(itinerary_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    permission = get_itinerary_permission(itinerary, current_user)
    if permission not in ('owner', 'edit'):
        flash('You do not have permission to add expenses to this itinerary.', 'error')
        return redirect(url_for('itinerary_detail', itinerary_id=itinerary_id))

    form = ItineraryExpenseForm()
    if form.validate_on_submit():
        db.session.add(ItineraryExpense(
            itinerary_id=itinerary_id,
            paid_by_user_id=current_user.id,
            description=form.description.data,
            amount=form.amount.data,
            currency=form.currency.data,
        ))
        db.session.commit()
        flash('Expense added!', 'success')
    else:
        flash('Could not add expense — please check the form.', 'error')
    return redirect(url_for('itinerary_detail', itinerary_id=itinerary_id))

@app.route('/itinerary/<int:itinerary_id>/packing-list', methods=['POST'])
@limiter.limit("10/hour")
@login_required
def generate_packing_list(itinerary_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    permission = get_itinerary_permission(itinerary, current_user)
    if permission is None:
        flash('You do not have permission to view this itinerary.', 'error')
        return redirect(url_for('itineraries'))

    if not groq_client:
        flash('AI packing list is not configured (missing GROQ_API_KEY).', 'error')
        return redirect(url_for('itinerary_detail', itinerary_id=itinerary_id))

    try:
        weather_context = "No live forecast available for these dates — use typical seasonal climate knowledge instead."
        today = datetime.utcnow().date()
        if itinerary.start_date and itinerary.end_date:
            days_out = (itinerary.start_date - today).days
            if 0 <= days_out <= 15:
                forecast = fetch_forecast_range(itinerary.country, itinerary.city, itinerary.start_date, itinerary.end_date)
                if forecast:
                    lines = [f"  - {d['date']}: {d['temp_min']}-{d['temp_max']}°C, {d['condition']}, rain chance {d['rain_chance']}%" for d in forecast]
                    weather_context = "Real forecast for the trip dates:\n" + "\n".join(lines)

        prompt = f"""Build a packing list for a {itinerary.title} trip to {itinerary.city or ''} {itinerary.country},
from {itinerary.start_date or 'an unspecified date'} to {itinerary.end_date or 'an unspecified date'}.

Weather:
{weather_context}

Return STRICT JSON only, matching exactly this schema:
{{"categories": [{{"name": "Clothing", "items": ["item1", "item2"]}}]}}
Include categories like Clothing, Footwear, Documents, Electronics, Health/Toiletries, and Weather-specific extras.
Keep each category to 4-8 concise items. Tailor clothing/footwear choices directly to the weather above."""

        completion = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=800,
            response_format={"type": "json_object"},
        )
        packing_list = json.loads(completion.choices[0].message.content)
    except Exception as e:
        print(f"Packing list generation error: {e}")
        flash('Could not generate a packing list right now. Please try again.', 'error')
        return redirect(url_for('itinerary_detail', itinerary_id=itinerary_id))

    items = ItineraryItem.query.filter_by(itinerary_id=itinerary_id).order_by(ItineraryItem.day_number, ItineraryItem.order_index).all()
    item_form = ItineraryItemForm()
    expense_form = ItineraryExpenseForm()
    expenses = ItineraryExpense.query.filter_by(itinerary_id=itinerary_id).order_by(ItineraryExpense.created_at.desc()).all()
    balances, settlements = compute_itinerary_balances(itinerary, expenses)
    user_poll_votes = get_user_poll_votes(itinerary, current_user)
    return render_template('user/itinerary_detail.html', itinerary=itinerary, items=items,
                            permission=permission, item_form=item_form,
                            expense_form=expense_form, expenses=expenses,
                            balances=balances, settlements=settlements,
                            packing_list=packing_list, user_poll_votes=user_poll_votes)

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

@app.route('/itinerary/<int:itinerary_id>/eco-score', methods=['POST'])
@limiter.limit("10/hour")
@login_required
def generate_eco_score(itinerary_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    permission = get_itinerary_permission(itinerary, current_user)
    if permission is None:
        flash('You do not have permission to view this itinerary.', 'error')
        return redirect(url_for('itineraries'))

    items = ItineraryItem.query.filter_by(itinerary_id=itinerary_id).order_by(ItineraryItem.day_number, ItineraryItem.order_index).all()
    eco_score = compute_eco_score(itinerary, items)
    if eco_score is None:
        flash('Add some activities to your itinerary first so we can estimate an eco-score.', 'info')
        return redirect(url_for('itinerary_detail', itinerary_id=itinerary_id))

    if groq_client:
        try:
            prompt = f"""A traveler's itinerary to {itinerary.city or ''} {itinerary.country} has an estimated
sustainability score of {eco_score['score']}/100 ({eco_score['label']}), based on {eco_score['transport_stops']}
transport-heavy stops and {eco_score['pace_per_day']} activities/day on average.

Give exactly 3 short, concrete, actionable tips (max 15 words each) to make this specific trip more
sustainable (e.g. train vs flight, public transit, eco-certified stays, slower pace). Return STRICT JSON only:
{{"tips": ["tip 1", "tip 2", "tip 3"]}}"""
            completion = groq_client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=300,
                response_format={"type": "json_object"},
            )
            eco_score['tips'] = json.loads(completion.choices[0].message.content).get('tips', [])
        except Exception as e:
            print(f"Eco-score tips generation error: {e}")
            eco_score['tips'] = []
    else:
        eco_score['tips'] = []

    item_form = ItineraryItemForm()
    expense_form = ItineraryExpenseForm()
    expenses = ItineraryExpense.query.filter_by(itinerary_id=itinerary_id).order_by(ItineraryExpense.created_at.desc()).all()
    balances, settlements = compute_itinerary_balances(itinerary, expenses)
    user_poll_votes = get_user_poll_votes(itinerary, current_user)
    travel_buddies = find_travel_buddies(itinerary) if permission == 'owner' else []
    return render_template('user/itinerary_detail.html', itinerary=itinerary, items=items,
                            permission=permission, item_form=item_form,
                            expense_form=expense_form, expenses=expenses,
                            balances=balances, settlements=settlements,
                            user_poll_votes=user_poll_votes, travel_buddies=travel_buddies,
                            eco_score=eco_score)

@app.route('/itinerary/<int:itinerary_id>/items', methods=['POST'])
@login_required
def add_itinerary_item(itinerary_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    permission = get_itinerary_permission(itinerary, current_user)
    if permission not in ('owner', 'edit'):
        flash('You do not have permission to edit this itinerary.', 'error')
        return redirect(url_for('itinerary_detail', itinerary_id=itinerary_id))

    form = ItineraryItemForm()
    if form.validate_on_submit():
        max_order = db.session.query(db.func.max(ItineraryItem.order_index)).filter_by(itinerary_id=itinerary_id).scalar() or 0
        item = ItineraryItem(
            itinerary_id=itinerary_id,
            day_number=form.day_number.data,
            time_slot=form.time_slot.data,
            place_name=form.place_name.data,
            place_type=form.place_type.data,
            description=form.description.data,
            address=form.address.data,
            estimated_duration=form.estimated_duration.data,
            notes=form.notes.data,
            order_index=max_order + 1,
        )
        db.session.add(item)
        db.session.commit()
        notify_itinerary_activity_added(itinerary, current_user, item)
        flash('Item added to itinerary!', 'success')
    else:
        flash('Could not add item — please check the form.', 'error')
    return redirect(url_for('itinerary_detail', itinerary_id=itinerary_id))


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
            f"View it: {url_for('itinerary_detail', itinerary_id=itinerary.id, _external=True)}",
        )

@app.route('/itinerary/<int:itinerary_id>/share', methods=['POST'])
@login_required
def share_itinerary(itinerary_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    if itinerary.user_id != current_user.id:
        flash('Only the owner can share this itinerary.', 'error')
        return redirect(url_for('itinerary_detail', itinerary_id=itinerary_id))

    username = request.form.get('username', '').strip()
    permission = request.form.get('permission', 'view')
    if permission not in ('view', 'edit'):
        permission = 'view'

    collaborator_user = User.query.filter_by(username=username).first()
    if not collaborator_user:
        flash(f"No user found with username '{username}'.", 'error')
    elif collaborator_user.id == current_user.id:
        flash("You already own this itinerary.", 'error')
    else:
        existing = ItineraryCollaborator.query.filter_by(itinerary_id=itinerary_id, user_id=collaborator_user.id).first()
        if existing:
            existing.permission = permission
            flash(f"Updated {collaborator_user.username}'s permission to {permission}.", 'success')
        else:
            db.session.add(ItineraryCollaborator(itinerary_id=itinerary_id, user_id=collaborator_user.id, permission=permission))
            flash(f"{collaborator_user.username} can now {permission} this itinerary.", 'success')
        db.session.commit()

    return redirect(url_for('itinerary_detail', itinerary_id=itinerary_id))

@app.route('/itinerary/<int:itinerary_id>/collaborators/<int:collaborator_id>/remove', methods=['POST'])
@login_required
def remove_collaborator(itinerary_id, collaborator_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    if itinerary.user_id != current_user.id:
        flash('Only the owner can manage collaborators.', 'error')
        return redirect(url_for('itinerary_detail', itinerary_id=itinerary_id))

    collab = ItineraryCollaborator.query.filter_by(id=collaborator_id, itinerary_id=itinerary_id).first()
    if collab:
        db.session.delete(collab)
        db.session.commit()
        flash('Collaborator removed.', 'success')
    return redirect(url_for('itinerary_detail', itinerary_id=itinerary_id))

# Enhanced Review Routes
@app.route('/add_review', methods=['GET', 'POST'])
@login_required
def add_review():
    form = ReviewForm()
    if form.validate_on_submit():
        review = Review(
            title=form.title.data,
            content=form.content.data,
            rating=form.rating.data,
            country=form.country.data,
            city=form.city.data,
            place_name=form.place_name.data,
            place_type=form.place_type.data,
            verified_visit=form.verified_visit.data,
            images=encode_review_images(form.images.data),
            wheelchair_accessible=tri_state_bool(form.wheelchair_accessible.data),
            step_free_access=tri_state_bool(form.step_free_access.data),
            accessibility_notes=form.accessibility_notes.data or None,
            user_id=current_user.id
        )
        db.session.add(review)
        award_points(current_user, POINTS_ADD_REVIEW + (POINTS_REVIEW_WITH_PHOTO_BONUS if review.images else 0))
        db.session.commit()
        flash('Review added successfully!', 'success')
        return redirect(url_for('reviews'))

    return render_template('reviews/add_review.html', form=form)


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
@app.route('/forum')
def forum_index():
    country_filter = request.args.get('country', '')
    query = ForumThread.query
    if country_filter:
        query = query.filter(ForumThread.country == country_filter)
    threads = query.order_by(ForumThread.updated_at.desc()).limit(50).all()
    reply_counts = {
        t.id: ForumPost.query.filter_by(thread_id=t.id).count() for t in threads
    }
    return render_template('forum/index.html', threads=threads, reply_counts=reply_counts, country_filter=country_filter)

@app.route('/forum/new', methods=['GET', 'POST'])
@login_required
def forum_new_thread():
    form = ForumThreadForm()
    if form.validate_on_submit():
        thread = ForumThread(title=form.title.data, country=form.country.data or None, user_id=current_user.id)
        db.session.add(thread)
        db.session.flush()
        db.session.add(ForumPost(thread_id=thread.id, user_id=current_user.id, content=form.content.data))
        award_points(current_user, POINTS_FORUM_THREAD)
        db.session.commit()
        flash('Discussion started!', 'success')
        return redirect(url_for('forum_thread', thread_id=thread.id))

    return render_template('forum/new_thread.html', form=form)

@app.route('/forum/<int:thread_id>', methods=['GET', 'POST'])
def forum_thread(thread_id):
    thread = ForumThread.query.get_or_404(thread_id)
    reply_form = ForumReplyForm()

    if reply_form.validate_on_submit():
        if not current_user.is_authenticated:
            return redirect(url_for('login', next=request.path))
        db.session.add(ForumPost(thread_id=thread.id, user_id=current_user.id, content=reply_form.content.data))
        thread.updated_at = datetime.utcnow()
        award_points(current_user, POINTS_FORUM_REPLY)
        db.session.commit()
        flash('Reply posted!', 'success')
        return redirect(url_for('forum_thread', thread_id=thread.id))

    return render_template('forum/thread_detail.html', thread=thread, reply_form=reply_form)

# Admin / Moderasyon Paneli
@app.route('/admin')
@admin_required
def admin_dashboard():
    stats = {
        'users': User.query.count(),
        'reviews': Review.query.count(),
        'itineraries': Itinerary.query.count(),
        'forum_threads': ForumThread.query.count(),
        'forum_posts': ForumPost.query.count(),
    }
    return render_template('admin/dashboard.html', stats=stats)

@app.route('/admin/reviews')
@admin_required
def admin_reviews():
    reviews = Review.query.order_by(Review.created_at.desc()).limit(200).all()
    return render_template('admin/reviews.html', reviews=reviews)

@app.route('/admin/reviews/<int:review_id>/delete', methods=['POST'])
@admin_required
def admin_delete_review(review_id):
    review = Review.query.get_or_404(review_id)
    ReviewHelpfulVote.query.filter_by(review_id=review_id).delete()
    db.session.delete(review)
    db.session.commit()
    flash('Review deleted.', 'success')
    return redirect(url_for('admin_reviews'))

@app.route('/admin/forum')
@admin_required
def admin_forum():
    threads = ForumThread.query.order_by(ForumThread.updated_at.desc()).limit(200).all()
    return render_template('admin/forum.html', threads=threads)

@app.route('/admin/forum/<int:thread_id>/delete', methods=['POST'])
@admin_required
def admin_delete_thread(thread_id):
    thread = ForumThread.query.get_or_404(thread_id)
    ForumPost.query.filter_by(thread_id=thread_id).delete()
    db.session.delete(thread)
    db.session.commit()
    flash('Thread deleted.', 'success')
    return redirect(url_for('admin_forum'))

@app.route('/admin/forum/post/<int:post_id>/delete', methods=['POST'])
@admin_required
def admin_delete_post(post_id):
    post = ForumPost.query.get_or_404(post_id)
    thread_id = post.thread_id
    db.session.delete(post)
    db.session.commit()
    flash('Post deleted.', 'success')
    return redirect(url_for('admin_forum'))

@app.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).limit(200).all()
    return render_template('admin/users.html', users=users)

@app.route('/admin/users/<int:user_id>/toggle-active', methods=['POST'])
@admin_required
def admin_toggle_user_active(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot deactivate your own account.', 'error')
        return redirect(url_for('admin_users'))
    user.is_active = not user.is_active
    db.session.commit()
    flash(f"{user.username} is now {'active' if user.is_active else 'banned'}.", 'success')
    return redirect(url_for('admin_users'))

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

@app.route('/weather/<country>/<city>')
@cache.memoize(timeout=1800)  # 30 dakika - hava durumu bu sıklıkta yenilense yeterli
def get_weather(country, city):
    try:
        weather = fetch_current_weather(country, city)
        if not weather:
            return jsonify({'error': f"Location not found for {city}, {country}"}), 404
        return jsonify(weather)
    except requests.RequestException as e:
        print(f"Weather API error: {e}")
        return jsonify({'error': 'Weather service temporarily unavailable'}), 503


@app.route('/currency/<from_currency>/<to_currency>')
@cache.memoize(timeout=3600)  # 1 saat - döviz kurları bu sıklıkta güncellense yeterli
def get_currency_rate(from_currency, to_currency):
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()
    try:
        resp = requests.get(
            'https://api.frankfurter.app/latest',
            params={'from': from_currency, 'to': to_currency},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        rate = data.get('rates', {}).get(to_currency)
        if rate is None:
            return jsonify({'error': f'No rate available for {from_currency} -> {to_currency}'}), 404
        return jsonify({
            'from': from_currency,
            'to': to_currency,
            'rate': rate,
            'date': data.get('date'),
            'source': 'frankfurter.app (European Central Bank)',
        })
    except requests.RequestException as e:
        print(f"Currency API error: {e}")
        return jsonify({'error': 'Currency service temporarily unavailable'}), 503

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