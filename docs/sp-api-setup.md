# Amazon SP-API Setup Guide
## Brand Analytics Access for NPD Pipeline

---

## Prerequisites

Before starting, you must have **both** of the following:

| Requirement | Details |
|---|---|
| Amazon Professional Seller Account | Paid plan (~$39.99/month). Individual accounts do not get API access. |
| Amazon Brand Registry | Brand Analytics reports are exclusive to brand-registered sellers. Requires a registered trademark. |

> **Important:** Without Brand Registry, Amazon will block access to the
> `GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT` regardless of your credentials.
> Brand Registry approval takes 2–4 weeks after trademark registration.

---

## Step 1 — Register as a Developer

1. Log in to [Seller Central](https://sellercentral.amazon.com)
2. Top menu → **Apps & Services** → **Develop Apps**
3. Click **"Register as Developer"**
4. Fill in the developer profile:
   - App name: `NPD Pipeline` (any name works)
   - Purpose: **Private use / my own business**
   - Select: **Your own account only** (not publishing to the app store)
5. Agree to the terms → Submit

---

## Step 2 — Create Your SP-API Application

1. After registering → click **"Create New App"**
2. Fill in:
   - App name: `NPD Pipeline`
   - IAM ARN: *(leave blank for now — fill in after Step 5)*
   - API type: **Selling Partner API**
3. Under **Roles**, check:
   - ✅ `Reports` (required for Brand Analytics)
4. Save the app. Amazon will show you:
   - **Client ID** → save as `SP_API_CLIENT_ID`
   - **Client Secret** → save as `SP_API_CLIENT_SECRET`

---

## Step 3 — Authorize Your App (Get the Refresh Token)

1. In your app listing → click **"Authorize"**
2. A consent screen appears — approve it
3. After approval Amazon shows a **one-time authorization code**
4. Exchange the code for a refresh token using this request:

```bash
curl -X POST https://api.amazon.com/auth/o2/token \
  -d "grant_type=authorization_code" \
  -d "code=YOUR_AUTH_CODE" \
  -d "client_id=YOUR_CLIENT_ID" \
  -d "client_secret=YOUR_CLIENT_SECRET" \
  -d "redirect_uri=https://sellercentral.amazon.com/apps/authorize/consent"
```

5. The response JSON contains `refresh_token` → save as `SP_API_REFRESH_TOKEN`

> The refresh token does not expire unless you revoke the app authorization.
> Keep it secret — it grants full API access to your seller account.

---

## Step 4 — Create an AWS Account

SP-API uses AWS SigV4 request signing. You need an AWS account even if you
don't use any other AWS services. The free tier is sufficient.

1. Go to [aws.amazon.com](https://aws.amazon.com) → **Create an AWS Account**
2. Choose the **Free Tier** plan
3. Complete identity verification (credit card required but not charged)

---

## Step 5 — Create an IAM User

1. In the AWS Console → search for **IAM** → open it
2. Left sidebar → **Users** → **Create User**
3. Username: `npd-spapi-user`
4. Click **Next** → select **"Attach policies directly"**
5. Click **"Create policy"** → **JSON** tab → paste:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "execute-api:Invoke",
      "Resource": "arn:aws:execute-api:us-east-1:*:*"
    }
  ]
}
```

6. Name the policy `npd-spapi-policy` → Create
7. Attach it to `npd-spapi-user` → Create user
8. Open the user → **Security credentials** tab → **Create access key**
9. Use case: **Other** → Next → Create
10. Copy and save:
    - **Access Key ID** → `AWS_ACCESS_KEY_ID`
    - **Secret Access Key** → `AWS_SECRET_ACCESS_KEY`

> You can only view the Secret Access Key once. Save it immediately.

11. Copy the user's **ARN** (shown at the top of the user page):
    - Format: `arn:aws:iam::123456789012:user/npd-spapi-user`

---

## Step 6 — Link the IAM User to Your SP-API App

1. Go back to Seller Central → **Apps & Services** → **Develop Apps**
2. Find your `NPD Pipeline` app → **Edit**
3. Paste the IAM ARN from Step 5 into the **IAM ARN** field
4. Save the app

---

## Step 7 — Add Credentials to `.env`

Open `NPD-api/.env` and add the following variables:

```env
# Amazon SP-API credentials
SP_API_CLIENT_ID=amzn1.application-oa2-client.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SP_API_CLIENT_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
SP_API_REFRESH_TOKEN=Atzr|xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Marketplace ID — use the one for your target market
# US:  ATVPDKIKX0DER
# UK:  A1F83G8C2ARO7P
# DE:  A1PA6795UKMFR9
# FR:  A13V1IB3VIYZZH
# CA:  A2EUQ1WTGCTBG2
# AU:  A39IBJ37TRP1C6
SP_API_MARKETPLACE_ID=ATVPDKIKX0DER

