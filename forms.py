from flask_wtf import FlaskForm
from country_catalog import country_choices
from flask_wtf.file import MultipleFileField, FileAllowed, FileSize
from wtforms import StringField, TextAreaField, PasswordField, SubmitField, SelectField, SelectMultipleField, IntegerField, FloatField, DateField, BooleanField
from wtforms.validators import DataRequired, Email, Length, EqualTo, NumberRange, Optional
from wtforms.widgets import TextArea

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=20)])
    password = PasswordField('Password', validators=[DataRequired()])
    remember_me = BooleanField('Remember Me')
    submit = SubmitField('Sign In')

class RegisterForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=20)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    first_name = StringField('First Name', validators=[Length(max=50)])
    last_name = StringField('Last Name', validators=[Length(max=50)])
    password = PasswordField('Password', validators=[
        DataRequired(), 
        Length(min=6, message='Password must be at least 6 characters long')
    ])
    password2 = PasswordField('Confirm Password', validators=[
        DataRequired(), 
        EqualTo('password', message='Passwords must match')
    ])
    submit = SubmitField('Register')

class ForgotPasswordForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Send Reset Link')

class ResetPasswordForm(FlaskForm):
    password = PasswordField('New Password', validators=[
        DataRequired(),
        Length(min=6, message='Password must be at least 6 characters long')
    ])
    password2 = PasswordField('Confirm New Password', validators=[
        DataRequired(),
        EqualTo('password', message='Passwords must match')
    ])
    submit = SubmitField('Reset Password')

class ReviewForm(FlaskForm):
    title = StringField('Review Title', validators=[DataRequired(), Length(max=200)],
                       render_kw={"placeholder": "Give your review a title"})
    content = TextAreaField('Your Review', validators=[DataRequired()],
                          widget=TextArea(), render_kw={"rows": 6, "placeholder": "Share your experience in detail..."})
    rating = IntegerField('Rating', validators=[DataRequired(), NumberRange(min=1, max=5)])
    country = SelectField('Country', choices=country_choices('Select a country'), validators=[DataRequired()])
    # Options are populated client-side by JS based on the chosen country
    # (see add_review.html), so the server can't know the valid choice set
    # up front — validate_choice=False stops WTForms from rejecting every
    # real submission against this static placeholder list.
    place_name = SelectField('Name', choices=[('', 'Select a place')], validators=[DataRequired()], validate_choice=False)
    city = StringField('City', validators=[Optional(), Length(max=100)],
                      render_kw={"placeholder": "City (optional)"})
    place_type = SelectField('Type', choices=[
        ('famous_places', 'Famous Places'),
        ('top_hotels', 'Top Hotels'),
        ('top_restaurants', 'Top Restaurants'),
        ('famous_dishes', 'Famous Dishes'),
        ('transport', 'Transport')
    ], validators=[DataRequired()])
    verified_visit = BooleanField('I actually visited this place')
    wheelchair_accessible = SelectField('Wheelchair accessible?', choices=[
        ('', "Don't know / not applicable"), ('yes', 'Yes'), ('no', 'No'),
    ], validators=[Optional()])
    step_free_access = SelectField('Step-free access?', choices=[
        ('', "Don't know / not applicable"), ('yes', 'Yes'), ('no', 'No'),
    ], validators=[Optional()])
    accessibility_notes = StringField('Accessibility notes (optional)', validators=[Optional(), Length(max=300)],
                                     render_kw={"placeholder": "e.g. 'Ramp at side entrance, accessible restroom on ground floor'"})
    images = MultipleFileField('Photos (optional, up to 3)', validators=[
        Optional(),
        FileAllowed(['jpg', 'jpeg', 'png', 'webp'], 'Only JPG, PNG or WEBP images allowed.'),
        FileSize(max_size=3 * 1024 * 1024, message='Each photo must be under 3MB.'),
    ])
    submit = SubmitField('Submit Review')

class WishlistForm(FlaskForm):
    place_name = StringField('Place Name', validators=[DataRequired(), Length(max=200)])
    place_type = SelectField('Place Type', choices=[
        ('hotel', 'Hotel'),
        ('restaurant', 'Restaurant'),
        ('attraction', 'Tourist Attraction'),
        ('transport', 'Transportation'),
        ('shopping', 'Shopping'),
        ('other', 'Other')
    ], validators=[DataRequired()])
    country = StringField('Country', validators=[DataRequired()])
    city = StringField('City', validators=[Optional()])
    description = TextAreaField('Description', validators=[Optional()], 
                              widget=TextArea(), render_kw={"rows": 3})
    submit = SubmitField('Add to Wishlist')

class ItineraryForm(FlaskForm):
    title = StringField('Trip Title', validators=[DataRequired(), Length(max=200)])
    description = TextAreaField('Description', validators=[Optional()], 
                              widget=TextArea(), render_kw={"rows": 3})
    country = StringField('Country', validators=[DataRequired()])
    city = StringField('City', validators=[Optional()])
    start_date = DateField('Start Date', validators=[Optional()])
    end_date = DateField('End Date', validators=[Optional()])
    is_public = BooleanField('Make this itinerary public')
    submit = SubmitField('Create Itinerary')

