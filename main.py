import os
from flask import (
    Flask, jsonify, request, render_template, redirect, url_for, flash
)
from flask_httpauth import HTTPBasicAuth
from datetime import datetime
from uuid import uuid4
from datetime import datetime
from dotenv import load_dotenv
from forms import NewDealForm
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.engine.url import URL
from sqlalchemy import text, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects.postgresql import UUID
import logging
import uuid
from sqlalchemy.dialects.postgresql import UUID


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
# You can override these by setting FLASK_USER and FLASK_PASSWORD in your env
USERS = {
    os.getenv("FLASK_USER", "JasonT"): os.getenv("FLASK_PASSWORD", "Akbar2120!")
}

app = Flask(__name__)
auth = HTTPBasicAuth()
# Option A: pull from an environment variable (recommended)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "you-should-override-in-prod")
# Option B: hard-code for local/dev (make sure to override in production!)
if not app.config['SECRET_KEY']:
    app.config['SECRET_KEY'] = 'changeme-to-a-random-32-byte-string'

# -----------------------------------------------------------------------------
# Database Configuration
# -----------------------------------------------------------------------------
DB_USER = os.getenv('DB_USER', 'verideal_user')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'Verideal123!!')
DB_NAME = os.getenv('DB_NAME', 'verideal')
DB_HOST = os.getenv('DB_HOST', 'host.docker.internal')  # Use host.docker.internal to reach host machine from Docker
DB_PORT = os.getenv('DB_PORT', '5432')

url = URL.create(
    drivername="postgresql+psycopg2",
    username=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=int(DB_PORT),
    database=DB_NAME,
)

app.config['SQLALCHEMY_DATABASE_URI'] = str(url)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)


# Test database connectivity on startup
app.app_context()
def test_db_connection():
    try:
        # Correct way to execute raw SQL
        db.session.execute(text('SELECT 1'))
        app.logger.info("Database connection successful.")
    except Exception as e:
        app.logger.error(f"Database connection failed: {e}")

# with app.app_context():
#     db.create_all()


