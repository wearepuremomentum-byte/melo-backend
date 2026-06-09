# Pure Meditation Backend — Railway Deploy

Backend for Pure Meditation subscriptions, Stripe checkout, PayPal subscription links, auth, Guided Sessions, royalty tracking, and health checks.

## Deploy on Railway

Connect this GitHub repo to Railway.

Railway settings:

```text
Root directory: /
Start command: gunicorn app:app --bind 0.0.0.0:$PORT
```

If Railway uses `railway.json`, the start command is already included.

## Environment variables

Add these in Railway → Variables:

```text
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
PAYPAL_PLAN_ID_BASE=P-...
PAYPAL_PLAN_ID_PRO=P-...
PAYPAL_PLAN_ID_PREMIUM=P-...
FRONTEND_URL=https://YOUR-NETLIFY-SITE.netlify.app
ADMIN_PASSWORD=choose_a_strong_password
DATABASE_URL=Railway PostgreSQL adds this automatically
```

## Add PostgreSQL

In Railway, add a PostgreSQL database service. Railway will inject `DATABASE_URL`.

## Health check

After deploy:

```text
https://YOUR-RAILWAY-URL/health
```

Expected:

```json
{"status":"ok","service":"pure-meditation-backend"}
```

## Stripe webhook

Set Stripe webhook endpoint to:

```text
https://YOUR-RAILWAY-URL/webhook
```

Events:

```text
checkout.session.completed
customer.subscription.deleted
customer.subscription.updated
invoice.payment_failed
```

## PayPal

Create 3 PayPal plans and add IDs to Railway variables:

```text
PAYPAL_PLAN_ID_BASE
PAYPAL_PLAN_ID_PRO
PAYPAL_PLAN_ID_PREMIUM
```
