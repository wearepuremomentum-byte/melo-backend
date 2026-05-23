"""
Pure Meditation - Flask Backend
--------------------------------
Minimal meditation app backend. No bloat.
"""

from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime, timedelta
import stripe
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# ── Database ──────────────────────────────────────────────
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv(
    'DATABASE_URL', 'sqlite:///app.db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ── Stripe ────────────────────────────────────────────────
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

# ── Config ────────────────────────────────────────────────
FRONTEND_URL = os.getenv(
    'FRONTEND_URL',
    'https://glistening-baklava-2dbe70.netlify.app'
)

# ============================================================
# DATABASE MODELS
# ============================================================

class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    stripe_customer_id = db.Column(db.String(255))
    subscription_status = db.Column(
        db.String(20), default='free', index=True
    )  # free | trial | active | canceled
    credits_remaining = db.Column(db.Integer, default=30)  # minutes
    trial_started = db.Column(db.DateTime)
    trial_ends = db.Column(db.DateTime)
    subscription_started = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    def to_dict(self):
        return {
            'user_id': self.id,
            'email': self.email,
            'subscription_status': self.subscription_status,
            'credits_remaining': self.credits_remaining,
            'trial_ends': self.trial_ends.isoformat()
                if self.trial_ends else None,
            'member_since': self.created_at.isoformat(),
        }


class Track(db.Model):
    __tablename__ = 'tracks'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), nullable=False, index=True)
    duration_minutes = db.Column(db.Integer, nullable=False)
    audio_url = db.Column(db.String(500), nullable=False)
    description = db.Column(db.String(300))
    suno_id = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'category': self.category,
            'duration': self.duration_minutes,
            'description': self.description,
            'url': self.audio_url,
        }


class Subscription(db.Model):
    __tablename__ = 'subscriptions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey('users.id'), nullable=False
    )
    stripe_subscription_id = db.Column(db.String(255))
    status = db.Column(
        db.String(20), default='active'
    )  # active | canceled | paused
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    canceled_at = db.Column(db.DateTime)
    next_billing_date = db.Column(db.DateTime)

    user = db.relationship('User', backref='subscriptions')


class ListeningHistory(db.Model):
    __tablename__ = 'listening_history'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey('users.id'), nullable=False
    )
    track_id = db.Column(
        db.Integer, db.ForeignKey('tracks.id'), nullable=False
    )
    played_at = db.Column(db.DateTime, default=datetime.utcnow)
    duration_seconds = db.Column(db.Integer)


# ============================================================
# AUTHENTICATION
# ============================================================

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    """Create new user with 14-day free trial. No credit card required."""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()

    if not email or '@' not in email:
        return jsonify({'error': 'Valid email required'}), 400

    existing = User.query.filter_by(email=email).first()
    if existing:
        return jsonify({
            'error': 'Email already registered',
            'user_id': existing.id,
        }), 409

    user = User(
        email=email,
        subscription_status='trial',
        trial_started=datetime.utcnow(),
        trial_ends=datetime.utcnow() + timedelta(days=14),
        credits_remaining=30,
    )

    db.session.add(user)
    db.session.commit()

    return jsonify(user.to_dict()), 201


@app.route('/api/auth/login', methods=['POST'])
def login():
    """Login existing user by email (no password — simplicity first)."""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip().lower()

    if not email:
        return jsonify({'error': 'Email required'}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'error': 'User not found'}), 404

    user.last_login = datetime.utcnow()
    db.session.commit()

    return jsonify(user.to_dict()), 200


# ============================================================
# TRACKS
# ============================================================

@app.route('/api/tracks', methods=['GET'])
def get_tracks():
    """Get all tracks, optionally filtered by category."""
    category = request.args.get('category', '').strip()

    query = Track.query
    if category and category != 'all':
        query = query.filter_by(category=category)

    tracks = query.order_by(Track.duration_minutes.asc()).all()

    return jsonify([t.to_dict() for t in tracks]), 200


@app.route('/api/tracks/<int:track_id>', methods=['GET'])
def get_track(track_id):
    """Get a single track by ID."""
    track = Track.query.get(track_id)
    if not track:
        return jsonify({'error': 'Track not found'}), 404
    return jsonify(track.to_dict()), 200


# ============================================================
# PLAY / CREDITS
# ============================================================

