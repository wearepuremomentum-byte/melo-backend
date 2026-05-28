from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime, timedelta
import stripe
import os
import hashlib
import secrets
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///app.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

# ============================================
# HELPERS
# ============================================

def hash_password(password):
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}:{hashed}"

def verify_password(stored, provided):
    try:
        salt, hashed = stored.split(':')
        return hashed == hashlib.sha256((salt + provided).encode()).hexdigest()
    except:
        return False

# ============================================
# MODELS
# ============================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    name = db.Column(db.String(100))
    stripe_customer_id = db.Column(db.String)
    subscription_status = db.Column(db.String, default='trial')
    credits_remaining = db.Column(db.Integer, default=30)
    trial_started = db.Column(db.DateTime)
    trial_ends = db.Column(db.DateTime)
    subscription_started = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

class Track(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    audio_url = db.Column(db.String(500), nullable=False)
    description = db.Column(db.String(300))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    stripe_subscription_id = db.Column(db.String)
    status = db.Column(db.String, default='active')
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    canceled_at = db.Column(db.DateTime)

class ListeningHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    track_id = db.Column(db.Integer, db.ForeignKey('track.id'), nullable=False)
    played_at = db.Column(db.DateTime, default=datetime.utcnow)
    duration_seconds = db.Column(db.Integer)

# ============================================
# AUTH ENDPOINTS
# ============================================

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.json
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    name = data.get('name', '').strip()

    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'An account with this email already exists'}), 409

    user = User(
        email=email,
        password_hash=hash_password(password),
        name=name,
        subscription_status='trial',
        trial_started=datetime.utcnow(),
        trial_ends=datetime.utcnow() + timedelta(days=14),
        credits_remaining=30
    )

    db.session.add(user)
    db.session.commit()

    return jsonify({
        'user_id': user.id,
        'email': user.email,
        'name': user.name,
        'subscription_status': user.subscription_status,
        'subscription_tier': 'free',
        'credits_remaining': user.credits_remaining,
        'trial_ends': user.trial_ends.isoformat()
    }), 201

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    user = User.query.filter_by(email=email).first()

    if not user or not verify_password(user.password_hash, password):
        return jsonify({'error': 'Invalid email or password'}), 401

    user.last_login = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'user_id': user.id,
        'email': user.email,
        'name': user.name,
        'subscription_status': user.subscription_status,
        'subscription_tier': getattr(user, 'subscription_tier', 'free') or 'free',
        'credits_remaining': user.credits_remaining,
        'trial_ends': user.trial_ends.isoformat() if user.trial_ends else None
    }), 200

# ============================================
# TRACKS
# ============================================

@app.route('/api/tracks', methods=['GET'])
def get_tracks():
    category = request.args.get('category', 'all')
    if category and category != 'all':
        tracks = Track.query.filter_by(category=category).all()
    else:
        tracks = Track.query.all()
    return jsonify([{
        'id': t.id, 'title': t.title, 'category': t.category,
        'duration': t.duration_minutes, 'description': t.description,
        'url': t.audio_url
    } for t in tracks]), 200

@app.route('/api/play', methods=['POST'])
def play_track():
    data = request.json
    user_id = data.get('user_id')
    track_id = data.get('track_id')

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    track = Track.query.get(track_id)
    if not track:
        return jsonify({'error': 'Track not found'}), 404

    if user.subscription_status == 'active':
        listening = ListeningHistory(user_id=user_id, track_id=track_id,
                                     duration_seconds=track.duration_minutes * 60)
        db.session.add(listening)
        db.session.commit()
        return jsonify({'status': 'playing', 'credits_left': 'unlimited'}), 200

    if user.credits_remaining < track.duration_minutes:
        return jsonify({'error': 'Insufficient credits. Upgrade to continue.'}), 402

    user.credits_remaining -= track.duration_minutes
    listening = ListeningHistory(user_id=user_id, track_id=track_id,
                                 duration_seconds=track.duration_minutes * 60)
    db.session.add(listening)
    db.session.commit()

    return jsonify({
        'status': 'playing',
        'track': track.title,
        'credits_left': user.credits_remaining
    }), 200

# ============================================
# PAYMENTS
# ============================================

@app.route('/api/checkout', methods=['POST'])
def checkout():
    data = request.json
    user_id = data.get('user_id')
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    if not user.stripe_customer_id:
        customer = stripe.Customer.create(email=user.email)
        user.stripe_customer_id = customer.id
        db.session.commit()

    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'usd',
                'product_data': {'name': 'Pure Meditation – Monthly'},
                'unit_amount': 2000,
                'recurring': {'interval': 'month'}
            },
            'quantity': 1
        }],
        mode='subscription',
        success_url=os.getenv('FRONTEND_URL', 'https://wearemomentum.netlify.app') + '/app.html?subscribed=true',
        cancel_url=os.getenv('FRONTEND_URL', 'https://wearemomentum.netlify.app') + '/app.html',
        customer=user.stripe_customer_id,
        metadata={'user_id': user_id}
    )
    return jsonify({'checkout_url': session.url}), 200

# ============================================
# UPGRADE — Handles all 3 paid tiers
# ============================================

TIER_PRICES = {
    'base':    {'amount': 2000,  'name': 'Pure Meditation – Base',    'label': 'Base'},
    'pro':     {'amount': 2999,  'name': 'Pure Meditation – Pro',     'label': 'Pro'},
    'premium': {'amount': 4999,  'name': 'Pure Meditation – Premium', 'label': 'Premium'},
}

