from flask import Blueprint, render_template, request, url_for, redirect, flash, jsonify
from flask_login import login_required, current_user
import json
from models import db, WishlistItem
from forms import WishlistForm
from app import limiter, groq_client, GROQ_MODEL

wishlist_bp = Blueprint('wishlist', __name__)


@wishlist_bp.route('/wishlist')
@login_required
def wishlist():
    items = WishlistItem.query.filter_by(user_id=current_user.id).order_by(WishlistItem.added_at.desc()).all()
    return render_template('user/wishlist.html', items=items)

@wishlist_bp.route('/add_to_wishlist', methods=['GET', 'POST'])
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
        return redirect(url_for('wishlist.wishlist'))
    
    return render_template('user/add_wishlist.html', form=form)

@wishlist_bp.route('/quick-add', methods=['GET', 'POST'])
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

@wishlist_bp.route('/quick-add/save', methods=['POST'])
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
    return redirect(url_for('wishlist.wishlist'))

@wishlist_bp.route('/remove_from_wishlist/<int:item_id>', methods=['POST'])
@login_required
def remove_from_wishlist(item_id):
    item = WishlistItem.query.filter_by(id=item_id, user_id=current_user.id).first()
    if item:
        db.session.delete(item)
        db.session.commit()
        flash('Removed from wishlist!', 'success')
    return redirect(url_for('wishlist.wishlist'))

@wishlist_bp.route('/api/add_to_wishlist', methods=['POST'])
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

@wishlist_bp.route('/api/remove_from_wishlist', methods=['POST'])
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
