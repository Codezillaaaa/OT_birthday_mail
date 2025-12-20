"""
OpenTalk Birthday Email Service - Robust Version for Render Free Tier

Features:
- Self wake-up mechanism to handle cold starts
- Retry logic for failed emails
- Proper IST timezone handling
- Rate limiting to avoid Gmail blocking
- Health check endpoint with detailed status
- Logging for debugging
- Batch processing for large user lists
"""

from flask import Flask, jsonify, request
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from datetime import datetime
import os
import random
import logging
import time
import threading
from functools import wraps

# Resend for email (HTTP API - works on Render free tier)
import resend

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
    RESEND_API_KEY = os.environ.get("RESEND_API_KEY")  # Get from resend.com
    SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")  # Verified domain or default
    API_SECRET = os.environ.get("API_SECRET", "")  # Optional: Add security
    
    # Email settings
    EMAIL_BATCH_SIZE = 10  # Send emails in batches
    EMAIL_DELAY_SECONDS = 1  # Delay between batches
    MAX_RETRIES = 3
    
    # MongoDB settings
    MONGO_TIMEOUT_MS = 10000  # 10 seconds timeout

# Global state
service_state = {
    "last_wake_time": None,
    "last_email_run": None,
    "total_emails_sent_today": 0,
    "is_ready": False,
    "mongo_connected": False,
    "last_result": None  # Stores result of last email sending
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
    
    for attempt in range(Config.MAX_RETRIES):
        try:
            mongo_client = MongoClient(
                Config.MONGO_URI,
                serverSelectionTimeoutMS=Config.MONGO_TIMEOUT_MS,
                connectTimeoutMS=Config.MONGO_TIMEOUT_MS
            )
            # Test connection
            mongo_client.admin.command('ping')
            db = mongo_client["test"]
            users_col = db["users"]
            service_state["mongo_connected"] = True
            logger.info("MongoDB connected successfully!")
            return True
        except (ConnectionFailure, ServerSelectionTimeoutError) as e:
            logger.warning(f"MongoDB connection attempt {attempt + 1} failed: {e}")
            time.sleep(2)
    
    logger.error("Failed to connect to MongoDB after all retries")
    return False

# Initialize MongoDB on startup
def startup_init():
    """Background initialization to speed up cold starts"""
    init_mongo()
    service_state["is_ready"] = True
    service_state["last_wake_time"] = datetime.now(IST).isoformat()
    logger.info("Service initialization complete")

# Run initialization in background thread
init_thread = threading.Thread(target=startup_init, daemon=True)
init_thread.start()

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
    <a href="https://play.google.com/store/apps/details?id=com.open.talk" style="display: inline-block; background: white; color: #667eea; padding: 10px 20px; border-radius: 25px; text-decoration: none; margin: 5px; font-weight: bold;">📱 Download App</a>
    <a href="https://t.me/AppOpentalk" style="display: inline-block; background: white; color: #667eea; padding: 10px 20px; border-radius: 25px; text-decoration: none; margin: 5px; font-weight: bold;">💬 Telegram</a>
    <a href="https://www.instagram.com/english_speaking_app_official" style="display: inline-block; background: white; color: #667eea; padding: 10px 20px; border-radius: 25px; text-decoration: none; margin: 5px; font-weight: bold;">📸 Instagram</a>
    <a href="https://www.youtube.com/@EnglishSpeakAppOfficial" style="display: inline-block; background: white; color: #667eea; padding: 10px 20px; border-radius: 25px; text-decoration: none; margin: 5px; font-weight: bold;">📺 YouTube</a>
</div>
<p style="text-align: center; color: #999; font-size: 12px; margin-top: 20px;">
    © 2024 Language Speaking App. Made with ❤️ for language learners worldwide.
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
        padding: 40px;
        border-radius: 20px;
        box-shadow: 0 10px 40px rgba(0,0,0,0.1);
    }}
    .header {{
        text-align: center;
        margin-bottom: 30px;
    }}
    .cake-emoji {{
        font-size: 60px;
        display: block;
        margin-bottom: 10px;
    }}
    h2 {{
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-size: 28px;
        margin: 0;
    }}
    .message {{
        font-size: 16px;
        color: #444;
        line-height: 1.8;
        text-align: center;
        padding: 20px;
        background: #f8f9fa;
        border-radius: 15px;
        margin: 20px 0;
    }}
    .footer {{
        margin-top: 30px;
    }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <span class="cake-emoji">🎂</span>
        <h2>Happy Birthday, {username}!</h2>
    </div>
    <div class="message">
        {message}
    </div>
    <div class="footer">
        {footer}
    </div>
</div>
</body>
</html>
"""

# ------------------ Helper Functions ------------------
def get_ist_now():
    """Get current time in IST"""
    return datetime.now(IST)

def require_ready(f):
    """Decorator to ensure service is ready"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Wait up to 30 seconds for service to be ready
        for _ in range(30):
            if service_state["is_ready"]:
                break
            time.sleep(1)
        
        if not service_state["is_ready"]:
            return jsonify({
                "error": "Service is still initializing. Please try again in a few seconds.",
                "status": "initializing"
            }), 503
        
        return f(*args, **kwargs)
    return decorated_function

def get_today_birthdays():
    """Fetch users whose birthday is today (IST)"""
    global users_col
    
    if users_col is None:
        if not init_mongo():
            logger.error("Cannot fetch birthdays - MongoDB not connected")
            return []
    
    today = get_ist_now()
    day = today.day
    month = today.month
    
    logger.info(f"Checking birthdays for {day}/{month} (IST)")
    
    matches = []
    try:
        # Only fetch necessary fields, exclude _id to avoid ObjectId issues
        cursor = users_col.find(
            {"dateOfBirth": {"$exists": True, "$ne": None, "$ne": ""}},
            {"_id": 0, "username": 1, "name": 1, "email": 1, "dateOfBirth": 1}
        )
        
        for user in cursor:
            dob_str = user.get("dateOfBirth", "")
            if not dob_str or not isinstance(dob_str, str):
                continue
                
            try:
                # Try multiple date formats
                dob = None
                for fmt in ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"]:
                    try:
                        dob = datetime.strptime(dob_str.strip(), fmt)
                        break
                    except ValueError:
                        continue
                
                if dob and dob.day == day and dob.month == month:
                    email = user.get("email", "")
                    if email and isinstance(email, str) and "@" in email:
                        # Create a clean dict to avoid any MongoDB-specific types
                        matches.append({
                            "username": str(user.get("username", "")),
                            "name": str(user.get("name", "")),
                            "email": str(email),
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

def send_single_email(sender_email, to_email, username):
    """Send a single birthday email using Resend API"""
    subject = "🎉 Happy Birthday from Language Speaking App!"
    message = random.choice(BIRTHDAY_MESSAGES).replace("{username}", username)
    
    # HTML version
    html_content = HTML_BIRTHDAY_TEMPLATE.format(
        username=username,
        message=message,
        footer=EMAIL_FOOTER
    )
    
    for attempt in range(Config.MAX_RETRIES):
        try:
            params = {
                "from": f"Language Speaking App <{sender_email}>",
                "to": [to_email],
                "subject": subject,
                "html": html_content,
            }
            
            email_response = resend.Emails.send(params)
            
            if email_response and email_response.get("id"):
                return True
            else:
                logger.warning(f"Resend returned no ID for {to_email}")
                
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed for {to_email}: {e}")
            if attempt < Config.MAX_RETRIES - 1:
                time.sleep(1)
    
    return False

def send_email_wishes(users):
    """Send birthday emails to users using Resend API"""
    api_key = Config.RESEND_API_KEY
    sender = Config.SENDER_EMAIL
    
    if not api_key:
        logger.error("RESEND_API_KEY environment variable not configured!")
        return 0, "RESEND_API_KEY not configured"
    
    # Initialize Resend with API key
    resend.api_key = api_key
    
    sent_count = 0
    failed_users = []
    
    # Process in batches
    for i in range(0, len(users), Config.EMAIL_BATCH_SIZE):
        batch = users[i:i + Config.EMAIL_BATCH_SIZE]
        
        for user in batch:
            to_email = user.get("email")
            username = user.get("username") or user.get("name") or "Friend"
            
            if not to_email:
                continue
            
            success = send_single_email(sender, to_email, username)
            
            if success:
                sent_count += 1
                logger.info(f"✅ Sent to {username} ({to_email})")
            else:
                failed_users.append(username)
                logger.error(f"❌ Failed to send to {username} ({to_email})")
        
        # Small delay between batches
        if i + Config.EMAIL_BATCH_SIZE < len(users):
            time.sleep(Config.EMAIL_DELAY_SECONDS)
    
    return sent_count, failed_users

# ------------------ API Routes ------------------

@app.route("/")
def home():
    """Health check endpoint - also wakes up the service"""
    now = get_ist_now()
    service_state["last_wake_time"] = now.isoformat()
    
    return jsonify({
        "status": "ok",
        "service": "OpenTalk Birthday Mail Service",
        "version": "2.0.0",
        "current_time_ist": now.strftime("%Y-%m-%d %H:%M:%S IST"),
        "is_ready": service_state["is_ready"],
        "mongo_connected": service_state["mongo_connected"],
        "last_email_run": service_state["last_email_run"],
        "emails_sent_today": service_state["total_emails_sent_today"]
    })

@app.route("/health")
def health_check():
    """Detailed health check"""
    checks = {
        "service": "ok",
        "mongo": "checking...",
        "resend": "checking..."
    }
    
    # Check MongoDB
    try:
        if mongo_client:
            mongo_client.admin.command('ping')
            checks["mongo"] = "ok"
        else:
            checks["mongo"] = "not initialized"
    except Exception as e:
        checks["mongo"] = f"error: {str(e)}"
    
    # Check Resend API key
    if Config.RESEND_API_KEY:
        checks["resend"] = "configured"
    else:
        checks["resend"] = "not configured"
    
    all_ok = checks["mongo"] == "ok" and checks["resend"] == "configured"
    
    return jsonify({
        "healthy": all_ok,
        "checks": checks,
        "timestamp": get_ist_now().isoformat()
    }), 200 if all_ok else 503

@app.route("/wake")
def wake():
    """Explicit wake endpoint for cron job"""
    now = get_ist_now()
    service_state["last_wake_time"] = now.isoformat()
    
    # Ensure MongoDB is connected and service is ready
    if not service_state["mongo_connected"]:
        if init_mongo():
            service_state["is_ready"] = True
    elif not service_state["is_ready"]:
        # MongoDB connected but is_ready not set (edge case)
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
    """Preview today's birthdays without sending emails"""
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

def send_emails_background(users, timestamp):
    """Background function to send emails without blocking the response"""
    try:
        sent_count, failed = send_email_wishes(users)
        service_state["last_email_run"] = timestamp
        service_state["total_emails_sent_today"] = sent_count
        service_state["last_result"] = {
            "success": True,
            "sent": sent_count,
            "total": len(users),
            "failed": len(failed) if isinstance(failed, list) else 0
        }
        logger.info(f"Background email sending complete: {sent_count}/{len(users)} sent")
    except Exception as e:
        logger.error(f"Background email sending failed: {e}", exc_info=True)
        service_state["last_result"] = {"success": False, "error": str(e)}

@app.route("/send-birthday-emails")
@require_ready
def send_birthday_emails_endpoint():
    """Main endpoint to send birthday emails - responds immediately, sends in background"""
    now = get_ist_now()
    
    # Fetch birthday users
    users = get_today_birthdays()
    
    if not users:
        return jsonify({
            "success": True,
            "message": "No birthdays today.",
            "emails_sent": 0,
            "timestamp": now.isoformat()
        })
    
    logger.info(f"Starting background email sending to {len(users)} users...")
    
    # Start background thread to send emails
    email_thread = threading.Thread(
        target=send_emails_background,
        args=(users.copy(), now.isoformat()),
        daemon=True
    )
    email_thread.start()
    
    # Respond immediately - don't wait for emails to complete
    return jsonify({
        "success": True,
        "message": f"Started sending birthday emails to {len(users)} users in background.",
        "total_users": len(users),
        "status": "processing",
        "timestamp": now.isoformat()
    })

@app.route("/test-email")
@require_ready
def test_email():
    """Send a test email to verify Resend is working"""
    test_email_addr = request.args.get("email")
    
    if not test_email_addr:
        return jsonify({"error": "Please provide ?email=your@email.com"}), 400
    
    api_key = Config.RESEND_API_KEY
    sender = Config.SENDER_EMAIL
    
    if not api_key:
        return jsonify({"error": "RESEND_API_KEY not configured"}), 500
    
    try:
        resend.api_key = api_key
        success = send_single_email(sender, test_email_addr, "Test User")
        
        if success:
            return jsonify({"success": True, "message": f"Test email sent to {test_email_addr}"})
        else:
            return jsonify({"success": False, "message": "Failed to send test email"}), 500
            
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ------------------ Error Handlers ------------------

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500

# ------------------ Main ------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"Starting Birthday Mail Service on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
