from flask import Blueprint, render_template, request, url_for, redirect, flash
from flask_login import login_required, current_user
from models import db, Review
from forms import ReviewForm
from app import award_points, POINTS_ADD_REVIEW, POINTS_REVIEW_WITH_PHOTO_BONUS, encode_review_images, tri_state_bool

review_bp = Blueprint('review', __name__)


@review_bp.route('/add_review', methods=['GET', 'POST'])
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
        return redirect(url_for('main.reviews'))

    return render_template('reviews/add_review.html', form=form)
