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

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# ==================== APP CONFIG ====================
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL", "sqlite:///siwes.db"
)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config["UPLOAD_FOLDER"] = os.path.join(BASE_DIR, "uploads")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"

# ==================== ENV KEYS ====================
PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY")
WHATSAPP_ADMIN = os.environ.get("WHATSAPP_ADMIN", "2348165017875")

# ==================== MODELS ====================
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.String(150), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
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
def load_user(user_id):
    return User.query.get(int(user_id))

# ==================== HELPERS ====================
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            flash("Admin access only")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


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

# ==================== ROUTES ====================
@app.route("/")
def home():
    return render_template("home.html")

# ---------- AUTH ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"]

        if User.query.filter_by(email=email).first():
            flash("Email already registered")
            return redirect(url_for("login"))

        user = User(
            fullname=request.form["fullname"],
            email=email,
            password=generate_password_hash(request.form["password"])
        )
        db.session.add(user)
        db.session.commit()

        flash("Registration successful")
        return redirect(url_for("login"))

    return render_template("auth/register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]

        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password, password):
            flash("Invalid email or password")
            return redirect(url_for("login"))

        login_user(user)
        return redirect(url_for("submit"))

    return render_template("auth/login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

# ---------- STUDENT ----------
@app.route("/submit", methods=["GET", "POST"])
@login_required
def submit():
    if request.method == "POST":
        service = request.form["service"]

        SERVICE_PRICES = {
            "SIWES Placement": 200,
            "Industrial Training Letter": 200
        }

        amount = SERVICE_PRICES.get(service, 200)

        file = request.files["file"]
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        sub = Submission(
            service=service,
            filename=filename,
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
    return render_template("student/track.html", subs=current_user.submissions)


@app.route("/attendance/checkin")
@login_required
def checkin():
    db.session.add(
        Attendance(user_id=current_user.id, day=date.today(), status="Present")
    )
    db.session.commit()
    flash("Attendance recorded")
    return redirect(url_for("track"))

# ---------- WHATSAPP ----------
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

# ---------- PAYSTACK ----------
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

    data = res.json()["data"]

    sub = Submission.query.filter_by(
        user_id=current_user.id,
        paid=False
    ).order_by(Submission.id.desc()).first()

    if data["status"] == "success" and sub:
        sub.paid = True
        sub.status = "Paid"
        sub.reference = reference
        sub.receipt = generate_receipt(sub)
        db.session.commit()
        flash("Payment successful")
    else:
        flash("Payment failed")

    return redirect(url_for("track"))

# ---------- ADMIN ----------
@app.route("/admin")
@login_required
@admin_required
def admin_dashboard():
    total_students = User.query.filter_by(role="student").count()
    total_revenue = db.session.query(
        db.func.sum(Submission.amount)
    ).filter_by(paid=True).scalar() or 0

    return render_template(
        "admin/dashboard.html",
        total_students=total_students,
        total_revenue=total_revenue
    )

# ---------- FILE DOWNLOAD ----------
@app.route("/download/<name>")
@login_required
def download(name):
    return send_from_directory(app.config["UPLOAD_FOLDER"], name, as_attachment=True)

# ==================== RUN ====================
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
