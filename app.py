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
    
    # Subscription tier: 'free', 'base', 'pro', 'premium'
    subscription_tier = db.Column(db.String(20), default='free')
    subscription_status = db.Column(db.String, default='active')  # active, trial, canceled
    
    # Trial tracking (for free & base tier)
    trial_started = db.Column(db.DateTime)
    trial_ends = db.Column(db.DateTime)
    
    # Subscription tracking
    subscription_started = db.Column(db.DateTime)
    subscription_renews = db.Column(db.DateTime)
    subscription_canceled_at = db.Column(db.DateTime)
    
    # Credits for free tier
    credits_remaining = db.Column(db.Integer, default=30)  # 30 min free/month
    
    # Pro tier: offline downloads limit
    offline_downloads_remaining = db.Column(db.Integer, default=50)
    
    # Premium tier: coaching sessions
    coaching_sessions_remaining = db.Column(db.Integer, default=4)  # 1/week
    
    # Ad impressions for free tier (for revenue tracking)
    ad_impressions = db.Column(db.Integer, default=0)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

class Track(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), nullable=False)  # sleep, focus, anxiety, energy
    duration_minutes = db.Column(db.Integer, nullable=False)
    audio_url = db.Column(db.String(500), nullable=False)
    description = db.Column(db.String(300))
    
    # Tier access: 'free', 'base', 'pro', 'premium', 'all'
    tier_access = db.Column(db.String(20), default='all')  # who can access this track
    
    # Pro tier exclusive
    is_exclusive_pro = db.Column(db.Boolean, default=False)
    
    # Premium tier exclusive
    is_exclusive_premium = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ExclusiveTrack(db.Model):
    """Premium tier exclusive meditation tracks with coaching"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    duration_minutes = db.Column(db.Integer, nullable=False)
    audio_url = db.Column(db.String(500), nullable=False)
    description = db.Column(db.String(500))
    coach_name = db.Column(db.String(100))  # e.g., "Dr. Jane Smith"
    coaching_tip = db.Column(db.String(1000))  # Personalized coaching
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    stripe_subscription_id = db.Column(db.String)
    
    tier = db.Column(db.String(20))  # 'base', 'pro', 'premium'
    price = db.Column(db.Float)  # 20, 29.99, 49.99
    
    status = db.Column(db.String, default='active')  # active, canceled
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    canceled_at = db.Column(db.DateTime)
    renews_at = db.Column(db.DateTime)

class ListeningHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    track_id = db.Column(db.Integer, db.ForeignKey('track.id'), nullable=False)
    played_at = db.Column(db.DateTime, default=datetime.utcnow)
    duration_seconds = db.Column(db.Integer)

class OfflineDownload(db.Model):
    """Track Pro tier offline downloads"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    track_id = db.Column(db.Integer, db.ForeignKey('track.id'), nullable=False)
    downloaded_at = db.Column(db.DateTime, default=datetime.utcnow)