@app.route('/api/play', methods=['POST'])
def play_track():
    """
    Play a track. Paid subscribers: unlimited.
    Trial/free users: deduct from 30 min/month credits.
    """
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    track_id = data.get('track_id')

    if not user_id or not track_id:
        return jsonify({'error': 'user_id and track_id required'}), 400

    user = User.query.get(user_id)
    track = Track.query.get(track_id)

    if not user:
        return jsonify({'error': 'User not found'}), 404
    if not track:
        return jsonify({'error': 'Track not found'}), 404

    # Paid → unlimited
    if user.subscription_status == 'active':
        entry = ListeningHistory(user_id=user_id, track_id=track_id)
        db.session.add(entry)
        db.session.commit()
        return jsonify({
            'status': 'playing',
            'track': track.title,
            'credits_left': 'unlimited',
            'url': track.audio_url,
        }), 200

    # Trial / free → check credits
    if user.credits_remaining < track.duration_minutes:
        return jsonify({
            'error': 'Insufficient credits. Please upgrade to continue.',
            'credits_remaining': user.credits_remaining,
            'needed': track.duration_minutes,
        }), 402

    user.credits_remaining -= track.duration_minutes
    entry = ListeningHistory(
        user_id=user_id,
        track_id=track_id,
        duration_seconds=track.duration_minutes * 60,
    )

    db.session.add(entry)
    db.session.commit()

    return jsonify({
        'status': 'playing',
        'track': track.title,
        'credits_left': user.credits_remaining,
        'url': track.audio_url,
    }), 200


# ============================================================
# PAYMENTS — SUBSCRIPTION
# ============================================================

@app.route('/api/checkout', methods=['POST'])
def checkout():
    """Create a Stripe checkout session for the $20/month subscription."""
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')

    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    # Create Stripe customer if needed
    if not user.stripe_customer_id:
        customer = stripe.Customer.create(email=user.email)
        user.stripe_customer_id = customer.id
        db.session.commit()

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Pure Meditation — Monthly',
                        'description': (
                            '30 minutes free per month + unlimited meditation. '
                            'No bloat. Cancel anytime.'
                        ),
                    },
                    'unit_amount': 2000,  # $20.00
                },
                'quantity': 1,
            }],
            mode='subscription',
            success_url=f'{FRONTEND_URL}/success?session_id={{CHECKOUT_SESSION_ID}}',
            cancel_url=f'{FRONTEND_URL}/cancel',
            customer=user.stripe_customer_id,
            metadata={'user_id': str(user_id)},
        )

        return jsonify({'checkout_url': session.url}), 200

    except stripe.error.StripeError as e:
        return jsonify({'error': str(e)}), 400


# ============================================================
# PAYMENTS — CREDITS
# ============================================================

CREDIT_PACKAGES = {
    'small':  {'amount': 499,  'credits': 60,  'name': '60 Minutes'},
    'medium': {'amount': 1299, 'credits': 180, 'name': '180 Minutes'},
    'large':  {'amount': 2999, 'credits': 500, 'name': '500 Minutes'},
}


@app.route('/api/credits-checkout', methods=['POST'])
def credits_checkout():
    """Create a Stripe checkout for one-time credit purchase."""
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')
    package_key = data.get('package')

    if not user_id or not package_key:
        return jsonify({'error': 'user_id and package required'}), 400

    pkg = CREDIT_PACKAGES.get(package_key)
    if not pkg:
        return jsonify({
            'error': 'Invalid package',
            'valid': list(CREDIT_PACKAGES.keys()),
        }), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    if not user.stripe_customer_id:
        customer = stripe.Customer.create(email=user.email)
        user.stripe_customer_id = customer.id
        db.session.commit()

    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': f'Pure Meditation Credits — {pkg["name"]}',
                    },
                    'unit_amount': pkg['amount'],
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=f'{FRONTEND_URL}/success',
            cancel_url=f'{FRONTEND_URL}/cancel',
            customer=user.stripe_customer_id,
            metadata={
                'user_id': str(user_id),
                'credits': str(pkg['credits']),
                'type': 'credits',
            },
        )

        return jsonify({'checkout_url': session.url}), 200

    except stripe.error.StripeError as e:
        return jsonify({'error': str(e)}), 400


# ============================================================
# CANCEL — ONE CLICK, IMMEDIATE
# ============================================================

@app.route('/api/cancel', methods=['POST'])
def cancel():
    """Cancel subscription immediately. No dark patterns. No phone calls."""
    data = request.get_json(silent=True) or {}
    user_id = data.get('user_id')

    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    sub = Subscription.query.filter_by(
        user_id=user_id, status='active'
    ).first()

    if sub and sub.stripe_subscription_id:
        try:
            stripe.Subscription.delete(sub.stripe_subscription_id)
        except stripe.error.StripeError as e:
            return jsonify({'error': str(e)}), 400

    if sub:
        sub.status = 'canceled'
        sub.canceled_at = datetime.utcnow()

    user.subscription_status = 'canceled'
    db.session.commit()

    return jsonify({
        'status': 'canceled',
        'message': (
            'Your subscription has been canceled. '
            'No further charges. You can re-subscribe anytime.'
        ),
    }), 200


# ============================================================
# USER STATS
# ============================================================

