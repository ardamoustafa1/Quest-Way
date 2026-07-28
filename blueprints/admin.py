from flask import Blueprint, render_template, request, url_for, redirect, flash
from flask_login import current_user
from models import db, User, Review, ReviewHelpfulVote, Itinerary, ForumThread, ForumPost, AdminAuditLog
from app import admin_required

admin_bp = Blueprint('admin', __name__)


def log_admin_action(action, target_type, target_id, details=None):
    """Bir admin işlemini kalıcı olarak kaydeder (kim, ne zaman, ne yaptı).

    Silme işlemlerinde çağıran, hedef satır DB'den silinmeden ÖNCE bu
    fonksiyonu çağırmalı ki `details` içine anlamlı bir özet (başlık,
    kullanıcı adı vb.) yazılabilsin.
    """
    db.session.add(AdminAuditLog(
        admin_user_id=current_user.id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        details=details,
    ))


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
    recent_actions = AdminAuditLog.query.order_by(AdminAuditLog.created_at.desc()).limit(20).all()
    return render_template('admin/dashboard.html', stats=stats, recent_actions=recent_actions)

@admin_bp.route('/admin/reviews')
@admin_required
def admin_reviews():
    reviews = Review.query.order_by(Review.created_at.desc()).limit(200).all()
    return render_template('admin/reviews.html', reviews=reviews)

@admin_bp.route('/admin/reviews/<int:review_id>/delete', methods=['POST'])
@admin_required
def admin_delete_review(review_id):
    review = Review.query.get_or_404(review_id)
    log_admin_action('delete_review', 'review', review.id,
                      f'"{review.title}" by {review.author.username if review.author else "?"}')
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
    log_admin_action('delete_thread', 'forum_thread', thread.id, f'"{thread.title}"')
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
    log_admin_action('delete_post', 'forum_post', post.id,
                      f'in thread {thread_id} by {post.author.username if post.author else "?"}')
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
    log_admin_action('ban_user' if not user.is_active else 'unban_user', 'user', user.id, user.username)
    db.session.commit()
    flash(f"{user.username} is now {'active' if user.is_active else 'banned'}.", 'success')
    return redirect(url_for('admin.admin_users'))

@admin_bp.route('/admin/audit-log')
@admin_required
def admin_audit_log():
    entries = AdminAuditLog.query.order_by(AdminAuditLog.created_at.desc()).limit(500).all()
    return render_template('admin/audit_log.html', entries=entries)