@app.route('/api/upgrade', methods=['POST'])
def upgrade():
    """Create Stripe checkout for any tier (base, pro, premium)"""
    data = request.json
    user_id = data.get('user_id')
    tier = data.get('tier', 'base')

    if tier not in TIER_PRICES:
        return jsonify({'error': 'Invalid tier'}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    if not user.stripe_customer_id:
        customer = stripe.Customer.create(email=user.email)
        user.stripe_customer_id = customer.id
        db.session.commit()

    price_info = TIER_PRICES[tier]
    frontend_url = os.getenv('FRONTEND_URL', 'https://wearemomentum.netlify.app')

    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'usd',
                'product_data': {
                    'name': price_info['name'],
                    'description': f'Pure Meditation {price_info["label"]} — monthly subscription'
                },
                'unit_amount': price_info['amount'],
                'recurring': {'interval': 'month'}
            },
            'quantity': 1
        }],
        mode='subscription',
        success_url=frontend_url + '/app.html?subscribed=' + tier,
        cancel_url=frontend_url + '/app.html',
        customer=user.stripe_customer_id,
        metadata={'user_id': str(user_id), 'tier': tier}
    )

    return jsonify({'checkout_url': session.url, 'tier': tier}), 200

@app.route('/api/credits-checkout', methods=['POST'])
def credits_checkout():
    data = request.json
    user_id = data.get('user_id')
    credit_package = data.get('package')
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    packages = {
        'small':  {'amount': 499,  'credits': 60,  'name': '60 Minutes'},
        'medium': {'amount': 1299, 'credits': 180, 'name': '180 Minutes'},
        'large':  {'amount': 2999, 'credits': 500, 'name': '500 Minutes'}
    }
    if credit_package not in packages:
        return jsonify({'error': 'Invalid package'}), 400

    pkg = packages[credit_package]
    if not user.stripe_customer_id:
        customer = stripe.Customer.create(email=user.email)
        user.stripe_customer_id = customer.id
        db.session.commit()

    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'usd',
                'product_data': {'name': f'Pure Meditation Credits – {pkg["name"]}'},
                'unit_amount': pkg['amount']
            },
            'quantity': 1
        }],
        mode='payment',
        success_url=os.getenv('FRONTEND_URL', 'https://wearemomentum.netlify.app') + '/app.html',
        cancel_url=os.getenv('FRONTEND_URL', 'https://wearemomentum.netlify.app') + '/app.html',
        customer=user.stripe_customer_id,
        metadata={'user_id': user_id, 'credits': pkg['credits'], 'type': 'credits'}
    )
    return jsonify({'checkout_url': session.url}), 200

# ============================================
# WEBHOOK
# ============================================

@app.route('/webhook', methods=['POST'])
def webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, os.getenv('STRIPE_WEBHOOK_SECRET')
        )
    except ValueError:
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({'error': 'Invalid signature'}), 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = session['metadata']['user_id']
        user = User.query.get(user_id)
        if user:
            if session['metadata'].get('type') == 'credits':
                credits = int(session['metadata'].get('credits', 0))
                user.credits_remaining += credits
            else:
                user.subscription_status = 'active'
                user.subscription_tier = session['metadata'].get('tier', 'base')
                user.subscription_started = datetime.utcnow()
                sub = Subscription(
                    user_id=user_id,
                    stripe_subscription_id=session.get('subscription'),
                    status='active'
                )
                db.session.add(sub)
            db.session.commit()

    if event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        sub = Subscription.query.filter_by(
            stripe_subscription_id=subscription['id']
        ).first()
        if sub:
            sub.status = 'canceled'
            sub.canceled_at = datetime.utcnow()
            user = User.query.get(sub.user_id)
            if user:
                user.subscription_status = 'canceled'
            db.session.commit()

    return jsonify({'status': 'success'}), 200

# ============================================
# CANCEL
# ============================================

@app.route('/api/cancel', methods=['POST'])
def cancel():
    data = request.json
    user_id = data.get('user_id')
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    sub = Subscription.query.filter_by(user_id=user_id, status='active').first()
    if sub and sub.stripe_subscription_id:
        try:
            stripe.Subscription.delete(sub.stripe_subscription_id)
        except stripe.error.StripeError as e:
            return jsonify({'error': str(e)}), 400

    user.subscription_status = 'canceled'
    db.session.commit()
    return jsonify({'status': 'canceled'}), 200

# ============================================
# USER STATS
# ============================================

@app.route('/api/user/<int:user_id>/stats', methods=['GET'])
def user_stats(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    listening_count = ListeningHistory.query.filter_by(user_id=user_id).count()
    total_seconds = db.session.query(
        db.func.sum(ListeningHistory.duration_seconds)
    ).filter_by(user_id=user_id).scalar() or 0

    return jsonify({
        'user_id': user_id,
        'email': user.email,
        'name': user.name,
        'subscription_status': user.subscription_status,
        'credits_remaining': user.credits_remaining,
        'total_meditations': listening_count,
        'total_minutes': total_seconds // 60,
        'trial_ends': user.trial_ends.isoformat() if user.trial_ends else None,
        'member_since': user.created_at.isoformat()
    }), 200

# ============================================
# HEALTH
# ============================================

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'}), 200

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)