# AWS credentials for SigV4 signing
AWS_ACCESS_KEY_ID=AKIAxxxxxxxxxxxxxxxx
AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
AWS_REGION=us-east-1
```

---

## Step 8 — Restart the Container

After updating `.env`, restart the Docker container to load the new variables:

```bash
docker-compose down && docker-compose up -d
```

---

## Step 9 — Test the Connection

Run a Brand Analytics ingestion for the previous month:

```bash
curl -s -X POST http://localhost:8000/api/brand-analytics/ingest/
```

Expected success response:
```json
{
  "status": "success",
  "report_id": "...",
  "report_date": "2026-05",
  "rows_inserted": 12500,
  "duration_seconds": 45.2
}
```

Then verify the database was populated:

```bash
curl -s http://localhost:8000/api/brand-analytics/status/
```

Expected response:
```json
{
  "total_terms": 12500,
  "report_dates": ["2026-05"],
  "last_ingestion": { "status": "success", ... }
}
```

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `Missing required environment variable: SP_API_CLIENT_ID` | `.env` not updated or container not restarted | Update `.env` → `docker-compose down && up` |
| `HTTP 401` from SP-API | Wrong client ID/secret or refresh token | Re-generate credentials in Seller Central |
| `HTTP 403` from SP-API | IAM ARN not linked to app, or missing Role | Check Step 6 — IAM ARN must match exactly |
| `Report DONE but no data rows` | No Brand Registry access | Apply for Brand Registry in Seller Central |
| `Report CANCELLED or FATAL` | Marketplace ID wrong | Check `SP_API_MARKETPLACE_ID` matches your region |
| Ingestion takes 30+ minutes | Normal for large reports | BA reports are built async — the poller waits up to 30 min |

---

## Marketplace IDs Reference

| Country | Marketplace ID |
|---|---|
| United States | `ATVPDKIKX0DER` |
| United Kingdom | `A1F83G8C2ARO7P` |
| Germany | `A1PA6795UKMFR9` |
| France | `A13V1IB3VIYZZH` |
| Canada | `A2EUQ1WTGCTBG2` |
| Australia | `A39IBJ37TRP1C6` |
| Japan | `A1VC38T7YXB528` |
| India | `A21TJRUUN4KGV` |
| Mexico | `A1AM78C64UM0Y8` |

---

## Summary Checklist

- [ ] Professional Seller account active
- [ ] Brand Registry approved
- [ ] Developer profile registered in Seller Central
- [ ] SP-API app created with `Reports` role
- [ ] App authorized → refresh token obtained
- [ ] AWS account created
- [ ] IAM user `npd-spapi-user` created with `execute-api:Invoke` policy
- [ ] Access key generated and saved
- [ ] IAM ARN linked to SP-API app in Seller Central
- [ ] All 6 variables added to `.env`
- [ ] Container restarted
- [ ] Ingestion test returns `"status": "success"`
