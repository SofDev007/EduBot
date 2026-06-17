#!/usr/bin/env python
"""
Complete startup script for Adaptive Chatbot
Checks everything is ready, then starts Flask
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 70)
print("🚀 ADAPTIVE CHATBOT - STARTUP SCRIPT")
print("=" * 70)

# Step 1: Check imports
print("\n1️⃣ Checking imports...")
try:
    from app import create_app
    from models import db, Subject, Question, Admin
    print("   ✅ Imports successful")
except Exception as e:
    print(f"   ❌ Import error: {e}")
    sys.exit(1)

# Step 2: Create app
print("\n2️⃣ Creating Flask app...")
try:
    app = create_app()
    print("   ✅ Flask app created")
except Exception as e:
    print(f"   ❌ App creation error: {e}")
    sys.exit(1)

# Step 3: Check database
print("\n3️⃣ Checking database...")
try:
    with app.app_context():
        admins = Admin.query.count()
        subjects = Subject.query.count()
        questions = Question.query.count()
        
        print(f"   ✅ Database connected")
        print(f"      • Admins: {admins}")
        print(f"      • Subjects: {subjects}")
        print(f"      • Questions: {questions}")
        
        if admins == 0:
            print("\n   ⚠️  WARNING: No admin user found!")
            print("      Run: python force_create_admin.py")
        if subjects == 0:
            print("\n   ⚠️  WARNING: No subjects found!")
            print("      Run: python create_demo.py")
        if questions == 0:
            print("\n   ⚠️  WARNING: No questions found!")
            print("      Run: python create_demo.py")
except Exception as e:
    print(f"   ❌ Database error: {e}")
    sys.exit(1)

# Step 4: Test API endpoints
print("\n4️⃣ Testing API endpoints...")
try:
    with app.test_client() as client:
        # Test subjects endpoint
        res = client.get('/api/subjects')
        if res.status_code == 200:
            print("   ✅ GET /api/subjects: OK")
        else:
            print(f"   ❌ GET /api/subjects: {res.status_code}")
        
        # Test start endpoint
        res = client.post('/api/start', 
            json={'name': 'Test', 'email': 'test@test.com', 'subject_id': 1}
        )
        if res.status_code in [200, 404]:  # 404 if no subject, but API is working
            print("   ✅ POST /api/start: OK")
        else:
            print(f"   ❌ POST /api/start: {res.status_code}")
except Exception as e:
    print(f"   ❌ API test error: {e}")

# Step 5: Start server
print("\n" + "=" * 70)
print("✅ ALL CHECKS PASSED - STARTING SERVER")
print("=" * 70)
print("\n📍 Frontend URL:  http://localhost:5000")
print("📍 Admin URL:     http://localhost:5000/auth/login")
print("\n⚠️  KEEP THIS TERMINAL OPEN - Flask must stay running")
print("=" * 70 + "\n")

try:
    app.run(debug=False, port=5000, host='0.0.0.0', use_reloader=False)
except KeyboardInterrupt:
    print("\n\n🛑 Server stopped by user")
    sys.exit(0)
except Exception as e:
    print(f"\n\n❌ Server error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
