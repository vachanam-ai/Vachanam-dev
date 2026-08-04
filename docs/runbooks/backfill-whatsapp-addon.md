# Backfill a WhatsApp add-on paid before `addon_purchases` existed

Vinay paid ₹1,499 for the WhatsApp add-on before migration `oo38` created the
table, so the money exists in Razorpay and as a boolean on the branch, but not
in the ops Payments list or anywhere usable at tax time.

Run this ONCE, against prod, yourself — it is a financial write and there is a
UNIQUE index doing the real safety work.

## 1. Find the three values

```sql
-- org + branch (the branch the number was bought FOR)
SELECT o.id AS org_id, b.id AS branch_id, o.name, b.name
FROM organizations o
JOIN branches b ON b.org_id = o.id
WHERE o.owner_email = 'hello@vachanam.in';
```

The Razorpay payment id (`pay_...`) comes from the Razorpay dashboard — the
₹1,499 capture. Use the PAYMENT id, not the order id.

## 2. Insert

`amount` is rupees EX-GST. ₹1,499 was charged inclusive of nothing extra, so
if that figure was the full amount taken, split it out rather than inventing a
number — put the amount actually charged in `amount` and leave `gst` at 0
unless a GST component was really collected separately.

```sql
INSERT INTO addon_purchases (id, org_id, branch_id, kind, amount, gst, razorpay_payment_id)
VALUES (
  gen_random_uuid(),
  '<org_id>',
  '<branch_id>',
  'whatsapp_addon',
  1499,
  0,
  '<pay_xxxxxxxxxxxx>'
)
ON CONFLICT (razorpay_payment_id) DO NOTHING;
```

`ON CONFLICT DO NOTHING` makes a second run a no-op — the same guard that stops
a Razorpay webhook redelivery booking the money twice.

## 3. Verify

```sql
SELECT ap.kind, ap.amount, ap.gst, ap.razorpay_payment_id, ap.created_at, o.name
FROM addon_purchases ap
JOIN organizations o ON o.id = ap.org_id;
```

It should also now appear in the admin Payments list (`/admin`, add-ons section).

## Do NOT

- Do not connect from a laptop to diagnose if this errors — Supabase's auth
  circuit breaker blocks all new connections after repeated auth failures, and
  a masked-password URL trips it. Use the Supabase SQL editor.
- Do not put this in a migration. It is one clinic's money, not schema.
