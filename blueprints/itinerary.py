from flask import Blueprint, render_template, request, url_for, redirect, flash, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timedelta
import json
from sqlalchemy import or_
from models import (
    db, Itinerary, ItineraryItem, ItineraryCollaborator, ItineraryExpense,
    ItineraryPoll, ItineraryPollOption, ItineraryPollVote, Review, User,
)
from forms import ItineraryForm, ItineraryItemForm, ItineraryExpenseForm, AIItineraryForm
from app import (
    limiter, groq_client, GROQ_MODEL, award_points, POINTS_CREATE_ITINERARY,
    generate_ai_itinerary, CHAT_SYSTEM_PROMPT, get_itinerary_permission,
    compute_itinerary_balances, find_travel_buddies, get_user_poll_votes,
    compute_eco_score, notify_itinerary_activity_added, fetch_forecast_range,
)

itinerary_bp = Blueprint('itinerary', __name__)


@itinerary_bp.route('/itineraries')
@login_required
def itineraries():
    owned = Itinerary.query.filter_by(user_id=current_user.id).order_by(Itinerary.created_at.desc()).all()
    shared_ids = [c.itinerary_id for c in ItineraryCollaborator.query.filter_by(user_id=current_user.id).all()]
    shared = Itinerary.query.filter(Itinerary.id.in_(shared_ids)).order_by(Itinerary.created_at.desc()).all() if shared_ids else []
    return render_template('user/itineraries.html', itineraries=owned, shared_itineraries=shared)

@itinerary_bp.route('/create_itinerary', methods=['GET', 'POST'])
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
        return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary.id))
    
    return render_template('user/create_itinerary.html', form=form)

@itinerary_bp.route('/ai-itinerary-planner', methods=['GET', 'POST'])
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

@itinerary_bp.route('/api/chat', methods=['POST'])
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

@itinerary_bp.route('/ai-itinerary-planner/save', methods=['POST'])
@login_required
def save_ai_itinerary():
    country = request.form.get('country')
    plan_json = request.form.get('plan_json')
    if not country or not plan_json:
        flash('Nothing to save.', 'error')
        return redirect(url_for('itinerary.ai_itinerary_planner'))

    try:
        plan = json.loads(plan_json)
    except (TypeError, ValueError):
        flash('Could not save that itinerary — the plan data was invalid.', 'error')
        return redirect(url_for('itinerary.ai_itinerary_planner'))

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
    return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary.id))

@itinerary_bp.route('/itinerary/<int:itinerary_id>')
@login_required
def itinerary_detail(itinerary_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    permission = get_itinerary_permission(itinerary, current_user)
    if permission is None:
        flash('You do not have permission to view this itinerary.', 'error')
        return redirect(url_for('itinerary.itineraries'))

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

@itinerary_bp.route('/itinerary/<int:itinerary_id>/polls', methods=['POST'])
@login_required
def create_itinerary_poll(itinerary_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    permission = get_itinerary_permission(itinerary, current_user)
    if permission not in ('owner', 'edit'):
        flash('You do not have permission to create polls on this itinerary.', 'error')
        return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary_id))

    question = request.form.get('question', '').strip()
    option_texts = [o.strip() for o in request.form.getlist('options') if o.strip()]
    if not question or len(option_texts) < 2:
        flash('A poll needs a question and at least 2 options.', 'error')
        return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary_id))

    poll = ItineraryPoll(itinerary_id=itinerary_id, question=question, created_by_user_id=current_user.id)
    db.session.add(poll)
    db.session.flush()
    for text in option_texts[:8]:
        db.session.add(ItineraryPollOption(poll_id=poll.id, text=text))
    db.session.commit()
    flash('Poll created!', 'success')
    return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary_id))

@itinerary_bp.route('/polls/<int:poll_id>/vote', methods=['POST'])
@login_required
def vote_itinerary_poll(poll_id):
    poll = ItineraryPoll.query.get_or_404(poll_id)
    permission = get_itinerary_permission(poll.itinerary, current_user)
    if permission is None:
        flash('You do not have permission to vote on this poll.', 'error')
        return redirect(url_for('itinerary.itineraries'))

    option_id = request.form.get('option_id', type=int)
    option = ItineraryPollOption.query.filter_by(id=option_id, poll_id=poll_id).first()
    if not option:
        flash('Invalid poll option.', 'error')
        return redirect(url_for('itinerary.itinerary_detail', itinerary_id=poll.itinerary_id))

    # Bu kullanıcının bu anketteki önceki oyunu sil (tek oy hakkı / oy değiştirme)
    option_ids = [o.id for o in poll.options]
    ItineraryPollVote.query.filter(
        ItineraryPollVote.option_id.in_(option_ids), ItineraryPollVote.user_id == current_user.id
    ).delete(synchronize_session=False)
    db.session.add(ItineraryPollVote(option_id=option_id, user_id=current_user.id))
    db.session.commit()
    flash('Vote recorded!', 'success')
    return redirect(url_for('itinerary.itinerary_detail', itinerary_id=poll.itinerary_id))

