from flask import Flask, render_template, redirect, url_for, session as flask_session
from flask_cors import CORS
from config import Config
from extensions import db, bcrypt, login_manager
from timezone_utils import format_time_short, format_time_long, format_date_only
import os
import socket
from datetime import timedelta


def _lan_ip():
    """Best-effort LAN IP of this machine so QR codes resolve from other devices
    on the same network (instead of 127.0.0.1, which is the phone's own loopback)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Reload templates from disk on every request even when debug is OFF, so
    # HTML/CSS edits show up without a restart. This does NOT enable the
    # Werkzeug debugger (the RCE risk) — only template hot-reloading.
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.jinja_env.auto_reload = True

    # Ensure session works reliably
    app.config['SESSION_TYPE'] = 'filesystem'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    # Only send the session cookie over HTTPS in production (FLASK_ENV=production).
    # Left off in dev so http://localhost still works.
    is_production = os.environ.get('FLASK_ENV', 'development').strip().lower() == 'production'
    app.config['SESSION_COOKIE_SECURE'] = is_production

    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    # CORS: only allow the origins you explicitly trust. Set CORS_ORIGINS in .env
    # as a comma-separated list (e.g. https://edubot.example.com). Defaults to the
    # app's own base URL so the wildcard "*" is never used.
    cors_origins_raw = os.environ.get(
        'CORS_ORIGINS',
        os.environ.get('APP_BASE_URL', 'http://localhost:5000')
    )
    allowed_origins = [o.strip() for o in cors_origins_raw.split(',') if o.strip()]
    CORS(app, resources={r"/api/*": {"origins": allowed_origins}}, supports_credentials=True)

    # ── Security headers on every response ────────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        # Prevent clickjacking
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        # Stop MIME-type sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        # Limit referrer leakage
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        # Content Security Policy. Templates use some inline styles/scripts and a
        # couple of CDNs, so we allow 'unsafe-inline' for those but lock down the
        # rest. Tighten further by moving inline JS/CSS into static files.
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline' https:; "
            "script-src 'self' 'unsafe-inline' https:; "
            "font-src 'self' data: https:; "
            "connect-src 'self' https:; "
            "frame-ancestors 'self'"
        )
        # Only advertise HSTS when actually serving over HTTPS in production.
        if is_production:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response
    
    # Add timezone filters for templates
    app.jinja_env.filters['format_time_short'] = format_time_short
    app.jinja_env.filters['format_time_long'] = format_time_long
    app.jinja_env.filters['format_date_only'] = format_date_only

    from routes.auth import auth_bp
    from routes.admin import admin_bp
    from routes.api import api_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(api_bp, url_prefix='/api')

    # Ensure any newly added tables exist (e.g. password_reset_requests).
    # create_all() only creates MISSING tables, so existing data is untouched.
    with app.app_context():
        import sys, traceback as _tb
        db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
        db_kind = 'PostgreSQL' if db_uri.startswith('postgresql') else ('MySQL' if db_uri.startswith('mysql') else 'SQLite')
        sys.stderr.write(f"[DB] Connecting to: {db_kind}\n")
        sys.stderr.flush()
        try:
            db.create_all()
            sys.stderr.write("[DB] create_all OK\n")
            sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(f"[DB] create_all FAILED: {e}\n")
            _tb.print_exc(file=sys.stderr)
            sys.stderr.flush()

        # Lightweight migration: add students.must_change_password if missing
        # (create_all() never ALTERs existing tables). Works on SQLite + MySQL.
        try:
            from sqlalchemy import inspect, text
            cols = [c['name'] for c in inspect(db.engine).get_columns('students')]
            if 'must_change_password' not in cols:
                with db.engine.begin() as conn:
                    conn.execute(text('ALTER TABLE students ADD COLUMN must_change_password BOOLEAN DEFAULT 0'))
                sys.stderr.write('[DB] Added students.must_change_password column\n')
                sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(f"[DB] must_change_password migration skipped: {e}\n")
            sys.stderr.flush()

    # Root route — student chatbot (requires student login)
    @app.route('/', methods=['GET'])
    def serve_edubot():
        if not flask_session.get('student_id'):
            return redirect(url_for('auth.login'))
        # Force temp-password users to set a new password before using the app
        if flask_session.get('must_change_password'):
            return redirect(url_for('auth.change_password'))

        student_name = flask_session.get('student_name', '')
        student_email = flask_session.get('student_email', '')
        return render_template('edubot.html',
                               student_name=student_name,
                               student_email=student_email,
                               server_host=_lan_ip())

    # Public certificate page — opened by scanning the QR on a phone (no login).
    @app.route('/certificate', methods=['GET'])
    def serve_certificate():
        return render_template('certificate.html')

    return app


if __name__ == '__main__':
    app = create_app()
    print("=" * 60)
    print("🚀 EduBot Flask Server")
    print("=" * 60)
    print("📍 Student portal: http://localhost:5000")
    print("🔧 Admin portal:   http://localhost:5000/auth/login?role=admin")
    print("=" * 60)
    # debug is OFF unless FLASK_DEBUG is truthy in .env — the Werkzeug debugger
    # allows remote code execution, so it must never be on in production.
    debug_mode = os.environ.get('FLASK_DEBUG', '0').strip().lower() in ('1', 'true', 'yes', 'on')
    app.run(debug=debug_mode, port=5000, host='0.0.0.0')
