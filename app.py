"""
Language Speaking App Birthday Email Service
Deployed on Vercel with Gmail SMTP

Features:
- Gmail SMTP for reliable email delivery
- Retry logic for failed emails
- IST timezone handling
- Rate limiting to avoid Gmail blocking
- Batch processing for large user lists
"""

from flask import Flask, jsonify, request
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from datetime import datetime
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import random
import logging
import time
from functools import wraps

# Try zoneinfo (Python 3.9+), fallback to pytz
try:
    from zoneinfo import ZoneInfo
    IST = ZoneInfo("Asia/Kolkata")
except ImportError:
    import pytz
    IST = pytz.timezone("Asia/Kolkata")

app = Flask(__name__)

# ------------------ Logging Setup ------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("birthday_mail")

# ------------------ Configuration ------------------
class Config:
    MONGO_URI = os.environ.get("MONGO_URI")
    SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "officialopentalk@gmail.com")
    SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
    
    # Email settings
    SMTP_SERVER = "smtp.gmail.com"
    SMTP_PORT = 587
    EMAIL_BATCH_SIZE = 10
    EMAIL_DELAY_SECONDS = 2
    MAX_RETRIES = 3
    
    # MongoDB settings
    MONGO_TIMEOUT_MS = 10000

# Global state
service_state = {
    "is_ready": False,
    "mongo_connected": False,
    "last_email_run": None,
    "total_emails_sent_today": 0
}

# ------------------ MongoDB Setup ------------------
mongo_client = None
users_col = None

def init_mongo():
    """Initialize MongoDB connection with retry logic"""
    global mongo_client, users_col
    
    if not Config.MONGO_URI:
        logger.error("MONGO_URI environment variable not set!")
        return False
    
    for attempt in range(3):
        try:
            mongo_client = MongoClient(
                Config.MONGO_URI,
                serverSelectionTimeoutMS=Config.MONGO_TIMEOUT_MS,
                connectTimeoutMS=Config.MONGO_TIMEOUT_MS
            )
            mongo_client.admin.command('ping')
            users_col = mongo_client["Opentalk"]["users"]
            service_state["mongo_connected"] = True
            logger.info("MongoDB connected successfully!")
            return True
        except Exception as e:
            logger.warning(f"MongoDB connection attempt {attempt + 1} failed: {e}")
            time.sleep(1)
    
    logger.error("Failed to connect to MongoDB after all retries")
    return False

# Initialize on startup
def startup_init():
    if init_mongo():
        service_state["is_ready"] = True
        logger.info("Service initialization complete")
    else:
        service_state["is_ready"] = True
        logger.warning("Service ready but MongoDB not connected")

startup_init()

# ------------------ Email Templates ------------------
BIRTHDAY_MESSAGES = [
    "Wishing you a fantastic birthday filled with smiles, good vibes, and great conversations! 🎂🥳<br><br>Here's to learning, speaking, and making this year unforgettable. 💬🌍",
    "Happy Birthday! 🎉<br><br>Your voice adds color to Language Speaking App, and we're grateful to have you with us. Keep inspiring! 🌟",
    "May your birthday be as meaningful as your conversations on Language Speaking App. Have a great one! 🎈💬",
    "Cheers to you, {username}! 🎉<br><br>Wishing you joy, confidence, and incredible language journeys ahead.",
    "Speak boldly. Live freely. Learn constantly. That's our birthday wish for you! 🎂💬",
    "Happy Birthday from Team Language Speaking App! 🥳<br><br>May today bring laughter and your voice reach even more people.",
    "One voice can change the world. Yours already is. 🎤 Happy Birthday from Language Speaking App!",
    "Here's to another year of being amazing — and speaking like a pro. 🎉🎤 Enjoy your day, {username}!",
    "On your birthday, we celebrate your growth, voice, and confidence. Keep it up! 💪💬",
    "We hope your birthday brings you closer to your goals and to great conversations. 🎁🎉",
]

EMAIL_FOOTER = """
<br><br>
<div style="text-align: center; padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 10px; margin-top: 20px;">
    <p style="color: white; font-size: 16px; margin-bottom: 15px;">Stay Connected with Language Speaking App!</p>
    <a href="https://play.google.com/store/apps/details?id=com.open.talk" style="display: inline-block; background: white; color: #667eea; padding: 8px 12px; border-radius: 20px; text-decoration: none; margin: 3px; font-weight: bold; font-size: 13px;">📱 App</a>
    <a href="https://t.me/AppOpentalk" style="display: inline-block; background: white; color: #667eea; padding: 8px 12px; border-radius: 20px; text-decoration: none; margin: 3px; font-weight: bold; font-size: 13px;">💬 Telegram</a>
    <a href="https://www.instagram.com/english_speaking_app_official" style="display: inline-block; background: white; color: #667eea; padding: 8px 12px; border-radius: 20px; text-decoration: none; margin: 3px; font-weight: bold; font-size: 13px;">📸 Instagram</a>
    <a href="https://www.youtube.com/@EnglishSpeakAppOfficial" style="display: inline-block; background: white; color: #667eea; padding: 8px 12px; border-radius: 20px; text-decoration: none; margin: 3px; font-weight: bold; font-size: 13px;">📺 YouTube</a>
</div>
<p style="text-align: center; color: #999; font-size: 12px; margin-top: 20px;">
    Made with ❤️ for language learners worldwide.
</p>
"""

