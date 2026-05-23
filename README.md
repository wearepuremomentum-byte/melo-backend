# 🧘 Pure Meditation

> **"Pure Meditation. No Bloat."** — The meditation app Calm forgot to be.

[![Netlify Status](https://api.netlify.com/api/v1/badges/placeholder/deploy-status)](https://glistening-baklava-2dbe70.netlify.app/)

---

## What Is This?

Pure Meditation is a meditation app built to be the opposite of Calm and Headspace:

- ❌ No sleep stories, therapy, shorts, or social features
- ❌ No dark billing patterns
- ❌ No impossible cancellation flows
- ✅ Just meditation tracks, fresh AI-generated content weekly
- ✅ $20/month, transparent pricing
- ✅ One-click cancel, immediate
- ✅ 14-day free trial, no credit card

## Why Now?

| Stat | Value |
|------|-------|
| Calm downloads | Down **61%** since 2018 |
| Headspace downloads | Down **74%** since 2018 |
| Meditation market | Growing **12-35%** annually |
| 2033 projection | **$7.6 billion** |
| Calm Trustpilot | **1.6 stars** (86% negative) |

Users want meditation. They're leaving Calm and Headspace. This is replacement, not new discovery.

---

## Project Structure

```
pure-meditation/
├── README.md
├── netlify.toml              # Netlify deployment config
├── ACTION_CHECKLIST.md       # Launch checklist & action items
├── CONTENT_STRATEGY.md       # Blog, TikTok, Reddit, Suno prompts
│
├── backend/
│   ├── app.py                # Flask API server
│   ├── .env                  # Environment variables
│   └── requirements.txt      # Python dependencies
│
├── frontend/
│   ├── index.html            # Landing page
│   └── app.html              # Meditation app (SPA)
│
└── blog/
    ├── 1-calm-headspace-losing-users.md
    ├── 2-meditation-app-billing-trap.md
    ├── 3-fresh-ai-tracks-vs-repetition.md
    └── 4-best-meditation-apps-2026.md
```

---

## Quick Start

### Frontend (Netlify)

```bash
# Deploy from repo root — Netlify picks up index.html
cp frontend/index.html ./
cp frontend/app.html ./
cp netlify.toml ./
git add . && git commit -m "Deploy" && git push
```

### Backend (Render / local)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
flask run --port 5000
```

### Seed demo tracks

```bash
flask seed
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/signup` | Create account (14-day trial) |
| POST | `/api/auth/login` | Login by email |
| GET | `/api/tracks?category=sleep` | List tracks |
| GET | `/api/tracks/:id` | Get single track |
| POST | `/api/play` | Play track (credit check) |
| POST | `/api/checkout` | Stripe subscription checkout |
| POST | `/api/credits-checkout` | Stripe credit purchase |
| POST | `/api/cancel` | One-click cancellation |
| GET | `/api/user/:id/stats` | User meditation stats |
| POST | `/webhook` | Stripe webhook handler |
| GET | `/health` | Health check |

---

## Revenue Model

- **Subscription:** $20/month (unlimited meditation + 30 free minutes)
- **Credits:** $4.99 (60 min) | $12.99 (180 min) | $29.99 (500 min)
- **Revenue mix:** 85% subscriptions, 15% credits
- **Costs:** ~$100/month (Suno $8, hosting $25, domain $1, tools $66)
- **Margin:** ~99%

### Projections

| Year | Subscribers | Monthly Revenue | Annual |
|------|-------------|-----------------|--------|
| 1 | 1,000 | $23,000 | $276K |
| 2 | 10,000 | $230,000 | $2.75M |
| 3 | 100,000 | $2.3M | $27.5M |

---

## Growth Channels

| Channel | Strategy | Target |
|---------|----------|--------|
| TikTok | 3-5 videos/week, app demos & comparisons | 100K+ views/month |
| Reddit | r/Meditation, r/nosurf, r/simpleliving | 1 post/week |
| ProductHunt | Launch week push | Top 10 |
| Hacker News | "Show HN" post | Front page |
| SEO/Blog | 1 post/week, target "calm alternative" | 1K+ organic/month by M6 |
| Email | Weekly tips + updates | Engagement & retention |

---

## Tech Stack

- **Frontend:** HTML/CSS/JS (vanilla, zero dependencies)
- **Backend:** Flask (Python) + SQLAlchemy
- **Payments:** Stripe
- **Audio:** Suno AI (track generation)
- **Hosting:** Netlify (frontend) + Render (backend)
- **Database:** SQLite (dev) → PostgreSQL (prod)

---

## License

Proprietary. All rights reserved.

---

**[Try Pure Meditation →](https://glistening-baklava-2dbe70.netlify.app/)**

*"The meditation app Calm forgot to be."*