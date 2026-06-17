#!/usr/bin/env python
"""
Script to initialize the database and create all tables
Run this ONCE before using the application
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from app import create_app
    from models import db
    
    print("🚀 Initializing database...\n")
    
    app = create_app()
    with app.app_context():
        print("📦 Creating all tables...")
        db.create_all()
        print("✅ Database tables created successfully!\n")
        
        print("═" * 50)
        print("✅ DATABASE INITIALIZED!")
        print("═" * 50)
        print("\n📝 Next Steps:")
        print("1. Run: python create_admin.py  (creates the admin & prints its password once)")
        print("2. Go to http://localhost:5000/auth/login and sign in as admin")
        print("3. Create your first subject")
        print("4. Upload syllabus to generate questions")
        print("\nThen students can take the quiz at:")
        print("   http://localhost:5000")
        
except Exception as e:
    print(f"❌ ERROR: {str(e)}")
    print("\nTroubleshooting:")
    print("1. Make sure Flask server is NOT running")
    print("2. Check database credentials in config.py")
    print("3. Make sure MySQL is running and accessible")
    import traceback
    traceback.print_exc()
    sys.exit(1)
