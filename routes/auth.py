from flask import Blueprint, render_template, redirect, url_for, request, flash, session as flask_session, current_app, jsonify
from flask_login import login_user, logout_user, login_required
from models import Admin, Student, PasswordResetRequest, db
from extensions import bcrypt
from datetime import datetime
import re

try:
    import dns.resolver
    import dns.exception
except Exception:  # pragma: no cover
    dns = None

auth_bp = Blueprint('auth', __name__)


def _password_strength_label(password: str, *, name: str = '', email: str = '') -> str:
    if not password:
        return 'weak'

    # Only allow numbers + upper/lowercase letters
    if not re.fullmatch(r'[A-Za-z0-9]+', password):
        return 'weak'

    length = len(password)
    has_lower = any(c.islower() for c in password)
    has_upper = any(c.isupper() for c in password)
    has_digit = any(c.isdigit() for c in password)
    categories = sum([has_lower, has_upper, has_digit])

    lowered = password.lower()
    common = (
        'password', 'passw0rd', '123456', '12345678', 'qwerty', 'admin', 'letmein',
        'welcome', 'iloveyou', '111111', '000000'
    )
    if any(w in lowered for w in common):
        return 'weak'

    if any(ch.isspace() for ch in password):
        return 'weak'

    if email:
        local = email.split('@', 1)[0].strip().lower()
        if local and len(local) >= 3 and local in lowered:
            return 'weak'

    if name:
        for part in re.split(r'\s+', name.strip().lower()):
            if len(part) >= 3 and part in lowered:
                return 'weak'

    if length >= 8 and categories == 3:
        return 'strong'
    if length >= 8 and categories == 2:
        return 'medium'
    return 'weak'


def _email_domain_is_deliverable(email: str) -> bool:
    """Best-effort check that an email domain can receive mail.

    This does NOT guarantee the mailbox exists, but it catches obvious typos like
    `user@gmial.con` by verifying DNS records (MX, or A as fallback).
    """

    if not email or '@' not in email:
        return False

    # Minimal format sanity (HTML already uses type=email; we enforce server-side too)
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        return False

    domain = email.split('@', 1)[1].strip().lower().rstrip('.')
    if not domain:
        return False

    # If dnspython isn't installed yet, avoid crashing the app.
    # In this case we fall back to format-only checks.
    if dns is None:
        print('[Email Check] dnspython not installed; skipping DNS deliverability check')
        return True

    try:
        answers = dns.resolver.resolve(domain, 'MX')
        return bool(list(answers))
    except Exception:
        # Fallback: if there's at least an A record, the domain may still accept mail.
        try:
            answers = dns.resolver.resolve(domain, 'A')
            return bool(list(answers))
        except Exception:
            return False


# ─────────────────────────────────────────
# UNIFIED LOGIN PAGE — GET
# Handles both student and admin login display
# ─────────────────────────────────────────
@auth_bp.route('/login', methods=['GET'])
def login():
    # If student already logged in, redirect to chatbot
    if flask_session.get('student_id'):
        return redirect('/')
    return render_template('login.html')


# ─────────────────────────────────────────
# ADMIN LOGIN — POST to /auth/login
# ─────────────────────────────────────────
@auth_bp.route('/login', methods=['POST'])
def login_post():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')

    if not username or not password:
        flash('Please enter both username and password.', 'danger')
        return redirect(url_for('auth.login') + '?role=admin')

    admin = Admin.query.filter_by(username=username).first()
    if admin and bcrypt.check_password_hash(admin.password_hash, password):
        login_user(admin)
        return redirect(url_for('admin.dashboard'))

    flash('Invalid username or password.', 'danger')
    return redirect(url_for('auth.login') + '?role=admin')


# ─────────────────────────────────────────
# STUDENT LOGIN — POST to /auth/student-login
# ─────────────────────────────────────────
@auth_bp.route('/student-login', methods=['POST'])
def student_login():
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')

    # Basic validation
    if not email or not password:
        flash('Please enter your email and password.', 'danger')
        return redirect(url_for('auth.login'))

    student = Student.query.filter_by(email=email).first()

    if not student:
        flash('No account found with this email. Please register first.', 'danger')
        return redirect(url_for('auth.login') + '?register=1')

    if not student.password_hash:
        flash('Your account needs a password. Please register to set one.', 'danger')
        return redirect(url_for('auth.login') + '?register=1')

    if not bcrypt.check_password_hash(student.password_hash, password):
        flash('Incorrect password. Please try again.', 'danger')
        return redirect(url_for('auth.login'))

    # Success — store in session
    flask_session.permanent = True
    flask_session['student_id'] = student.id
    flask_session['student_name'] = student.name
    flask_session['student_email'] = student.email

    # If this was a temporary (admin-reset) password, force a change first
    if student.must_change_password:
        flask_session['must_change_password'] = True
        return redirect(url_for('auth.change_password'))
    flask_session.pop('must_change_password', None)
    return redirect('/')