@app.route('/api/user/<int:user_id>/stats', methods=['GET'])
def user_stats(user_id):
    """Get meditation stats for a user."""
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    total_sessions = ListeningHistory.query.filter_by(
        user_id=user_id
    ).count()

    total_seconds = (
        db.session.query(db.func.sum(ListeningHistory.duration_seconds))
        .filter_by(user_id=user_id)
        .scalar()
    ) or 0

    return jsonify({
        **user.to_dict(),
        'total_meditations': total_sessions,
        'total_minutes': total_seconds // 60,
    }), 200


# ============================================================
# STRIPE WEBHOOK
# ============================================================

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle Stripe events."""
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, os.getenv('STRIPE_WEBHOOK_SECRET', '')
        )
    except ValueError:
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({'error': 'Invalid signature'}), 400

    event_type = event['type']
    session = event['data']['object']

    # ── Checkout completed ────────────────────────────
    if event_type == 'checkout.session.completed':
        meta = session.get('metadata', {})
        user_id = meta.get('user_id')

        if not user_id:
            return jsonify({'status': 'no user_id in metadata'}), 200

        user = User.query.get(int(user_id))
        if not user:
            return jsonify({'status': 'user not found'}), 200

        # Credit purchase
        if meta.get('type') == 'credits':
            credits = int(meta.get('credits', 0))
            user.credits_remaining += credits

        # Subscription purchase
        else:
            user.subscription_status = 'active'
            user.subscription_started = datetime.utcnow()

            sub = Subscription(
                user_id=user.id,
                stripe_subscription_id=session.get('subscription', ''),
                status='active',
            )
            db.session.add(sub)

        db.session.commit()

    # ── Subscription deleted ───────────────────────────
    elif event_type == 'customer.subscription.deleted':
        stripe_sub_id = session.get('id', '')
        sub = Subscription.query.filter_by(
            stripe_subscription_id=stripe_sub_id
        ).first()

        if sub:
            sub.status = 'canceled'
            sub.canceled_at = datetime.utcnow()

            user = User.query.get(sub.user_id)
            if user:
                user.subscription_status = 'canceled'

            db.session.commit()

    return jsonify({'status': 'success'}), 200


# ============================================================
# HEALTH CHECK
# ============================================================

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.utcnow().isoformat(),
    }), 200


# ============================================================
# SEED DATA (run once to populate demo tracks)
# ============================================================

@app.cli.command('seed')
def seed_tracks():
    """Seed the database with demo tracks."""
    demo_tracks = [
        # Sleep
        ('10 Min Deep Sleep', 'sleep', 10,
         'https://storage.example.com/sleep-10.mp3',
         'Quick deep sleep meditation with binaural beats'),
        ('20 Min Relaxation', 'sleep', 20,
         'https://storage.example.com/sleep-20.mp3',
         'Warm ambient pads for deep relaxation'),
        ('30 Min Sleep Story', 'sleep', 30,
         'https://storage.example.com/sleep-30.mp3',
         'Gentle piano progression for restful sleep'),
        ('45 Min Deep Sleep', 'sleep', 45,
         'https://storage.example.com/sleep-45.mp3',
         'Ultimate deep sleep with binaural 40Hz'),
        ('60 Min Long Sleep', 'sleep', 60,
         'https://storage.example.com/sleep-60.mp3',
         'Long-form sleep meditation with nature sounds'),
        # Focus
        ('20 Min Focus Boost', 'focus', 20,
         'https://storage.example.com/focus-20.mp3',
         'Lo-fi focus meditation for concentration'),
        ('30 Min Deep Work', 'focus', 30,
         'https://storage.example.com/focus-30.mp3',
         'Ambient electronic for productive flow'),
        ('45 Min Flow State', 'focus', 45,
         'https://storage.example.com/focus-45.mp3',
         'Progressive synth for deep work state'),
        # Anxiety
        ('10 Min Calm', 'anxiety', 10,
         'https://storage.example.com/anxiety-10.mp3',
         'Quick anxiety relief with warm pads and nature'),
        ('15 Min Grounding', 'anxiety', 15,
         'https://storage.example.com/anxiety-15.mp3',
         'Centering meditation with gentle strings'),
        # Energy
        ('5 Min Morning Boost', 'energy', 5,
         'https://storage.example.com/energy-5.mp3',
         'Gentle morning energy activation'),
        ('10 Min Energy Flow', 'energy', 10,
         'https://storage.example.com/energy-10.mp3',
         'Uplifting energy meditation at 80 BPM'),
    ]

    existing = Track.query.count()
    if existing > 0:
        print(f'  ⚠ {existing} tracks already exist — skipping seed.')
        return

    for title, cat, dur, url, desc in demo_tracks:
        db.session.add(Track(
            title=title, category=cat, duration_minutes=dur,
            audio_url=url, description=desc,
        ))

    db.session.commit()
    print(f'  ✓ Seeded {len(demo_tracks)} demo tracks.')


# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000, host='0.0.0.0')
