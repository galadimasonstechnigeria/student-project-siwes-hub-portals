# ==================== IMPORTS ====================
import os
import smtplib
import urllib.parse
import requests
from email.message import EmailMessage
from functools import wraps
from datetime import date

from flask import (
    Flask, render_template, redirect,
    url_for, request, flash, send_from_directory
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user,
    login_required, logout_user, current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from twilio.rest import Client
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# ==================== CONFIG ====================
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///siwes.db"
)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, "uploads")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

# ==================== KEYS ====================
PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY")

SMTP_EMAIL = os.environ.get("SMTP_EMAIL")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")

TWILIO_SID = os.environ.get("TWILIO_SID")
TWILIO_TOKEN = os.environ.get("TWILIO_TOKEN")
TWILIO_PHONE = os.environ.get("TWILIO_PHONE")

WHATSAPP_ADMIN = os.environ.get("WHATSAPP_ADMIN", "2348165017875")

# ==================== HELPERS ====================
def send_email(to, subject, template, **context):
if not SMTP_EMAIL or not SMTP_PASSWORD:
    print("Email not configured")
    return
    
    msg = EmailMessage()
    msg["From"] = SMTP_EMAIL
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(render_template(template, **context), subtype="html")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)


def send_sms(to, body):
    if not TWILIO_SID:
        return
    Client(TWILIO_SID, TWILIO_TOKEN).messages.create(
        body=body,
        from_=TWILIO_PHONE,
        to=to
    )


def generate_receipt(submission):
    filename = f"receipt_{submission.id}.pdf"
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)

    c = canvas.Canvas(path, pagesize=A4)
    c.drawString(100, 800, "SIWES HUB PAYMENT RECEIPT")
    c.drawString(100, 760, f"Student: {submission.user.fullname}")
    c.drawString(100, 740, f"Email: {submission.user.email}")
    c.drawString(100, 720, f"Service: {submission.service}")
    c.drawString(100, 700, f"Amount: ₦{submission.amount}")
    c.drawString(100, 680, "Status: PAID")
    c.save()

    return filename

# ==================== MODELS ====================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.String(150))
    email = db.Column(db.String(150), unique=True)
    password = db.Column(db.String(255))
    role = db.Column(db.String(20), default="student")

    submissions = db.relationship("Submission", backref="user", lazy=True)


class Submission(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    service = db.Column(db.String(100))
    filename = db.Column(db.String(200))
    status = db.Column(db.String(50), default="Pending")
    amount = db.Column(db.Integer, default=200)
    paid = db.Column(db.Boolean, default=False)
    receipt = db.Column(db.String(200))
    reference = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=db.func.now())
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))


class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    day = db.Column(db.Date)
    status = db.Column(db.String(20))


@login_manager.user_loader
def load_user(uid):
    return db.session.get(User, int(uid))

# ==================== ACCESS CONTROL ====================
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            flash("Admin only")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated
    
# ==================== HOME ====================
@app.route("/")
def home():
    return render_template("home.html")


# ==================== Login ====================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        user = User.query.filter_by(email=email).first()

      if user and check_password_hash(user.password, data.get("password")):
            flash("Invalid email or password")
            return redirect(url_for("login"))

        login_user(user)
        return redirect(url_for("submit"))

    return render_template("auth/login.html")
    
# ==================== AUTH ====================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]

        # CHECK IF USER EXISTS
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash("Email already registered. Please login.")
            return redirect(url_for("login"))

        user = User(
            fullname=request.form["fullname"],
            email=email,
            password=generate_password_hash(request.form["password"]),
            role="student"
        )
        db.session.add(user)
        db.session.commit()

        flash("Registration successful. Please login.")
        return redirect(url_for("login"))

    return render_template("auth/register.html")
    
