#!/usr/bin/env python
"""
Script to create an admin user for the Adaptive Chatbot
Run this once to set up your first admin account
"""

import sys
import os
import secrets

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app import create_app
    from models import db, Admin
    from extensions import bcrypt

    print("🚀 Creating admin user...\n")

    app = create_app()
    with app.app_context():
        # Check if admin already exists
        existing_admin = Admin.query.filter_by(username='admin').first()
        if existing_admin:
            print("❌ Admin user 'admin' already exists!")
            print("\n✅ Login at: http://localhost:5000/auth/login")
            print("   Username: admin")
            print("   (If you forgot the password, delete the admin row and re-run this script.)")
            sys.exit(0)

        # Password comes from the ADMIN_PASSWORD env var, or is randomly generated
        # and shown ONCE here. Never ship a hardcoded default password.
        password = os.environ.get('ADMIN_PASSWORD', '').strip()
        generated = False
        if not password:
            password = secrets.token_urlsafe(12)
            generated = True

        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')

        admin = Admin(
            username='admin',
            password_hash=hashed_pw
        )

        db.session.add(admin)
        db.session.commit()

        print("✅ SUCCESS! Admin user created!\n")
        print("═" * 50)
        print("📧 LOGIN CREDENTIALS:")
        print("═" * 50)
        print(f"URL:      http://localhost:5000/auth/login")
        print(f"Username: admin")
        if generated:
            print(f"Password: {password}")
            print("⚠️  This password is shown ONCE. Save it now and change it after login.")
        else:
            print("Password: (the value you set in ADMIN_PASSWORD)")
        print("═" * 50)
        print("\n📝 Next Steps:")
        print("1. Go to http://localhost:5000/auth/login")
        print("2. Enter username and password above")
        print("3. Click 'Create Subject' to add your first subject")
        print("4. Upload syllabus for that subject")
        print("5. Students can then select and take the quiz!")
        
except Exception as e:
    print(f"❌ ERROR: {str(e)}")
    print("\nTroubleshooting:")
    print("1. Make sure Flask server is running in another terminal")
    print("2. Make sure you're in the correct directory")
    print("3. Run: python create_admin.py")
    sys.exit(1)
