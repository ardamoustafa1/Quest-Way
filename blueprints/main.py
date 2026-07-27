from flask import Blueprint, render_template, request, url_for, redirect, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from models import db, Review, ReviewHelpfulVote, User, Itinerary, ForumThread
from travel_data import data
from app import (
    cache, calculate_review_stats_cached, create_sample_reviews, award_points,
    POINTS_HELPFUL_VOTE_RECEIVED, geocode_place, search_reviews_cached,
)
from forms import SearchForm

main_bp = Blueprint('main', __name__)


@main_bp.route('/explore')
def explore():
    country_filter = request.args.get('country', '')
    query = Review.query.filter(Review.images.isnot(None))
    if country_filter:
        query = query.filter(Review.country == country_filter)
    photo_reviews = query.order_by(Review.created_at.desc()).limit(60).all()
    return render_template('explore.html', reviews=photo_reviews, country_filter=country_filter)

@main_bp.route('/reviews')
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

@main_bp.route('/review/<int:review_id>/helpful', methods=['POST'])
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

@main_bp.route('/delete_comment/<int:comment_id>', methods=['POST'])
@login_required
def delete_comment(comment_id):
    review = Review.query.filter_by(id=comment_id, user_id=current_user.id).first()
    if review:
        db.session.delete(review)
        db.session.commit()
        flash('Review deleted.', 'success')
    return redirect(url_for('main.reviews'))

@main_bp.route('/ads.txt')
def ads_txt():
    try:
        with open('ads.txt', 'r', encoding='utf-8') as f:
            content = f.read()
        return content, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except FileNotFoundError:
        return 'google.com, pub-9221145906123169, DIRECT, f08c47fec0942fa0', 200, {'Content-Type': 'text/plain; charset=utf-8'}

@main_bp.route('/robots.txt')
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
        f"Sitemap: {url_for('main.sitemap_xml', _external=True)}",
    ]
    return '\n'.join(lines), 200, {'Content-Type': 'text/plain; charset=utf-8'}

@main_bp.route('/sitemap.xml')
@cache.cached(timeout=3600)
def sitemap_xml():
    urls = []
    now = datetime.utcnow().strftime('%Y-%m-%d')

    static_pages = ['main.index', 'main.reviews', 'main.explore', 'forum.forum_index', 'main.search', 'auth.login', 'auth.register']
    for endpoint in static_pages:
        urls.append({'loc': url_for(endpoint, _external=True), 'lastmod': now, 'priority': '0.8'})

    for country in data.keys():
        for section in data[country].keys():
            urls.append({
                'loc': url_for('main.details', country_name=country, section=section, _external=True),
                'lastmod': now, 'priority': '0.7',
            })

    for itinerary in Itinerary.query.filter_by(is_public=True).all():
        urls.append({
            'loc': url_for('itinerary.itinerary_detail', itinerary_id=itinerary.id, _external=True),
            'lastmod': itinerary.updated_at.strftime('%Y-%m-%d') if itinerary.updated_at else now,
            'priority': '0.5',
        })
        if itinerary.recap_text:
            urls.append({
                'loc': url_for('itinerary.view_trip_recap', itinerary_id=itinerary.id, _external=True),
                'lastmod': itinerary.updated_at.strftime('%Y-%m-%d') if itinerary.updated_at else now,
                'priority': '0.6',
            })

    for thread in ForumThread.query.all():
        urls.append({
            'loc': url_for('forum.forum_thread', thread_id=thread.id, _external=True),
            'lastmod': thread.updated_at.strftime('%Y-%m-%d') if thread.updated_at else now,
            'priority': '0.4',
        })

    xml_parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        xml_parts.append(f"<url><loc>{u['loc']}</loc><lastmod>{u['lastmod']}</lastmod><priority>{u['priority']}</priority></url>")
    xml_parts.append('</urlset>')

    return '\n'.join(xml_parts), 200, {'Content-Type': 'application/xml; charset=utf-8'}

@main_bp.route('/')
def index():
    countries = data.keys()  # 'data' sözlüğünden tüm ülke isimlerini alır
    return render_template('index.html', countries=countries)

@main_bp.route('/country', methods=['GET', 'POST'])
def country():
    if request.method == 'POST':
        selected_country = request.form.get('country')  # Seçilen ülkeyi al
    else:
        selected_country = request.args.get('country')  # GET request'ten ülkeyi al
    
    if not selected_country:
        return redirect(url_for('main.index'))
    
    return render_template('country.html', country=selected_country)

@main_bp.route('/details/<country_name>/<section>')
def details(country_name, section):
    if country_name not in data:
        return f"Error: Country '{country_name}' not found", 404

    section_key = section.replace(" ", "_").lower()
    if section_key not in data[country_name]:
        return f"Error: Section '{section}' not found for country '{country_name}'", 404

    content = data[country_name][section_key]  # İçerik alınır
    return render_template('details.html', country=country_name, section=section, content=content)

@main_bp.route('/api/location')
def api_location():
    place = request.args.get('place', '')
    country = request.args.get('country', '')
    if not place and not country:
        return jsonify({'error': 'place or country query param required'}), 400
    location = geocode_place(place, country)
    if not location:
        return jsonify({'error': 'Location not found'}), 404
    return jsonify(location)

@main_bp.route('/search', methods=['GET', 'POST'])
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
