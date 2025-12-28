from app import app, db, User
from werkzeug.security import generate_password_hash

with app.app_context():
    admin_email = "admin@example.com"

    existing = User.query.filter_by(email=admin_email).first()
    if existing:
        print("Admin already exists")
    else:
        admin = User(
            fullname="Administrator",
            email=admin_email,
            password=generate_password_hash("admin123"),
            role="admin"
        )
        db.session.add(admin)
        db.session.commit()
        print("Admin created successfully")
        
