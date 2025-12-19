# OpenTalk Birthday Email Service - Render Deployment Guide

## 📦 Files to Deploy

1. **`app.py`** - Main application file (use this instead of `birthday_mail_send.py`)
2. **`requirements.txt`** - Dependencies

---

## 🚀 Render Setup

### Step 1: Create New Web Service
1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click **"New +"** → **"Web Service"**
3. Connect your GitHub repo or upload files

### Step 2: Configure Build & Start Commands

| Setting | Value |
|---------|-------|
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120` |

> ⚠️ Note: Changed from `birthday_mail_send:app` to `app:app`

### Step 3: Environment Variables

Add these in Render Dashboard → Environment:

| Variable | Value | Required |
|----------|-------|----------|
| `MONGO_URI` | `mongodb+srv://open_talk:jainpansare@opentalk.kk61m.mongodb.net/?retryWrites=true&w=majority&appName=Opentalk` | ✅ Yes |
| `SENDER_EMAIL` | `officialopentalk@gmail.com` | ✅ Yes |
| `SENDER_PASSWORD` | `qlpz iueo fcti tcao` | ✅ Yes |
| `LOG_LEVEL` | `INFO` | Optional |
| `PORT` | (Auto-set by Render) | Auto |

---

## ⏰ Cron Job Setup (Using cron-job.org - FREE)

Go to [cron-job.org](https://cron-job.org) and create **TWO** cron jobs:

### Cron Job 1: Wake Up Service
| Setting | Value |
|---------|-------|
| **Title** | OpenTalk Birthday - Wake |
| **URL** | `https://ot-birthday-mail.onrender.com/wake` |
| **Schedule** | Every day at **11:58 PM IST** (18:28 UTC) |
| **Cron Expression** | `28 18 * * *` |

### Cron Job 2: Send Emails
| Setting | Value |
|---------|-------|
| **Title** | OpenTalk Birthday - Send Emails |
| **URL** | `https://ot-birthday-mail.onrender.com/send-birthday-emails` |
| **Schedule** | Every day at **12:02 AM IST** (18:32 UTC) |
| **Cron Expression** | `32 18 * * *` |

> 💡 **Why 4 minutes apart?** 
> - First call wakes up the service (cold start takes ~30-60 seconds)
> - Second call actually sends the emails when service is ready

---

## 🔗 Available Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /` | Health check + wake up service |
| `GET /wake` | Explicit wake up for cron |
| `GET /health` | Detailed health status |
| `GET /preview-birthdays` | See today's birthdays without sending |
| `GET /send-birthday-emails` | **Send birthday emails** |
| `GET /test-email?email=you@gmail.com` | Send a test email |

---

## 🧪 Testing

### 1. Test if service is running:
```
curl https://ot-birthday-mail.onrender.com/
```

### 2. Check today's birthdays:
```
curl https://ot-birthday-mail.onrender.com/preview-birthdays
```

### 3. Send a test email:
```
curl https://ot-birthday-mail.onrender.com/test-email?email=your@email.com
```

### 4. Manually trigger birthday emails:
```
curl https://ot-birthday-mail.onrender.com/send-birthday-emails
```

---

## 🔧 Troubleshooting

### Service not waking up?
- Increase the gap between wake and send to 5 minutes
- Check Render logs for errors

### Emails not sending?
1. Check if `SENDER_EMAIL` and `SENDER_PASSWORD` are set correctly
2. Make sure Gmail "Less secure apps" is enabled OR use App Password
3. Check `/health` endpoint for SMTP status

### MongoDB connection failing?
1. Verify `MONGO_URI` is correct
2. Check if your IP is whitelisted in MongoDB Atlas (use 0.0.0.0/0 for all IPs)

### No birthdays found?
1. Check date format in database (should be `DD/MM/YYYY`)
2. Verify timezone - service uses IST (Asia/Kolkata)
3. Use `/preview-birthdays` to debug

---

## 📊 Expected Cron Job Flow

```
11:58 PM IST → /wake → Service wakes up, MongoDB connects
12:02 AM IST → /send-birthday-emails → Fetches today's birthdays, sends emails
```

---

## ⚡ Performance Notes

- **Cold start**: ~30-60 seconds (Render free tier)
- **Email rate**: 10 emails per batch, 2 second delay between batches
- **Retry logic**: 3 attempts per failed email
- **Timeout**: 120 seconds for gunicorn workers

---

## 🔒 Security Notes

1. Never commit credentials to Git
2. Use environment variables for all secrets
3. The test-email endpoint is for debugging only

---

Last Updated: December 2024
