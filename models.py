from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

# Create db instance here
db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(50), nullable=True)
    last_name = db.Column(db.String(50), nullable=True)
    profile_picture = db.Column(db.String(200), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    referral_code = db.Column(db.String(12), unique=True, nullable=True)
    referred_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    points = db.Column(db.Integer, default=0, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    referred_by = db.relationship('User', remote_side=[id])

    # Relationships
    reviews = db.relationship('Review', backref='author', lazy=True)
    wishlist_items = db.relationship('WishlistItem', backref='user', lazy=True)
    itineraries = db.relationship('Itinerary', backref='user', lazy=True)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def __repr__(self):
        return f'<User {self.username}>'

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    rating = db.Column(db.Integer, nullable=False)  # 1-5 stars
    country = db.Column(db.String(100), nullable=False)
    city = db.Column(db.String(100), nullable=True)
    place_name = db.Column(db.String(200), nullable=True)
    place_type = db.Column(db.String(50), nullable=True)  # hotel, restaurant, attraction, etc.
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Additional fields for enhanced reviews
    helpful_count = db.Column(db.Integer, default=0)
    images = db.Column(db.JSON, nullable=True)  # Store image URLs as JSON array
    verified_visit = db.Column(db.Boolean, default=False)
    # Erişilebilirlik alanları — hepsi tri-state (None = belirtilmedi)
    wheelchair_accessible = db.Column(db.Boolean, nullable=True)
    step_free_access = db.Column(db.Boolean, nullable=True)
    accessibility_notes = db.Column(db.String(300), nullable=True)
    
    # `author` is the single real relationship (declared on User.reviews below);
    # `user` is kept as an alias since templates reference both names.
    user = db.synonym('author')

    # pg_trgm GIN indexleri — fuzzy/typo-toleranslı arama için (bkz. app.py search_reviews_cached).
    # Modelde tanımlı olmaları, Flask-Migrate'in her `db migrate` çalıştırmasında
    # bunları 'kaldırılmış' sanıp silme migration'ı üretmesini engelliyor.
    __table_args__ = (
        db.Index('ix_review_title_trgm', 'title', postgresql_using='gin', postgresql_ops={'title': 'gin_trgm_ops'}),
        db.Index('ix_review_content_trgm', 'content', postgresql_using='gin', postgresql_ops={'content': 'gin_trgm_ops'}),
        db.Index('ix_review_place_name_trgm', 'place_name', postgresql_using='gin', postgresql_ops={'place_name': 'gin_trgm_ops'}),
    )

    def __repr__(self):
        return f'<Review {self.title}>'

class ReviewHelpfulVote(db.Model):
    """Kullanıcı başına en fazla bir 'helpful' oyu (unique constraint)."""
    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey('review.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    review = db.relationship('Review', backref=db.backref('helpful_votes', lazy=True, cascade='all, delete-orphan'))
    user = db.relationship('User')

    __table_args__ = (db.UniqueConstraint('review_id', 'user_id', name='uq_review_user_helpful_vote'),)

class WishlistItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    place_name = db.Column(db.String(200), nullable=False)
    place_type = db.Column(db.String(50), nullable=False)
    country = db.Column(db.String(100), nullable=False)
    city = db.Column(db.String(100), nullable=True)
    description = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<WishlistItem {self.place_name}>'

class Itinerary(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    country = db.Column(db.String(100), nullable=False)
    city = db.Column(db.String(100), nullable=True)
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    is_public = db.Column(db.Boolean, default=False)
    recap_text = db.Column(db.Text, nullable=True)  # AI tarafından üretilen paylaşılabilir 'gezi hikayesi'
    reminder_sent = db.Column(db.Boolean, default=False, nullable=False)  # 'gezine N gün kaldı' e-postası tekrar gitmesin diye
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Relationships
    itinerary_items = db.relationship('ItineraryItem', backref='itinerary', lazy=True, cascade='all, delete-orphan')
    collaborators = db.relationship('ItineraryCollaborator', backref='itinerary', lazy=True, cascade='all, delete-orphan')
    expenses = db.relationship('ItineraryExpense', backref='itinerary', lazy=True, cascade='all, delete-orphan')
    polls = db.relationship('ItineraryPoll', backref='itinerary', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Itinerary {self.title}>'

class ItineraryPoll(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    itinerary_id = db.Column(db.Integer, db.ForeignKey('itinerary.id'), nullable=False)
    question = db.Column(db.String(200), nullable=False)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    options = db.relationship('ItineraryPollOption', backref='poll', lazy=True, cascade='all, delete-orphan')

class ItineraryPollOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('itinerary_poll.id'), nullable=False)
    text = db.Column(db.String(200), nullable=False)

    votes = db.relationship('ItineraryPollVote', backref='option', lazy=True, cascade='all, delete-orphan')

class ItineraryPollVote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    option_id = db.Column(db.Integer, db.ForeignKey('itinerary_poll_option.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User')

class ItineraryExpense(db.Model):
    """Grup masrafı — eşit şekilde tüm katılımcılar (sahip + collaborator'lar)
    arasında bölüşülür. 'Kim kime borçlu' hesaplaması app.py'de yapılır."""
    id = db.Column(db.Integer, primary_key=True)
    itinerary_id = db.Column(db.Integer, db.ForeignKey('itinerary.id'), nullable=False)
    paid_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default='USD')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    paid_by = db.relationship('User')

class ItineraryCollaborator(db.Model):
    """Bir itinerary'yi sahibiyle birlikte görüntüleyebilen/düzenleyebilen kullanıcılar."""
    id = db.Column(db.Integer, primary_key=True)
    itinerary_id = db.Column(db.Integer, db.ForeignKey('itinerary.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    permission = db.Column(db.String(10), nullable=False, default='view')  # 'view' or 'edit'
    invited_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User')

    __table_args__ = (db.UniqueConstraint('itinerary_id', 'user_id', name='uq_itinerary_collaborator'),)

class ItineraryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    itinerary_id = db.Column(db.Integer, db.ForeignKey('itinerary.id'), nullable=False)
    day_number = db.Column(db.Integer, nullable=False)
    time_slot = db.Column(db.String(50), nullable=True)  # morning, afternoon, evening
    place_name = db.Column(db.String(200), nullable=False)
    place_type = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=True)
    address = db.Column(db.String(300), nullable=True)
    estimated_duration = db.Column(db.Integer, nullable=True)  # in minutes
    cost_estimate = db.Column(db.Float, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    order_index = db.Column(db.Integer, nullable=False)
    
    def __repr__(self):
        return f'<ItineraryItem {self.place_name}>'

class WeatherData(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    country = db.Column(db.String(100), nullable=False)
    city = db.Column(db.String(100), nullable=False)
    date = db.Column(db.Date, nullable=False)
    temperature_high = db.Column(db.Float, nullable=True)
    temperature_low = db.Column(db.Float, nullable=True)
    weather_condition = db.Column(db.String(100), nullable=True)
    humidity = db.Column(db.Float, nullable=True)
    wind_speed = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<WeatherData {self.city} - {self.date}>'

class CurrencyRate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    from_currency = db.Column(db.String(3), nullable=False)
    to_currency = db.Column(db.String(3), nullable=False)
    rate = db.Column(db.Float, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<CurrencyRate {self.from_currency} to {self.to_currency}>'

class ForumThread(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    country = db.Column(db.String(100), nullable=True)  # opsiyonel ülke etiketi
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    author = db.relationship('User')
    posts = db.relationship('ForumPost', backref='thread', lazy=True, cascade='all, delete-orphan',
                             order_by='ForumPost.created_at')

    def __repr__(self):
        return f'<ForumThread {self.title}>'

class ForumPost(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    thread_id = db.Column(db.Integer, db.ForeignKey('forum_thread.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship('User')

    def __repr__(self):
        return f'<ForumPost thread={self.thread_id}>'