# ─────────────────────────────────────────
# CHANGE PASSWORD — GET form + POST update (for logged-in students)
# Compulsory for temp-password users; voluntary for everyone else.
# ─────────────────────────────────────────
@auth_bp.route('/change-password', methods=['GET', 'POST'])
def change_password():
    student_id = flask_session.get('student_id')
    if not student_id:
        return redirect(url_for('auth.login'))
    student = Student.query.get(student_id)
    if not student:
        flask_session.clear()
        return redirect(url_for('auth.login'))

    compulsory = bool(student.must_change_password)

    if request.method == 'POST':
        new_pw = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')

        if new_pw != confirm:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('auth.change_password'))

        label = _password_strength_label(new_pw, name=student.name, email=student.email)
        if label == 'weak':
            flash('Password too weak — use 8+ characters with letters and numbers (no spaces or common words).', 'danger')
            return redirect(url_for('auth.change_password'))

        # Don't allow reusing the current/temporary password
        if student.password_hash and bcrypt.check_password_hash(student.password_hash, new_pw):
            flash('Your new password must be different from your current password.', 'danger')
            return redirect(url_for('auth.change_password'))

        student.password_hash = bcrypt.generate_password_hash(new_pw).decode('utf-8')
        student.must_change_password = False
        db.session.commit()
        flask_session.pop('must_change_password', None)
        flash('Password updated successfully!', 'success')
        return redirect('/')

    return render_template('change_password.html', compulsory=compulsory, student_name=student.name)


# ─────────────────────────────────────────
# STUDENT REGISTER — POST to /auth/student-register
# ─────────────────────────────────────────
@auth_bp.route('/student-register', methods=['POST'])
def student_register():
    name = request.form.get('name', '').strip()
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    confirm = request.form.get('confirm_password', '')

    # Validate all fields
    if not name or not email or not password or not confirm:
        flash('All fields are required.', 'danger')
        return redirect(url_for('auth.login') + '?register=1')

    if not _email_domain_is_deliverable(email):
        flash('Please enter a valid, deliverable email address (check the domain).', 'danger')
        return redirect(url_for('auth.login') + '?register=1')

    strength = _password_strength_label(password, name=name, email=email)
    if strength == 'weak':
        flash('Password must be at least MEDIUM strength (8+ chars with letters and numbers).', 'danger')
        return redirect(url_for('auth.login') + '?register=1')

    if password != confirm:
        flash('Passwords do not match. Please try again.', 'danger')
        return redirect(url_for('auth.login') + '?register=1')

    # Check if email already exists
    existing = Student.query.filter_by(email=email).first()

    if existing:
        if existing.password_hash:
            # Account with password exists — tell them to login
            flash('An account with this email already exists. Please sign in instead.', 'danger')
            return redirect(url_for('auth.login'))
        else:
            # Account exists but no password (old quiz-only entry) — upgrade it
            existing.name = name
            existing.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
            db.session.commit()
            flask_session.permanent = True
            flask_session['student_id'] = existing.id
            flask_session['student_name'] = existing.name
            flask_session['student_email'] = existing.email
            return redirect('/')

    # Create brand new student account
    try:
        hashed_pw = bcrypt.generate_password_hash(password).decode('utf-8')
        student = Student(name=name, email=email, password_hash=hashed_pw)
        db.session.add(student)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash('Registration failed due to a server error. Please try again.', 'danger')
        return redirect(url_for('auth.login') + '?register=1')

    flask_session.permanent = True
    flask_session['student_id'] = student.id
    flask_session['student_name'] = student.name
    flask_session['student_email'] = student.email

    return redirect('/')


# ─────────────────────────────────────────
# STUDENT LOGOUT
# ─────────────────────────────────────────
@auth_bp.route('/student-logout')
def student_logout():
    flask_session.pop('student_id', None)
    flask_session.pop('student_name', None)
    flask_session.pop('student_email', None)
    return redirect(url_for('auth.login'))


# ─────────────────────────────────────────
# ADMIN LOGOUT
# ─────────────────────────────────────────
@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


# ─────────────────────────────────────────
# STUDENT FORGOT PASSWORD
# ─────────────────────────────────────────
@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'GET':
        return render_template('forgot_password.html')

    # POST: Handle forgot password request.
    # Supports BOTH the classic page form AND the AJAX popup on the login page.
    wants_json = request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.is_json:
        email = (request.json.get('email') or '').strip().lower()
    else:
        email = request.form.get('email', '').strip().lower()

    if not email:
        if wants_json:
            return jsonify({'success': False, 'message': 'Please enter your email address.'}), 400
        flash('Please enter your email address.', 'danger')
        return redirect(url_for('auth.forgot_password'))

    # Link to a registered account if the email matches one
    student = Student.query.filter_by(email=email).first()

    # ── Raise an "issue" for the admin (Issues section) ──
    # De-dupe: if there's already a pending request for this email, just refresh it
    # instead of stacking duplicates.
    try:
        existing = PasswordResetRequest.query.filter_by(email=email, status='pending').first()
        if existing:
            existing.created_at = datetime.utcnow()
            if student:
                existing.student_id = student.id
                existing.name = student.name
        else:
            req = PasswordResetRequest(
                email=email,
                student_id=student.id if student else None,
                name=student.name if student else None,
                status='pending',
            )
            db.session.add(req)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[Forgot Password] Could not record request: {e}")

    # Log the forgot password request to the server console as well
    print(f"\n{'='*60}")
    print(f"🔐 FORGOT PASSWORD REQUEST")
    print(f"{'='*60}")
    print(f"Student: {student.name if student else '(no matching account)'}")
    print(f"Email: {email}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"\n👉 Admin Action Required:")
    print(f"   1. Open the Admin panel → Issues")
    print(f"   2. Click the request to jump to that student")
    print(f"   3. Reset their password and share the temporary one")
    print(f"{'='*60}\n")

    msg = 'A message has been sent to the admin for your password recovery.'
    if wants_json:
        return jsonify({'success': True, 'message': msg})

    flash('If an account exists with this email, your admin has been notified. Please check your messages.', 'success')
    return redirect(url_for('auth.login'))
