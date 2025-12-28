from app import app, db, User
from werkzeug.security import generate_password_hash

with app.app_context():
    admin = User(
        fullname="Admin",
        email="admin@siwes.com",
        password=generate_password_hash("admin123"),
        role="admin"
    )
    db.session.add(admin)
    db.session.commit()
    print("Admin created")
    