# ==================== STUDENT ====================
@app.route("/submit", methods=["GET", "POST"])
@login_required
def submit():
    if request.method == "POST":
        service = request.form["service"]

        SERVICE_PRICES = {
            "SIWES Placement": 200,
            "PROJECT PROPOSAL/PROJECT BIDING": 200,
        }

        amount = SERVICE_PRICES.get(service, 200)

        f = request.files["file"]
        name = secure_filename(f.filename)
        f.save(os.path.join(app.config["UPLOAD_FOLDER"], name))

        sub = Submission(
            service=service,
            filename=name,
            amount=amount,
            user=current_user
        )
        db.session.add(sub)
        db.session.commit()

        return redirect(url_for("whatsapp_redirect", sid=sub.id))

    return render_template("student/submit.html")

@app.route("/track")
@login_required
def track():
    return render_template(
        "student/track.html",
        subs=current_user.submissions
    )


@app.route("/attendance/checkin")
@login_required
def checkin():
    db.session.add(
        Attendance(user_id=current_user.id, day=date.today(), status="Present")
    )
    db.session.commit()
    flash("Attendance recorded")
    return redirect(url_for("track"))

# ==================== WHATSAPP ====================
@app.route("/whatsapp/<int:sid>")
@login_required
def whatsapp_redirect(sid):
    s = Submission.query.get_or_404(sid)
    msg = f"""
NEW SIWES SUBMISSION

Student: {s.user.fullname}
Service: {s.service}
Amount: ₦{s.amount}
"""
    return redirect(
        f"https://wa.me/{WHATSAPP_ADMIN}?text={urllib.parse.quote(msg)}"
    )

# ==================== PAYSTACK ====================
@app.route("/payment/verify")
@login_required
def payment_verify():
    reference = request.args.get("reference")

    if not reference:
        flash("Invalid payment reference")
        return redirect(url_for("track"))

    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
    res = requests.get(
        f"https://api.paystack.co/transaction/verify/{reference}",
        headers=headers
    )

    if res.status_code != 200:
        flash("Payment verification failed")
        return redirect(url_for("track"))

    data = res.json().get("data")

    sub = Submission.query.filter_by(
        user_id=current_user.id,
        paid=False
    ).order_by(Submission.id.desc()).first()

    if not sub:
        flash("No pending submission found")
        return redirect(url_for("track"))

    if data["status"] == "success":
        sub.paid = True
        sub.status = "Paid"
        sub.reference = reference
        sub.receipt = generate_receipt(sub)
        db.session.commit()
        flash("Payment successful")
    else:
        flash("Payment failed")

    return redirect(url_for("track"))

# ==================== ADMIN ====================
@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    total_students = User.query.filter_by(role="student").count()
    total_revenue = db.session.query(
        db.func.sum(Submission.amount)
    ).filter_by(paid=True).scalar() or 0
    total_payments = Submission.query.filter_by(paid=True).count()

    return render_template(
        "admin/dashboard.html",
        total_students=total_students,
        total_revenue=total_revenue,
        total_payments=total_payments
    )

# ==================== FILES ====================
@app.route("/download/<name>")
@login_required
def download(name):
    return send_from_directory(app.config["UPLOAD_FOLDER"], name, as_attachment=True)

# ==================== MOBILE API ====================

@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()

    if not data:
        return {"status": "error", "message": "No data"}, 400

    user = User.query.filter_by(email=data.get("email")).first()

    if user and check_password_hash(user.password, data.get("password")):
        return {
            "status": "success",
            "user": {
                "id": user.id,
                "fullname": user.fullname,
                "role": user.role
            }
        }

    return {"status": "error", "message": "Invalid credentials"}, 401


@app.route("/api/submissions/<int:user_id>")
def api_submissions(user_id):
    subs = Submission.query.filter_by(user_id=user_id).all()

    return {
        "submissions": [
            {
                "id": s.id,
                "service": s.service,
                "status": s.status,
                "amount": s.amount,
                "paid": s.paid
            }
            for s in subs
        ]
    }


# ==================== RUN ====================
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        app.run(debug=True, host="127.0.0.1", port=5000)

        
