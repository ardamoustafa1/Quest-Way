from flask import Blueprint, render_template, request, url_for, redirect, flash
from flask_login import current_user
from models import db, User, Review, ReviewHelpfulVote, Itinerary, ForumThread, ForumPost
from app import admin_required

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/admin')
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

@admin_bp.route('/admin/reviews')
@admin_required
def admin_reviews():
    reviews = Review.query.order_by(Review.created_at.desc()).limit(200).all()
    return render_template('admin/reviews.html', reviews=reviews)

@admin_bp.route('/admin/reviews/<int:review_id>/delete', methods=['POST'])
@admin_required
def admin_delete_review(review_id):
    review = Review.query.get_or_404(review_id)
    ReviewHelpfulVote.query.filter_by(review_id=review_id).delete()
    db.session.delete(review)
    db.session.commit()
    flash('Review deleted.', 'success')
    return redirect(url_for('admin.admin_reviews'))

@admin_bp.route('/admin/forum')
@admin_required
def admin_forum():
    threads = ForumThread.query.order_by(ForumThread.updated_at.desc()).limit(200).all()
    return render_template('admin/forum.html', threads=threads)

@admin_bp.route('/admin/forum/<int:thread_id>/delete', methods=['POST'])
@admin_required
def admin_delete_thread(thread_id):
    thread = ForumThread.query.get_or_404(thread_id)
    ForumPost.query.filter_by(thread_id=thread_id).delete()
    db.session.delete(thread)
    db.session.commit()
    flash('Thread deleted.', 'success')
    return redirect(url_for('admin.admin_forum'))

@admin_bp.route('/admin/forum/post/<int:post_id>/delete', methods=['POST'])
@admin_required
def admin_delete_post(post_id):
    post = ForumPost.query.get_or_404(post_id)
    thread_id = post.thread_id
    db.session.delete(post)
    db.session.commit()
    flash('Post deleted.', 'success')
    return redirect(url_for('admin.admin_forum'))

@admin_bp.route('/admin/users')
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).limit(200).all()
    return render_template('admin/users.html', users=users)

@admin_bp.route('/admin/users/<int:user_id>/toggle-active', methods=['POST'])
@admin_required
def admin_toggle_user_active(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot deactivate your own account.', 'error')
        return redirect(url_for('admin.admin_users'))
    user.is_active = not user.is_active
    db.session.commit()
    flash(f"{user.username} is now {'active' if user.is_active else 'banned'}.", 'success')
    return redirect(url_for('admin.admin_users'))