class Deal(db.Model):
    __tablename__ = "deals"

    id = db.Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False
    )
    customer_email    = db.Column(db.String(255), nullable=False)
    customer_website  = db.Column(db.String(255), nullable=False)
    deal_value        = db.Column(db.Numeric(12, 2), nullable=False)
    arr               = db.Column(db.Numeric(12, 2), nullable=False)
    product_sold      = db.Column(db.String(255), nullable=False)
    description       = db.Column(db.Text, nullable=False)
    deal_cycle_length = db.Column(db.Integer, nullable=False)
    rate_me           = db.Column(db.Integer, nullable=False)
    sales_agent       = db.Column(db.String(50), nullable=False)
    verified_by    = db.Column(db.String(50), nullable=True)  # sales agent who verified the deal
    verified      = db.Column(db.Boolean, default=False, nullable=False)
    verified_at   = db.Column(db.DateTime(timezone=True), nullable=True)  # timestamp of verification
    display_verified_at = db.Column(db.Boolean, default=False, nullable=False)  # whether to display the verified_at timestamp
    display_verified_by = db.Column(db.Boolean, default=False, nullable=False)  # whether to display the verified_by field
    closed            = db.Column(db.Boolean, default=False, nullable=False)
    created_at        = db.Column(db.DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at        = db.Column(
                           db.DateTime(timezone=True),
                           server_default=func.now(),
                           onupdate=func.now(),
                           nullable=False
                        )


# -----------------------------------------------------------------------------
# App & Auth setup
# -----------------------------------------------------------------------------


@auth.verify_password
def verify_password(username, password):
    """Flask-HTTPAuth callback to check credentials."""
    if USERS.get(username) == password:
        return username  # this becomes auth.current_user()
    return None


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.route("/")
@auth.login_required
def index():
    """Protected root route."""
    user = auth.current_user()
    return render_template("index.html", user=user)

@app.route("/api")
@auth.login_required
def api():
    """Protected API route."""
    user = auth.current_user()
    return jsonify({
        "message": f"Hello, {user}! This is your WebApp’s API endpoint."
    })

@app.route("/deals")
@auth.login_required
def deals():
    """Protected deals  route."""
    user = auth.current_user()
    # Simulate a deals list
    deals = Deal.query.filter_by(sales_agent=user).all()
    if not deals:
        flash("No deals found for you.", "info")
        return render_template("deals.html", user=user, deals=[])
    return render_template("deals.html", user=user, deals=deals)

# Now I need a route to add a new deal
# These are the attributes I want to add:
#  id                   SERIAL PRIMARY KEY,
#   customer_email       VARCHAR(255)    NOT NULL,
#   customer_website     VARCHAR(255),
#   deal_value           NUMERIC(12,2)   NOT NULL,  -- dollars and cents
#   arr                  NUMERIC(12,2),             -- annual recurring revenue
#   product_sold         VARCHAR(255),
#   description          TEXT,
#   deal_cycle_length    INTEGER,                  -- in days (or months—your choice)
#   rate_me              SMALLINT   NOT NULL CHECK (rate_me BETWEEN 1 AND 10)
#   created_at           TIMESTAMP DEFAULT NOW(),
#   updated_at           TIMESTAMP DEFAULT NOW()
#   closed_at           TIMESTAMP DEFAULT NOW(),
#   closed              BOOLEAN DEFAULT FALSE,
@app.route("/new_deal", methods=["GET", "POST"])
@auth.login_required
def new_deal():
    user = auth.current_user()
    form = NewDealForm()

    # DEBUG: print out what’s happening
    if request.method == "POST":
        app.logger.debug("POST to /new_deal; form data: %s", request.form)
        app.logger.debug("form.validate(): %s", form.validate())
        app.logger.debug("form.errors: %s", form.errors)

    if form.validate_on_submit():  
        # at this point, request.method == POST & form.validate() is True
        deal = Deal(
            id=uuid4(),
            customer_email   = form.customer_email.data,
            customer_website = form.customer_website.data,
            deal_value       = form.deal_value.data,
            arr              = form.arr.data,
            product_sold     = form.product_sold.data,
            description      = form.description.data,
            deal_cycle_length= form.deal_cycle_length.data,
            rate_me          = form.rate_me.data,
            sales_agent      = user,
            verified_by      = "",
            verified_at      = datetime.utcnow(),
            verified         = False,
            display_verified_at = False,
            display_verified_by = False,
            created_at       = datetime.utcnow(),
            updated_at       = datetime.utcnow(), 
            closed           = False
        )
        try:
            db.session.add(deal)
            db.session.commit()
            flash("Deal created successfully!", "success")
            return redirect(url_for("deals"))  # make sure you have a `@app.route("/deals")` 
        except SQLAlchemyError as exc:
            db.session.rollback()
            app.logger.exception(exc)
            flash(f"Could not save deal: {exc}", "danger")

    # Either GET or POST-with-errors → re-render the form
    return render_template("new_deal.html", form=form, user=user)


@app.route("/deals/<int:deal_id>/delete", methods=["POST"])
@auth.login_required
def delete_deal(deal_id):
    """Protected route to delete a deal."""
    # Simulate deal deletion
    # Redirect to the deals page after deleting a deal
    return redirect(url_for("deals"))


@app.route("/deals/<string:deal_id>/edit", methods=["GET", "POST"])
@auth.login_required
def edit_deal(deal_id):
    user = auth.current_user()

    # Convert the path component to a Python UUID (404 if invalid)
    try:
        uuid_obj = uuid.UUID(deal_id)
    except ValueError:
        abort(404)

    # Load the existing Deal (404 if not found)
    deal = Deal.query.get_or_404(uuid_obj)

    # Preload the form with existing values
    form = NewDealForm(obj=deal)

    if form.validate_on_submit():
        # Copy changes back into “deal”
        form.populate_obj(deal)
        # (you can update “closed” or other fields here if needed)

        try:
            db.session.commit()
            flash("Deal updated successfully!", "success")
            return redirect(url_for("deals"))
        except SQLAlchemyError as exc:
            db.session.rollback()
            app.logger.exception(exc)
            flash(f"Could not update deal: {exc}", "danger")

    return render_template("edit_deal.html", form=form, user=user, deal=deal)

@app.route("/deals/<int:deal_id>")
@auth.login_required
def deal_detail(deal_id):
    """Protected deal detail route."""
    user = auth.current_user()
    # Simulate a deal detail
    deal = {
        "id": deal_id,
        "title": f"Deal {deal_id}",
        "description": f"Description for Deal {deal_id}",
        "price": 100 + deal_id * 10,
        "discount": 10 + deal_id,
    }
    # Render the deal detail page
    return render_template("deal_detail.html", user=user, deal=deal)

# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # Debug mode on; listens on localhost:5000 by default
    app.run(debug=True, host="0.0.0.0", port=5000)
