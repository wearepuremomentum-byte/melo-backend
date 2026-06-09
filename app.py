from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from datetime import datetime, timedelta
from dotenv import load_dotenv
import hashlib, secrets, os, urllib.parse
import stripe

load_dotenv()
app = Flask(__name__)
CORS(app)

database_url = os.getenv('DATABASE_URL', 'sqlite:///pure_meditation.db')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
stripe.api_key = os.getenv('STRIPE_SECRET_KEY')

FRONTEND_URL = os.getenv('FRONTEND_URL', 'https://wearemomentum.netlify.app')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'changeme')

TIERS = {
    'free': {'name': 'Free', 'price': 0, 'minutes': 30, 'downloads': 0, 'guided': False, 'trial_days': 0},
    'base': {'name': 'Base', 'price': 20.00, 'minutes': 999999, 'downloads': 0, 'guided': False, 'trial_days': 14},
    'pro': {'name': 'Pro', 'price': 29.99, 'minutes': 999999, 'downloads': 50, 'guided': False, 'trial_days': 0},
    'premium': {'name': 'Premium', 'price': 49.99, 'minutes': 999999, 'downloads': 200, 'guided': True, 'trial_days': 0},
}

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(160), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(120))
    stripe_customer_id = db.Column(db.String(160))
    subscription_tier = db.Column(db.String(30), default='free')
    subscription_status = db.Column(db.String(30), default='active')
    credits_remaining = db.Column(db.Integer, default=30)
    offline_downloads_remaining = db.Column(db.Integer, default=0)
    trial_ends = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

class GuidedSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(220), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    audio_url = db.Column(db.String(600), nullable=False)
    description = db.Column(db.String(600))
    guidance_type = db.Column(db.String(100))
    difficulty = db.Column(db.String(30), default='beginner')

class TrackMetadata(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(220), nullable=False)
    isrc = db.Column(db.String(32))
    category = db.Column(db.String(60))
    album = db.Column(db.String(220))
    bpm = db.Column(db.String(50))
    primary_hz = db.Column(db.String(100))
    solfeggio_hz = db.Column(db.String(100))
    spotify_url = db.Column(db.String(600))
    apple_music_url = db.Column(db.String(600))
    youtube_music_url = db.Column(db.String(600))

class RoyaltyRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    track_title = db.Column(db.String(220))
    platform = db.Column(db.String(80))
    reporting_period = db.Column(db.String(20))
    streams = db.Column(db.Integer, default=0)
    revenue = db.Column(db.Float, default=0.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

def hash_password(password):
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f'{salt}:{hashed}'

def verify_password(stored, password):
    try:
        salt, hashed = stored.split(':', 1)
        return hashlib.sha256((salt + password).encode()).hexdigest() == hashed
    except Exception:
        return False

def user_payload(user):
    tier = TIERS.get(user.subscription_tier, TIERS['free'])
    return {
        'user_id': user.id,
        'email': user.email,
        'name': user.name,
        'subscription_tier': user.subscription_tier,
        'subscription_status': user.subscription_status,
        'credits_remaining': user.credits_remaining if user.subscription_tier == 'free' else 'unlimited',
        'offline_downloads_remaining': user.offline_downloads_remaining,
        'trial_ends': user.trial_ends.isoformat() if user.trial_ends else None,
        'features': {
            'ad_supported': user.subscription_tier == 'free',
            'offline_downloads': user.subscription_tier in ['pro', 'premium'],
            'guided_sessions': tier['guided'],
            'cancel_anytime': True
        }
    }

@app.before_request
def ensure_tables():
    # Safe for simple launch. For scale, replace with migrations.
    db.create_all()

@app.get('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'pure-meditation-backend'})

@app.get('/api/pricing')
def pricing():
    return jsonify({'tiers': TIERS, 'currency': 'USD'})

@app.post('/api/auth/signup')
def signup():
    data = request.get_json(force=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    name = (data.get('name') or '').strip()
    tier = data.get('tier') or 'free'
    if tier not in TIERS: tier = 'free'
    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Account already exists'}), 409
    trial_ends = datetime.utcnow() + timedelta(days=14) if tier == 'base' else None
    user = User(
        email=email,
        password_hash=hash_password(password),
        name=name,
        subscription_tier=tier,
        subscription_status='trial' if tier == 'base' else 'active',
        credits_remaining=30 if tier == 'free' else 999999,
        offline_downloads_remaining=TIERS[tier]['downloads'],
        trial_ends=trial_ends
    )
    db.session.add(user); db.session.commit()
    return jsonify(user_payload(user)), 201

@app.post('/api/auth/login')
def login():
    data = request.get_json(force=True) or {}
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    user = User.query.filter_by(email=email).first()
    if not user or not verify_password(user.password_hash, password):
        return jsonify({'error': 'Invalid email or password'}), 401
    user.last_login = datetime.utcnow(); db.session.commit()
    return jsonify(user_payload(user))

@app.get('/api/user/<int:user_id>/profile')
def profile(user_id):
    user = User.query.get_or_404(user_id)
    return jsonify(user_payload(user))

@app.post('/api/upgrade')
def upgrade():
    data = request.get_json(force=True) or {}
    user_id = data.get('user_id')
    tier = data.get('tier')
    if tier not in ['base', 'pro', 'premium']:
        return jsonify({'error': 'Invalid tier'}), 400
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    if not stripe.api_key:
        return jsonify({'error': 'STRIPE_SECRET_KEY missing on backend'}), 500
    if not user.stripe_customer_id:
        customer = stripe.Customer.create(email=user.email, name=user.name)
        user.stripe_customer_id = customer.id
        db.session.commit()
    t = TIERS[tier]
    kwargs = {}
    if tier == 'base':
        kwargs['subscription_data'] = {'trial_period_days': 14}
    session = stripe.checkout.Session.create(
        mode='subscription',
        customer=user.stripe_customer_id,
        automatic_payment_methods={'enabled': True},
        line_items=[{
            'price_data': {
                'currency': 'usd',
                'product_data': {'name': f'Pure Meditation — {t["name"]}'},
                'unit_amount': int(t['price'] * 100),
                'recurring': {'interval': 'month'}
            },
            'quantity': 1
        }],
        success_url=f'{FRONTEND_URL}/app.html?upgraded={tier}&session_id={{CHECKOUT_SESSION_ID}}',
        cancel_url=f'{FRONTEND_URL}/pricing.html?canceled=true',
        metadata={'user_id': str(user.id), 'tier': tier},
        **kwargs
    )
    return jsonify({'checkout_url': session.url})

@app.post('/api/upgrade/paypal')
def paypal_upgrade():
    data = request.get_json(force=True) or {}
    tier = data.get('tier')
    if tier not in ['base', 'pro', 'premium']:
        return jsonify({'error': 'Invalid tier'}), 400
    plan_ids = {
        'base': os.getenv('PAYPAL_PLAN_ID_BASE', 'P-BASE_PLAN_ID_HERE'),
        'pro': os.getenv('PAYPAL_PLAN_ID_PRO', 'P-PRO_PLAN_ID_HERE'),
        'premium': os.getenv('PAYPAL_PLAN_ID_PREMIUM', 'P-PREMIUM_PLAN_ID_HERE')
    }
    return_url = urllib.parse.quote(f'{FRONTEND_URL}/app.html?upgraded={tier}&method=paypal')
    cancel_url = urllib.parse.quote(f'{FRONTEND_URL}/pricing.html?canceled=true')
    url = f'https://www.paypal.com/webapps/billing/plans/subscribe?plan_id={plan_ids[tier]}&return_url={return_url}&cancel_url={cancel_url}'
    return jsonify({'checkout_url': url})

@app.post('/webhook')
def stripe_webhook():
    payload = request.get_data(as_text=True)
    sig = request.headers.get('Stripe-Signature')
    secret = os.getenv('STRIPE_WEBHOOK_SECRET')
    if not secret:
        return jsonify({'error': 'STRIPE_WEBHOOK_SECRET missing'}), 500
    try:
        event = stripe.Webhook.construct_event(payload, sig, secret)
    except Exception as e:
        return jsonify({'error': str(e)}), 400
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = session.get('metadata', {}).get('user_id')
        tier = session.get('metadata', {}).get('tier')
        user = User.query.get(user_id)
        if user and tier in TIERS:
            user.subscription_tier = tier
            user.subscription_status = 'active'
            user.credits_remaining = 999999 if tier != 'free' else 30
            user.offline_downloads_remaining = TIERS[tier]['downloads']
            db.session.commit()
    return jsonify({'status': 'success'})

GUIDED_DEFAULTS = [
    ('10 Min Body Scan for Sleep','sleep',10,'body-scan','beginner','Guided body scan to release tension and support sleep.'),
    ('20 Min Deep Sleep Visualization','sleep',20,'visualization','beginner','Guided visualization for deep sleep preparation.'),
    ('30 Min Progressive Muscle Relaxation','sleep',30,'body-scan','beginner','Progressive muscle relaxation for full-body release.'),
    ('15 Min Breath Awareness for Focus','focus',15,'breath-work','beginner','Breath awareness for attention and mental clarity.'),
    ('20 Min Concentration Meditation','focus',20,'visualization','intermediate','Single-point concentration practice for deep work.'),
    ('10 Min 4-7-8 Breathing','anxiety',10,'breath-work','beginner','Guided breathing for calm and nervous-system reset.'),
    ('15 Min Grounding Visualization','anxiety',15,'visualization','beginner','Grounding visualization for safety and calm.'),
    ('20 Min NSDR','anxiety',20,'body-scan','beginner','Non-sleep deep rest style recovery session.'),
    ('5 Min Kapalabhati Breath','energy',5,'breath-work','intermediate','Energizing breath practice.'),
    ('10 Min Morning Activation','energy',10,'breath-work','beginner','Morning breath and body activation.'),
    ('10 Min Pre-Workout Priming','fitness',10,'visualization','beginner','Mental priming before training.'),
    ('15 Min Post-Workout Body Scan','fitness',15,'body-scan','beginner','Recovery body scan after training.'),
    ('20 Min Sports Visualization','fitness',20,'visualization','advanced','Athletic visualization for performance.'),
]

@app.post('/api/guided-sessions/init')
def init_guided():
    data = request.get_json(force=True) or {}
    if data.get('admin_password') != ADMIN_PASSWORD:
        return jsonify({'error': 'Unauthorized'}), 401
    count = 0
    for title, cat, dur, gtype, diff, desc in GUIDED_DEFAULTS:
        if not GuidedSession.query.filter_by(title=title).first():
            db.session.add(GuidedSession(title=title, category=cat, duration_minutes=dur, guidance_type=gtype, difficulty=diff, description=desc, audio_url='https://res.cloudinary.com/YOUR_CLOUD/video/upload/placeholder.mp3'))
            count += 1
    db.session.commit()
    return jsonify({'status': 'success', 'sessions_added': count})

@app.get('/api/guided-sessions')
def guided():
    user_id = request.args.get('user_id')
    category = request.args.get('category')
    user = User.query.get(user_id) if user_id else None
    if not user:
        return jsonify({'error': 'User ID required'}), 400
    if user.subscription_tier != 'premium':
        return jsonify({'error': 'Premium tier required', 'message': 'Guided Sessions are exclusive to Premium members.'}), 403
    q = GuidedSession.query
    if category:
        q = q.filter_by(category=category)
    sessions = q.order_by(GuidedSession.category, GuidedSession.duration_minutes).all()
    return jsonify({'sessions': [{
        'id': s.id, 'title': s.title, 'category': s.category, 'duration': s.duration_minutes,
        'description': s.description, 'url': s.audio_url, 'guidance_type': s.guidance_type, 'difficulty': s.difficulty
    } for s in sessions]})

@app.post('/api/royalties')
def add_royalty():
    data = request.get_json(force=True) or {}
    if data.get('admin_password') != ADMIN_PASSWORD:
        return jsonify({'error': 'Unauthorized'}), 401
    r = RoyaltyRecord(track_title=data.get('track_title'), platform=data.get('platform'), reporting_period=data.get('reporting_period'), streams=int(data.get('streams', 0)), revenue=float(data.get('revenue', 0)))
    db.session.add(r); db.session.commit()
    return jsonify({'status': 'success', 'id': r.id})

@app.get('/api/royalties')
def royalties():
    rows = RoyaltyRecord.query.order_by(RoyaltyRecord.created_at.desc()).all()
    return jsonify({'total_revenue': round(sum(r.revenue for r in rows), 2), 'total_streams': sum(r.streams for r in rows), 'records': [{
        'track_title': r.track_title, 'platform': r.platform, 'period': r.reporting_period, 'streams': r.streams, 'revenue': r.revenue
    } for r in rows]})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=True)