class AdImpression(db.Model):
    """Track free tier ad impressions for revenue"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    ad_placement = db.Column(db.String(50))  # 'between_tracks', 'before_play', 'after_play'
    ad_type = db.Column(db.String(50))  # 'meditation_app_promo', 'tidal_promo', etc.
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ============================================
# INITIALIZE DATABASE ON STARTUP
# ============================================

with app.app_context():
    db.create_all()
    print("✅ Database initialized - all tables created")

# ============================================
# PRICING TIERS
# ============================================

TIERS = {
    'free': {
        'name': 'Free',
        'price': 0,
        'monthly_credit_minutes': 30,
        'features': {
            'ad_supported': True,
            'offline_downloads': False,
            'new_tracks_weekly': False,
            'exclusive_tracks': False,
            'coaching': False,
            'trial_days': 14
        }
    },
    'base': {
        'name': 'Base',
        'price': 20.00,
        'monthly_credit_minutes': 9999,  # Unlimited
        'features': {
            'ad_supported': False,
            'offline_downloads': False,
            'new_tracks_weekly': True,
            'exclusive_tracks': False,
            'coaching': False,
            'trial_days': 14
        }
    },
    'pro': {
        'name': 'Pro',
        'price': 29.99,
        'monthly_credit_minutes': 9999,  # Unlimited
        'features': {
            'ad_supported': False,
            'offline_downloads': True,
            'offline_limit': 50,
            'new_tracks_weekly': True,
            'exclusive_tracks': True,
            'exclusive_pro_tracks': True,
            'coaching': False,
            'trial_days': 0  # No trial
        }
    },
    'premium': {
        'name': 'Premium',
        'price': 49.99,
        'monthly_credit_minutes': 9999,  # Unlimited
        'features': {
            'ad_supported': False,
            'offline_downloads': True,
            'offline_limit': 200,
            'new_tracks_weekly': True,
            'exclusive_tracks': True,
            'exclusive_pro_tracks': True,
            'exclusive_premium_tracks': True,
            'coaching': True,
            'coaching_sessions_monthly': 4,
            'trial_days': 0  # No trial
        }
    }
}

# ============================================
# AUTH ENDPOINTS
# ============================================

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    data = request.json
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    name = data.get('name', '').strip()
    tier = data.get('tier', 'free')  # 'free' or 'base' at signup

    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400

    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'An account with this email already exists'}), 409

    # Free or Base tier
    if tier == 'base':
        subscription_status = 'trial'
        trial_started = datetime.utcnow()
        trial_ends = datetime.utcnow() + timedelta(days=14)
    else:
        subscription_status = 'active'
        trial_started = None
        trial_ends = None

    user = User(
        email=email,
        password_hash=hash_password(password),
        name=name,
        subscription_tier=tier,
        subscription_status=subscription_status,
        trial_started=trial_started,
        trial_ends=trial_ends,
        credits_remaining=30 if tier == 'free' else 9999,
        offline_downloads_remaining=0 if tier != 'pro' else 50,
        coaching_sessions_remaining=0 if tier != 'premium' else 4
    )

    db.session.add(user)
    db.session.commit()

    return jsonify({
        'user_id': user.id,
        'email': user.email,
        'name': user.name,
        'subscription_tier': user.subscription_tier,
        'subscription_status': user.subscription_status,
        'trial_ends': user.trial_ends.isoformat() if user.trial_ends else None,
        'features': TIERS[tier]['features']
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
        'subscription_tier': user.subscription_tier,
        'subscription_status': user.subscription_status,
        'trial_ends': user.trial_ends.isoformat() if user.trial_ends else None,
        'features': TIERS[user.subscription_tier]['features']
    }), 200

# ============================================
# PRICING PAGE
# ============================================

@app.route('/api/pricing', methods=['GET'])
def get_pricing():
    """Get all tier pricing and features"""
    return jsonify({
        'tiers': TIERS,
        'currency': 'USD',
        'recommended': 'base'
    }), 200

# ============================================
# TRACKS (WITH TIER FILTERING)
# ============================================

@app.route('/api/tracks', methods=['GET'])
def get_tracks():
    user_id = request.args.get('user_id')
    category = request.args.get('category', 'all')
    
    # Get user's tier (default: free if not logged in)
    user_tier = 'free'
    if user_id:
        user = User.query.get(user_id)
        if user:
            user_tier = user.subscription_tier
    
    # Get regular tracks
    if category and category != 'all':
        tracks = Track.query.filter_by(category=category).all()
    else:
        tracks = Track.query.all()
    
    # Filter by tier access
    available_tracks = []
    for track in tracks:
        # Base track
        if not track.is_exclusive_pro and not track.is_exclusive_premium:
            available_tracks.append({
                'id': track.id,
                'title': track.title,
                'category': track.category,
                'duration': track.duration_minutes,
                'description': track.description,
                'url': track.audio_url,
                'is_exclusive': False
            })
        # Pro exclusive
        elif track.is_exclusive_pro and user_tier in ['pro', 'premium']:
            available_tracks.append({
                'id': track.id,
                'title': track.title,
                'category': track.category,
                'duration': track.duration_minutes,
                'description': track.description,
                'url': track.audio_url,
                'is_exclusive': True,
                'exclusive_tier': 'pro'
            })
        # Premium exclusive
        elif track.is_exclusive_premium and user_tier == 'premium':
            available_tracks.append({
                'id': track.id,
                'title': track.title,
                'category': track.category,
                'duration': track.duration_minutes,
                'description': track.description,
                'url': track.audio_url,
                'is_exclusive': True,
                'exclusive_tier': 'premium'
            })
    
    return jsonify({
        'user_tier': user_tier,
        'total_available': len(available_tracks),
        'tracks': available_tracks
    }), 200

# ============================================
# EXCLUSIVE TRACKS (PREMIUM TIER)
# ============================================

@app.route('/api/exclusive-tracks', methods=['GET'])
def get_exclusive_tracks():
    """Premium tier exclusive tracks with coaching"""
    user_id = request.args.get('user_id')
    
    if not user_id:
        return jsonify({'error': 'User not found'}), 404
    
    user = User.query.get(user_id)
    if not user or user.subscription_tier != 'premium':
        return jsonify({'error': 'Premium tier required'}), 403
    
    exclusive = ExclusiveTrack.query.all()
    
    return jsonify({
        'user_tier': 'premium',
        'total': len(exclusive),
        'coaching_sessions_remaining': user.coaching_sessions_remaining,
        'tracks': [{
            'id': t.id,
            'title': t.title,
            'category': t.category,
            'duration': t.duration_minutes,
            'description': t.description,
            'url': t.audio_url,
            'coach': t.coach_name,
            'coaching_tip': t.coaching_tip
        } for t in exclusive]
    }), 200

# ============================================
# PLAY TRACK (WITH CREDITS & OFFLINE)
# ============================================

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

    # Check if user has access to this track
    if track.is_exclusive_pro and user.subscription_tier not in ['pro', 'premium']:
        return jsonify({'error': 'Pro tier required for this track'}), 403
    if track.is_exclusive_premium and user.subscription_tier != 'premium':
        return jsonify({'error': 'Premium tier required for this track'}), 403

    # Premium tier: unlimited, no credits
    if user.subscription_tier == 'premium':
        listening = ListeningHistory(
            user_id=user_id,
            track_id=track_id,
            duration_seconds=track.duration_minutes * 60
        )
        db.session.add(listening)
        db.session.commit()
        return jsonify({
            'status': 'playing',
            'tier': 'premium',
            'credits_left': 'unlimited',
            'show_ads': False
        }), 200

    # Pro tier: unlimited, no credits
    if user.subscription_tier == 'pro':
        listening = ListeningHistory(
            user_id=user_id,
            track_id=track_id,
            duration_seconds=track.duration_minutes * 60
        )
        db.session.add(listening)
        db.session.commit()
        return jsonify({
            'status': 'playing',
            'tier': 'pro',
            'credits_left': 'unlimited',
            'show_ads': False
        }), 200

    # Base tier: unlimited, no ads
    if user.subscription_tier == 'base':
        if user.subscription_status == 'canceled':
            return jsonify({'error': 'Subscription canceled. Please renew.'}), 402
        
        listening = ListeningHistory(
            user_id=user_id,
            track_id=track_id,
            duration_seconds=track.duration_minutes * 60
        )
        db.session.add(listening)
        db.session.commit()
        return jsonify({
            'status': 'playing',
            'tier': 'base',
            'credits_left': 'unlimited',
            'show_ads': False
        }), 200

    # Free tier: limited credits + ads
    if user.subscription_tier == 'free':
        # Check trial
        if user.subscription_status == 'trial' and user.trial_ends < datetime.utcnow():
            return jsonify({'error': 'Trial expired. Upgrade to continue.'}), 402
        
        # Check credits
        if user.credits_remaining < track.duration_minutes:
            return jsonify({
                'error': 'Insufficient credits',
                'credits_needed': track.duration_minutes,
                'credits_remaining': user.credits_remaining
            }), 402
        
        user.credits_remaining -= track.duration_minutes
        listening = ListeningHistory(
            user_id=user_id,
            track_id=track_id,
            duration_seconds=track.duration_minutes * 60
        )
        db.session.add(listening)
        db.session.commit()
        
        return jsonify({
            'status': 'playing',
            'tier': 'free',
            'credits_left': user.credits_remaining,
            'show_ads': True,  # Show ads to free users
            'ad_slots': ['before_play', 'between_tracks']
        }), 200

    return jsonify({'error': 'Unknown tier'}), 400

# ============================================
# OFFLINE DOWNLOAD (PRO & PREMIUM)
# ============================================

@app.route('/api/download', methods=['POST'])
def download_track():
    """Download track for offline (Pro & Premium only)"""
    data = request.json
    user_id = data.get('user_id')
    track_id = data.get('track_id')

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    track = Track.query.get(track_id)
    if not track:
        return jsonify({'error': 'Track not found'}), 404

    # Check tier
    if user.subscription_tier not in ['pro', 'premium']:
        return jsonify({'error': 'Offline downloads require Pro or Premium tier'}), 403

    # Check download limit
    if user.subscription_tier == 'pro' and user.offline_downloads_remaining <= 0:
        return jsonify({'error': 'Pro download limit reached (50/month)'}), 403
    if user.subscription_tier == 'premium' and user.offline_downloads_remaining <= 0:
        return jsonify({'error': 'Premium download limit reached (200/month)'}), 403

    # Check if already downloaded
    existing = OfflineDownload.query.filter_by(user_id=user_id, track_id=track_id).first()
    if existing:
        return jsonify({'error': 'Track already downloaded'}), 400

    # Record download
    download = OfflineDownload(user_id=user_id, track_id=track_id)
    user.offline_downloads_remaining -= 1
    
    db.session.add(download)
    db.session.commit()

    return jsonify({
        'status': 'downloaded',
        'track_id': track_id,
        'downloads_remaining': user.offline_downloads_remaining,
        'download_url': track.audio_url
    }), 200

# ============================================
# AD TRACKING (FREE TIER)
# ============================================

@app.route('/api/ad-impression', methods=['POST'])
def track_ad_impression():
    """Track ad impression for free tier (revenue tracking)"""
    data = request.json
    user_id = data.get('user_id')
    ad_placement = data.get('placement', 'unknown')  # before_play, between_tracks, etc.
    ad_type = data.get('type', 'general')

    user = User.query.get(user_id)
    if not user or user.subscription_tier != 'free':
        return jsonify({'error': 'Free tier required'}), 403

    ad = AdImpression(
        user_id=user_id,
        ad_placement=ad_placement,
        ad_type=ad_type
    )
    user.ad_impressions += 1
    
    db.session.add(ad)
    db.session.commit()

    return jsonify({
        'status': 'tracked',
        'total_impressions': user.ad_impressions,
        'estimated_revenue': user.ad_impressions * 0.001  # $0.001 per impression (avg CPM = $1)
    }), 200

# ============================================
# UPGRADE TIER
# ============================================

@app.route('/api/upgrade', methods=['POST'])
def upgrade_tier():
    """Upgrade user to paid tier"""
    data = request.json
    user_id = data.get('user_id')
    new_tier = data.get('tier')  # 'base', 'pro', 'premium'

    if new_tier not in TIERS:
        return jsonify({'error': 'Invalid tier'}), 400

    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    if not user.stripe_customer_id:
        customer = stripe.Customer.create(email=user.email)
        user.stripe_customer_id = customer.id
        db.session.commit()

    tier_config = TIERS[new_tier]
    
    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'usd',
                'product_data': {
                    'name': f'Pure Meditation – {tier_config["name"]} Tier',
                    'description': f'Monthly subscription'
                },
                'unit_amount': int(tier_config['price'] * 100),
                'recurring': {'interval': 'month'}
            },
            'quantity': 1
        }],
        mode='subscription',
        success_url=os.getenv('FRONTEND_URL', 'https://wearemomentum.netlify.app') + f'/app.html?upgraded={new_tier}',
        cancel_url=os.getenv('FRONTEND_URL', 'https://wearemomentum.netlify.app') + '/app.html',
        customer=user.stripe_customer_id,
        metadata={'user_id': user_id, 'tier': new_tier}
    )
    
    return jsonify({
        'checkout_url': session.url,
        'tier': new_tier,
        'price': tier_config['price']
    }), 200

# ============================================
# WEBHOOK (STRIPE)
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
        new_tier = session['metadata']['tier']
        user = User.query.get(user_id)
        
        if user:
            user.subscription_tier = new_tier
            user.subscription_status = 'active'
            user.subscription_started = datetime.utcnow()
            user.subscription_renews = datetime.utcnow() + timedelta(days=30)
            
            # Update features based on tier
            tier_config = TIERS[new_tier]
            if new_tier in ['base', 'pro', 'premium']:
                user.credits_remaining = tier_config['monthly_credit_minutes']
            if new_tier == 'pro':
                user.offline_downloads_remaining = 50
            elif new_tier == 'premium':
                user.offline_downloads_remaining = 200
                user.coaching_sessions_remaining = 4
            
            sub = Subscription(
                user_id=user_id,
                stripe_subscription_id=session.get('subscription'),
                tier=new_tier,
                price=tier_config['price'],
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
            user = User.query.get(sub.user_id)
            if user:
                user.subscription_status = 'canceled'
                user.subscription_canceled_at = datetime.utcnow()
            db.session.commit()

    return jsonify({'status': 'success'}), 200

# ============================================
# USER PROFILE & STATS
# ============================================

@app.route('/api/user/<int:user_id>/profile', methods=['GET'])
def user_profile(user_id):
    user = User.query.get(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    listening_count = ListeningHistory.query.filter_by(user_id=user_id).count()
    total_seconds = db.session.query(
        db.func.sum(ListeningHistory.duration_seconds)
    ).filter_by(user_id=user_id).scalar() or 0

    return jsonify({
        'user_id': user.id,
        'name': user.name,
        'email': user.email,
        'subscription_tier': user.subscription_tier,
        'subscription_status': user.subscription_status,
        'trial_ends': user.trial_ends.isoformat() if user.trial_ends else None,
        'subscription_renews': user.subscription_renews.isoformat() if user.subscription_renews else None,
        'credits_remaining': user.credits_remaining if user.subscription_tier == 'free' else 'unlimited',
        'offline_downloads': user.offline_downloads_remaining if user.subscription_tier in ['pro', 'premium'] else None,
        'coaching_sessions': user.coaching_sessions_remaining if user.subscription_tier == 'premium' else None,
        'total_meditations': listening_count,
        'total_minutes': total_seconds // 60,
        'features': TIERS[user.subscription_tier]['features'],
        'member_since': user.created_at.isoformat()
    }), 200

# ============================================
# HEALTH CHECK
# ============================================

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'}), 200

# ============================================
# MAIN
# ============================================

if __name__ == '__main__':
    app.run(debug=True, port=5000)
