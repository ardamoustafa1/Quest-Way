from flask import Blueprint, request, jsonify, url_for
from datetime import datetime, timedelta
from models import db, Itinerary
from app import CRON_SECRET, send_email

cron_bp = Blueprint('cron', __name__)


@cron_bp.route('/internal/send-trip-reminders', methods=['POST'])
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
                f"Review your itinerary: {url_for('itinerary.itinerary_detail', itinerary_id=itinerary.id, _external=True)}",
            )
        itinerary.reminder_sent = True
        sent_count += 1

    db.session.commit()
    return jsonify({'itineraries_notified': sent_count})