HTML_BIRTHDAY_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
    body {{
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        margin: 0;
        padding: 20px;
    }}
    .container {{
        background-color: white;
        max-width: 600px;
        margin: 0 auto;
        border-radius: 15px;
        box-shadow: 0 10px 40px rgba(0,0,0,0.1);
        overflow: hidden;
    }}
    .header {{
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        text-align: center;
        padding: 40px 20px;
    }}
    .header h1 {{
        margin: 0;
        font-size: 28px;
    }}
    .content {{
        padding: 30px;
        text-align: center;
    }}
    .content p {{
        font-size: 16px;
        line-height: 1.6;
        color: #333;
    }}
    .cake {{
        font-size: 80px;
        margin: 20px 0;
    }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>� Happy Birthday, {username}! 🎉</h1>
    </div>
    <div class="content">
        <div class="cake">🎂</div>
        <p>{message}</p>
        {footer}
    </div>
</div>
</body>
</html>
"""

# ------------------ Helper Functions ------------------
def get_ist_now():
    return datetime.now(IST)

def require_ready(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        for _ in range(30):
            if service_state["is_ready"]:
                break
            time.sleep(1)
        if not service_state["is_ready"]:
            return jsonify({"error": "Service is still initializing.", "status": "initializing"}), 503
        return f(*args, **kwargs)
    return decorated_function

# ------------------ Birthday Functions ------------------
DATE_FORMATS = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y", "%Y/%m/%d"]

def get_today_birthdays():
    if not service_state["mongo_connected"]:
        if not init_mongo():
            return []
    
    now = get_ist_now()
    today_day = now.day
    today_month = now.month
    logger.info(f"Checking birthdays for {today_day:02d}/{today_month:02d} (IST)")
    
    matches = []
    try:
        all_users = users_col.find(
            {"dateOfBirth": {"$exists": True, "$ne": None, "$ne": ""}},
            {"_id": 0, "username": 1, "name": 1, "email": 1, "dateOfBirth": 1}
        )
        
        for user in all_users:
            try:
                dob_str = user.get("dateOfBirth")
                if not dob_str or not isinstance(dob_str, str):
                    continue
                
                dob = None
                for fmt in DATE_FORMATS:
                    try:
                        dob = datetime.strptime(dob_str.strip(), fmt)
                        break
                    except ValueError:
                        continue
                
                if dob and dob.day == today_day and dob.month == today_month:
                    email = user.get("email")
                    if email and isinstance(email, str) and "@" in email:
                        matches.append({
                            "username": user.get("username") or user.get("name") or "Friend",
                            "name": user.get("name", ""),
                            "email": email,
                            "dateOfBirth": str(dob_str)
                        })
            except Exception as e:
                logger.debug(f"Skipping user {user.get('username')}: {e}")
                continue
                
    except Exception as e:
        logger.error(f"Error fetching birthdays: {e}", exc_info=True)
        return []
    
    logger.info(f"Found {len(matches)} users with birthdays today")
    return matches

def send_single_email(server, sender_email, to_email, username):
    """Send a single birthday email with retry logic"""
    subject = "🎉 Happy Birthday from Language Speaking App!"
    message = random.choice(BIRTHDAY_MESSAGES).replace("{username}", username)
    
    plain_text = f"Dear {username},\n\n" + message.replace("<br>", "\n") + "\n\n– Team Language Speaking App"
    
    html_content = HTML_BIRTHDAY_TEMPLATE.format(
        username=username,
        message=message,
        footer=EMAIL_FOOTER
    )
    
    msg = MIMEMultipart("alternative")
    msg['From'] = f"Language Speaking App <{sender_email}>"
    msg['To'] = to_email
    msg['Subject'] = subject
    msg['Reply-To'] = sender_email
    
    msg.attach(MIMEText(plain_text, 'plain', 'utf-8'))
    msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    
    for attempt in range(Config.MAX_RETRIES):
        try:
            server.sendmail(sender_email, to_email, msg.as_string())
            return True
        except smtplib.SMTPException as e:
            logger.warning(f"Attempt {attempt + 1} failed for {to_email}: {e}")
            if attempt < Config.MAX_RETRIES - 1:
                time.sleep(1)
    
    return False

def send_email_wishes(users):
    """Send birthday emails to users in batches"""
    sender = Config.SENDER_EMAIL
    password = Config.SENDER_PASSWORD
    
    if not sender or not password:
        logger.error("Email credentials not configured!")
        return 0, "Email credentials not configured"
    
    try:
        server = smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT, timeout=30)
        server.starttls()
        server.login(sender, password)
    except Exception as e:
        logger.error(f"SMTP connection failed: {e}")
        return 0, f"SMTP connection failed: {str(e)}"
    
    sent_count = 0
    failed_users = []
    
    for i in range(0, len(users), Config.EMAIL_BATCH_SIZE):
        batch = users[i:i + Config.EMAIL_BATCH_SIZE]
        
        for user in batch:
            to_email = user.get("email")
            username = user.get("username") or user.get("name") or "Friend"
            
            if not to_email:
                continue
            
            success = send_single_email(server, sender, to_email, username)
            
            if success:
                sent_count += 1
                logger.info(f"✅ Sent to {username} ({to_email})")
            else:
                failed_users.append(username)
                logger.error(f"❌ Failed to send to {username} ({to_email})")
        
        if i + Config.EMAIL_BATCH_SIZE < len(users):
            time.sleep(Config.EMAIL_DELAY_SECONDS)
    
    try:
        server.quit()
    except:
        pass
    
    return sent_count, failed_users

# ------------------ API Routes ------------------

@app.route("/")
def home():
    now = get_ist_now()
    return jsonify({
        "service": "Language Speaking App Birthday Mail",
        "status": "running",
        "current_time_ist": now.strftime("%Y-%m-%d %H:%M:%S IST"),
        "is_ready": service_state["is_ready"],
        "mongo_connected": service_state["mongo_connected"],
        "last_email_run": service_state["last_email_run"],
        "emails_sent_today": service_state["total_emails_sent_today"]
    })

@app.route("/health")
def health_check():
    checks = {
        "service": "ok",
        "mongo": "checking...",
        "smtp": "checking..."
    }
    
    try:
        if mongo_client:
            mongo_client.admin.command('ping')
            checks["mongo"] = "ok"
        else:
            checks["mongo"] = "not initialized"
    except Exception as e:
        checks["mongo"] = f"error: {str(e)}"
    
    if Config.SENDER_EMAIL and Config.SENDER_PASSWORD:
        checks["smtp"] = "configured"
    else:
        checks["smtp"] = "not configured"
    
    all_ok = checks["mongo"] == "ok" and checks["smtp"] == "configured"
    
    return jsonify({
        "healthy": all_ok,
        "checks": checks,
        "timestamp": get_ist_now().isoformat()
    })

@app.route("/wake")
def wake():
    now = get_ist_now()
    
    if not service_state["mongo_connected"]:
        if init_mongo():
            service_state["is_ready"] = True
    elif not service_state["is_ready"]:
        service_state["is_ready"] = True
    
    return jsonify({
        "status": "awake",
        "wake_time": now.strftime("%Y-%m-%d %H:%M:%S IST"),
        "mongo_connected": service_state["mongo_connected"],
        "ready_for_emails": service_state["is_ready"]
    })

@app.route("/preview-birthdays")
@require_ready
def preview_birthdays():
    try:
        users = get_today_birthdays()
        
        preview = []
        for user in users:
            email = user.get("email", "")
            masked_email = email[:3] + "***" + email[email.find("@"):] if email and "@" in email else None
            preview.append({
                "username": user.get("username", ""),
                "name": user.get("name", ""),
                "email": masked_email,
                "dob": user.get("dateOfBirth", "")
            })
        
        return jsonify({
            "date": get_ist_now().strftime("%Y-%m-%d"),
            "total_birthdays": len(users),
            "users": preview
        })
    except Exception as e:
        logger.error(f"Error in preview_birthdays: {e}", exc_info=True)
        return jsonify({"error": str(e), "users": []}), 500

@app.route("/send-birthday-emails")
@require_ready
def send_birthday_emails_endpoint():
    now = get_ist_now()
    
    users = get_today_birthdays()
    
    if not users:
        return jsonify({
            "success": True,
            "message": "No birthdays today.",
            "emails_sent": 0,
            "timestamp": now.isoformat()
        })
    
    logger.info(f"Sending birthday emails to {len(users)} users...")
    
    sent_count, failed = send_email_wishes(users)
    
    service_state["last_email_run"] = now.isoformat()
    service_state["total_emails_sent_today"] = sent_count
    
    logger.info(f"Email sending complete: {sent_count}/{len(users)} sent")
    
    return jsonify({
        "success": True,
        "message": f"Sent birthday emails to {sent_count}/{len(users)} users.",
        "sent": sent_count,
        "total_users": len(users),
        "failed": len(failed) if isinstance(failed, list) else 0,
        "timestamp": now.isoformat()
    })

@app.route("/test-email")
@require_ready
def test_email():
    test_email_addr = request.args.get("email")
    
    if not test_email_addr:
        return jsonify({"error": "Please provide ?email=your@email.com"}), 400
    
    sender = Config.SENDER_EMAIL
    password = Config.SENDER_PASSWORD
    
    if not sender or not password:
        return jsonify({"error": "Email credentials not configured"}), 500
    
    try:
        server = smtplib.SMTP(Config.SMTP_SERVER, Config.SMTP_PORT, timeout=30)
        server.starttls()
        server.login(sender, password)
        
        success = send_single_email(server, sender, test_email_addr, "Test User")
        server.quit()
        
        if success:
            return jsonify({"success": True, "message": f"Test email sent to {test_email_addr}"})
        else:
            return jsonify({"success": False, "message": "Failed to send test email"}), 500
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500

# For Vercel
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
