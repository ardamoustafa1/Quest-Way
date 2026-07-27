from flask import Blueprint, render_template, request, url_for, redirect, flash
from flask_login import login_required, current_user
from datetime import datetime
from models import db, ForumThread, ForumPost
from forms import ForumThreadForm, ForumReplyForm
from app import award_points, POINTS_FORUM_THREAD, POINTS_FORUM_REPLY

forum_bp = Blueprint('forum', __name__)


@forum_bp.route('/forum')
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

@forum_bp.route('/forum/new', methods=['GET', 'POST'])
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
        return redirect(url_for('forum.forum_thread', thread_id=thread.id))

    return render_template('forum/new_thread.html', form=form)

@forum_bp.route('/forum/<int:thread_id>', methods=['GET', 'POST'])
def forum_thread(thread_id):
    thread = ForumThread.query.get_or_404(thread_id)
    reply_form = ForumReplyForm()

    if reply_form.validate_on_submit():
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login', next=request.path))
        db.session.add(ForumPost(thread_id=thread.id, user_id=current_user.id, content=reply_form.content.data))
        thread.updated_at = datetime.utcnow()
        award_points(current_user, POINTS_FORUM_REPLY)
        db.session.commit()
        flash('Reply posted!', 'success')
        return redirect(url_for('forum.forum_thread', thread_id=thread.id))

    return render_template('forum/thread_detail.html', thread=thread, reply_form=reply_form)
