from flask_wtf import FlaskForm
from wtforms import StringField, DecimalField, TextAreaField, IntegerField, SelectField, SubmitField
from wtforms.validators import DataRequired, Email, URL, NumberRange

from flask_wtf import FlaskForm
from wtforms import StringField, DecimalField, IntegerField, TextAreaField, SubmitField
from wtforms.validators import DataRequired, Email, NumberRange

class NewDealForm(FlaskForm):
    customer_email    = StringField("Customer Email", validators=[DataRequired(), Email()])
    customer_website  = StringField("Customer Website", validators=[DataRequired()])
    deal_value        = DecimalField("Deal Value (USD)", validators=[DataRequired(), NumberRange(min=0)])
    arr               = DecimalField("ARR (USD)", validators=[DataRequired(), NumberRange(min=0)])
    product_sold      = StringField("Product Sold", validators=[DataRequired()])
    description       = TextAreaField("Description", validators=[DataRequired()])
    deal_cycle_length = IntegerField("Deal Cycle Length (days)", validators=[DataRequired(), NumberRange(min=0)])
    rate_me           = IntegerField("Your Rating (1–10)", validators=[DataRequired(), NumberRange(min=1, max=10)])
    submit            = SubmitField("Create Deal")

class EditDealForm(FlaskForm):
    customer_email    = StringField("Customer Email", validators=[DataRequired(), Email()])
    customer_website  = StringField("Customer Website", validators=[DataRequired()])
    deal_value        = DecimalField("Deal Value (USD)", validators=[DataRequired(), NumberRange(min=0)])
    arr               = DecimalField("ARR (USD)", validators=[DataRequired(), NumberRange(min=0)])
    product_sold      = StringField("Product Sold", validators=[DataRequired()])
    description       = TextAreaField("Description", validators=[DataRequired()])
    deal_cycle_length = IntegerField("Deal Cycle Length (days)", validators=[DataRequired(), NumberRange(min=0)])
    rate_me           = IntegerField("Your Rating (1–10)", validators=[DataRequired(), NumberRange(min=1, max=10)])
    submit            = SubmitField("Update Deal")

class DeleteDealForm(FlaskForm):
    confirm_delete = StringField("Type 'DELETE' to confirm", validators=[DataRequired()])
    submit         = SubmitField("Delete Deal")