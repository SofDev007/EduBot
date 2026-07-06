from extensions import db, login_manager
from flask_login import UserMixin
from datetime import datetime

@login_manager.user_loader
def load_user(user_id):
    return Admin.query.get(int(user_id))

class Admin(db.Model, UserMixin):
    __tablename__ = 'admins'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    subjects = db.relationship('Subject', backref='admin', lazy=True)

class Subject(db.Model):
    __tablename__ = 'subjects'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=True)
    syllabus_text = db.Column(db.Text, nullable=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('admins.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    questions = db.relationship('Question', backref='subject', lazy=True, cascade='all, delete-orphan')
    sessions = db.relationship('Session', backref='subject', lazy=True, cascade='all, delete-orphan')

class Question(db.Model):
    __tablename__ = 'questions'
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=False, index=True)
    topic = db.Column(db.String(500), nullable=False, index=True)
    difficulty = db.Column(db.Enum('easy', 'hard', name='difficulty_enum'), nullable=False, index=True)
    question_text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(300), nullable=False)
    option_b = db.Column(db.String(300), nullable=False)
    option_c = db.Column(db.String(300), nullable=False)
    option_d = db.Column(db.String(300), nullable=False)
    correct_option = db.Column(db.Enum('A','B','C','D', name='option_enum'), nullable=False)
    responses = db.relationship('Response', backref='question', lazy=True, cascade='all, delete-orphan')
    
    # Composite index for frequently queried combinations
    __table_args__ = (
        db.Index('idx_subject_difficulty', 'subject_id', 'difficulty'),
        db.Index('idx_subject_topic', 'subject_id', 'topic'),
    )

class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True)
    # ← NEW: password_hash for student auth
    password_hash = db.Column(db.String(255), nullable=True)
    # Email verification
    # - None  => legacy/unknown (treated as verified to avoid breaking existing accounts)
    # - False => must verify
    # - True  => verified
    email_verified = db.Column(db.Boolean, nullable=True, default=None)
    email_verified_at = db.Column(db.DateTime, nullable=True)
    email_verification_sent_at = db.Column(db.DateTime, nullable=True)
    # Set True when an admin resets to a temporary password — forces a change at next login.
    must_change_password = db.Column(db.Boolean, default=False, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Session(db.Model):
    __tablename__ = 'sessions'
    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey('subjects.id'), nullable=True, index=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False, index=True)
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.Enum('in_progress', 'completed', name='session_status_enum'), default='in_progress', index=True)
    selected_question_ids = db.Column(db.Text, nullable=True)
    responses = db.relationship('Response', backref='session', lazy=True, cascade='all, delete-orphan')
    weak_topics = db.relationship('WeakTopic', backref='session', lazy=True, cascade='all, delete-orphan')
    
    # Composite index for frequently queried combinations
    __table_args__ = (
        db.Index('idx_student_status', 'student_id', 'status'),
        db.Index('idx_subject_status', 'subject_id', 'status'),
    )

class Response(db.Model):
    __tablename__ = 'responses'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.id'), nullable=False, index=True)
    question_id = db.Column(db.Integer, db.ForeignKey('questions.id'), nullable=False, index=True)
    selected_option = db.Column(db.Enum('A','B','C','D', name='option_enum'), nullable=False)
    is_correct = db.Column(db.Boolean, nullable=False, index=True)
    answered_at = db.Column(db.DateTime, default=datetime.utcnow)

class WeakTopic(db.Model):
    __tablename__ = 'weak_topics'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('sessions.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    topic = db.Column(db.String(100), nullable=False)
    flagged_at = db.Column(db.DateTime, default=datetime.utcnow)

class PasswordResetRequest(db.Model):
    """Raised when a student clicks 'Forgot password?' on the login page.
    Surfaced to the admin in the Issues section so they can reset the password."""
    __tablename__ = 'password_reset_requests'
    id = db.Column(db.Integer, primary_key=True)
    # Linked student if the email matches a registered account (else NULL)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=True, index=True)
    email = db.Column(db.String(255), nullable=False, index=True)
    name = db.Column(db.String(255), nullable=True)
    # pending  => admin still needs to action it
    # resolved => admin has reset the password / closed the issue
    status = db.Column(db.Enum('pending', 'resolved', name='reset_status_enum'), nullable=False, default='pending', index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)