@itinerary_bp.route('/itinerary/<int:itinerary_id>/generate-recap', methods=['POST'])
@limiter.limit("10/hour")
@login_required
def generate_trip_recap(itinerary_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    if itinerary.user_id != current_user.id:
        flash('Only the trip owner can generate a trip recap.', 'error')
        return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary_id))

    if not groq_client:
        flash('Trip recap is not configured (missing GROQ_API_KEY).', 'error')
        return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary_id))

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

    return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary_id))

@itinerary_bp.route('/itinerary/<int:itinerary_id>/recap')
def view_trip_recap(itinerary_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    permission = get_itinerary_permission(itinerary, current_user)
    if permission is None:
        flash('You do not have permission to view this trip recap.', 'error')
        return redirect(url_for('itinerary.itineraries'))
    if not itinerary.recap_text:
        flash('This trip does not have a recap yet.', 'info')
        return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary_id))

    photos = []
    for r in Review.query.filter_by(user_id=itinerary.user_id, country=itinerary.country).all():
        if r.images:
            photos.extend(r.images[:2])
    return render_template('user/trip_recap.html', itinerary=itinerary, photos=photos[:8])

@itinerary_bp.route('/itinerary/<int:itinerary_id>/expenses', methods=['POST'])
@login_required
def add_itinerary_expense(itinerary_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    permission = get_itinerary_permission(itinerary, current_user)
    if permission not in ('owner', 'edit'):
        flash('You do not have permission to add expenses to this itinerary.', 'error')
        return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary_id))

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
    return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary_id))

@itinerary_bp.route('/itinerary/<int:itinerary_id>/packing-list', methods=['POST'])
@limiter.limit("10/hour")
@login_required
def generate_packing_list(itinerary_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    permission = get_itinerary_permission(itinerary, current_user)
    if permission is None:
        flash('You do not have permission to view this itinerary.', 'error')
        return redirect(url_for('itinerary.itineraries'))

    if not groq_client:
        flash('AI packing list is not configured (missing GROQ_API_KEY).', 'error')
        return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary_id))

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
        return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary_id))

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

@itinerary_bp.route('/itinerary/<int:itinerary_id>/eco-score', methods=['POST'])
@limiter.limit("10/hour")
@login_required
def generate_eco_score(itinerary_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    permission = get_itinerary_permission(itinerary, current_user)
    if permission is None:
        flash('You do not have permission to view this itinerary.', 'error')
        return redirect(url_for('itinerary.itineraries'))

    items = ItineraryItem.query.filter_by(itinerary_id=itinerary_id).order_by(ItineraryItem.day_number, ItineraryItem.order_index).all()
    eco_score = compute_eco_score(itinerary, items)
    if eco_score is None:
        flash('Add some activities to your itinerary first so we can estimate an eco-score.', 'info')
        return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary_id))

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

@itinerary_bp.route('/itinerary/<int:itinerary_id>/items', methods=['POST'])
@login_required
def add_itinerary_item(itinerary_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    permission = get_itinerary_permission(itinerary, current_user)
    if permission not in ('owner', 'edit'):
        flash('You do not have permission to edit this itinerary.', 'error')
        return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary_id))

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
    return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary_id))

@itinerary_bp.route('/itinerary/<int:itinerary_id>/share', methods=['POST'])
@login_required
def share_itinerary(itinerary_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    if itinerary.user_id != current_user.id:
        flash('Only the owner can share this itinerary.', 'error')
        return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary_id))

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

    return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary_id))

@itinerary_bp.route('/itinerary/<int:itinerary_id>/collaborators/<int:collaborator_id>/remove', methods=['POST'])
@login_required
def remove_collaborator(itinerary_id, collaborator_id):
    itinerary = Itinerary.query.get_or_404(itinerary_id)
    if itinerary.user_id != current_user.id:
        flash('Only the owner can manage collaborators.', 'error')
        return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary_id))

    collab = ItineraryCollaborator.query.filter_by(id=collaborator_id, itinerary_id=itinerary_id).first()
    if collab:
        db.session.delete(collab)
        db.session.commit()
        flash('Collaborator removed.', 'success')
    return redirect(url_for('itinerary.itinerary_detail', itinerary_id=itinerary_id))