class ItineraryItemForm(FlaskForm):
    day_number = IntegerField('Day Number', validators=[DataRequired(), NumberRange(min=1)])
    time_slot = SelectField('Time Slot', choices=[
        ('morning', 'Morning (6AM-12PM)'),
        ('afternoon', 'Afternoon (12PM-6PM)'),
        ('evening', 'Evening (6PM-12AM)'),
        ('night', 'Night (12AM-6AM)')
    ], validators=[Optional()])
    place_name = StringField('Place Name', validators=[DataRequired(), Length(max=200)])
    place_type = SelectField('Place Type', choices=[
        ('hotel', 'Hotel'),
        ('restaurant', 'Restaurant'),
        ('attraction', 'Tourist Attraction'),
        ('transport', 'Transportation'),
        ('shopping', 'Shopping'),
        ('other', 'Other')
    ], validators=[DataRequired()])
    description = TextAreaField('Description', validators=[Optional()], 
                              widget=TextArea(), render_kw={"rows": 2})
    address = StringField('Address', validators=[Optional(), Length(max=300)])
    estimated_duration = IntegerField('Duration (minutes)', validators=[Optional(), NumberRange(min=1)])
    cost_estimate = StringField('Estimated Cost', validators=[Optional()])
    notes = TextAreaField('Notes', validators=[Optional()], 
                        widget=TextArea(), render_kw={"rows": 2})
    submit = SubmitField('Add Item')

class ForumThreadForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(max=200)],
                       render_kw={"placeholder": "What's your question or topic?"})
    country = SelectField('Related country (optional)', choices=country_choices('General / not country-specific'), validators=[Optional()])
    content = TextAreaField('Message', validators=[DataRequired(), Length(max=4000)],
                           widget=TextArea(), render_kw={"rows": 5, "placeholder": "Share details, ask your question..."})
    submit = SubmitField('Start Discussion')

class ForumReplyForm(FlaskForm):
    content = TextAreaField('Reply', validators=[DataRequired(), Length(max=4000)],
                           widget=TextArea(), render_kw={"rows": 3, "placeholder": "Write a reply..."})
    submit = SubmitField('Post Reply')

class AIItineraryForm(FlaskForm):
    country = SelectField('Country', choices=country_choices(), validators=[DataRequired()])
    days = IntegerField('Number of days', validators=[DataRequired(), NumberRange(min=1, max=14, message='Between 1 and 14 days.')], default=3)
    budget_level = SelectField('Budget', choices=[
        ('budget', 'Budget-friendly'), ('mid', 'Mid-range'), ('luxury', 'Luxury'),
    ], default='mid')
    interests = SelectMultipleField('Interests', choices=[
        ('history', 'History & Culture'), ('food', 'Food & Dining'), ('nature', 'Nature & Outdoors'),
        ('nightlife', 'Nightlife'), ('shopping', 'Shopping'), ('relaxation', 'Relaxation'),
    ])
    submit = SubmitField('Generate Itinerary')

class ItineraryExpenseForm(FlaskForm):
    description = StringField('What was it for?', validators=[DataRequired(), Length(max=200)])
    amount = FloatField('Amount', validators=[DataRequired(), NumberRange(min=0.01, message='Amount must be greater than 0.')])
    currency = SelectField('Currency', choices=[
        ('USD', 'USD'), ('EUR', 'EUR'), ('TRY', 'TRY'), ('GBP', 'GBP'),
    ], default='USD')
    submit = SubmitField('Add Expense')

class SearchForm(FlaskForm):
    query = StringField('Search', validators=[Optional()])
    country = SelectField('Country', choices=country_choices('All Countries'), validators=[Optional()])
    place_type = SelectField('Place Type', choices=[
        ('', 'All Types'),
        ('famous_places', 'Famous Places'),
        ('top_hotels', 'Top Hotels'),
        ('top_restaurants', 'Top Restaurants'),
        ('famous_dishes', 'Famous Dishes'),
        ('transport', 'Transport')
    ], validators=[Optional()])
    rating_min = SelectField('Minimum Rating', choices=[
        (0, 'Any Rating'),
        (1, '1+ Stars'),
        (2, '2+ Stars'),
        (3, '3+ Stars'),
        (4, '4+ Stars'),
        (5, '5 Stars Only')
    ], validators=[Optional()], coerce=int, default=0)
    submit = SubmitField('Search')

class ContactForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    subject = StringField('Subject', validators=[DataRequired(), Length(max=200)])
    message = TextAreaField('Message', validators=[DataRequired()], 
                          widget=TextArea(), render_kw={"rows": 5})
    submit = SubmitField('Send Message')
