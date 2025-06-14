import os
from flask import Flask, jsonify, request, render_template, redirect, flash
from datetime import datetime
import dotenv
import boto3
import uuid
# Load environment variables from .env file
dotenv.load_dotenv()
    
app = Flask(__name__)

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default_secret_key')

## routes
@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
def submit():
    first = request.form['first_name']
    last  = request.form['last_name']
    email = request.form['email']
    datetime_now = datetime.utcnow().isoformat()

    print(f"Received submission at {datetime_now}: {first} {last}, {email}")

    if not first or not last or not email:
        flash('Please fill out all fields.', 'error')
        return redirect(url_for('index'))
    # Here you would typically process the data, e.g., save it to a database
    # For now, we just flash a success message
    if not email or '@' not in email:
        flash('Please enter a valid email address.', 'error')
        return redirect(url_for('index'))
    if not first.isalpha() or not last.isalpha():
        flash('Please enter valid names (letters only).', 'error')
        return redirect(url_for('index'))
    # If all validations pass, flash a success message      
    flash(f'Thanks, {first}! We got your info.', 'success')
    # Set AWS profile via environment variable if needed: os.environ['AWS_PROFILE'] = 'personal'
    os.environ['AWS_PROFILE'] = 'personal'
    dynamodb = boto3.resource(
        'dynamodb',
        region_name='us-east-1'
    )
    table = dynamodb.Table('verideal-submissions')
    record_id = str(uuid.uuid4())
    table.put_item(Item={
        'id': record_id,
        'first_name': first,
        'last_name': last,
        'email': email,
        'timestamp': datetime_now
    })
    return redirect(url_for('index'))

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'healthy', 'timestamp': datetime.utcnow().isoformat()}), 200
@app.errorhandler(404)
def page_not_found(e):
    """Custom 404 error page."""
    return render_template('404.html'), 404
@app.errorhandler(500)
def internal_server_error(e):
    """Custom 500 error page."""
    return render_template('500.html'), 500

@app.route('/wheel', methods=['GET'])
def wheel():
    """Serve the wheel page."""
    return render_template('wheel.html')


if __name__ == '__main__':
    # Run the app with debug mode enabled
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv('PORT', 5000)))