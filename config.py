    #Stores all database connection details in one place
    #If we ever change the database, we only update this one file
    #SECRET_KEY keeps our Flask sessions secure


import os
import secrets
from urllib.parse import quote
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Treat these as "not really set" so we never run on a known/placeholder secret.
_PLACEHOLDER_SECRETS = {
    '', 'adaptive-chatbot-secret-key',
    'your-secret-key-change-this-in-production',
    'CHANGE_ME_GENERATE_A_RANDOM_64_CHAR_HEX_STRING',
}
_IS_PRODUCTION = os.environ.get('FLASK_ENV', 'development').strip().lower() == 'production'


def _resolve_secret_key():
    key = (os.environ.get('SECRET_KEY') or '').strip()
    if key in _PLACEHOLDER_SECRETS:
        if _IS_PRODUCTION:
            # Never silently boot production with a guessable/ephemeral session key.
            raise RuntimeError(
                'SECRET_KEY is missing or set to a placeholder. Set a strong, random '
                'SECRET_KEY in the environment before running in production.'
            )
        # Dev fallback: generate a random per-process key so sessions are not forgeable.
        # (Sessions reset on restart — set SECRET_KEY in .env to keep them stable.)
        print('[CONFIG] WARNING: SECRET_KEY not set; using a random ephemeral key for development.')
        return secrets.token_hex(32)
    return key


class Config:

    SECRET_KEY = _resolve_secret_key()

    # App base URL used when building verification links
    # Example: http://localhost:5000
    APP_BASE_URL = os.environ.get('APP_BASE_URL', 'http://localhost:5000').strip()

    # SMTP settings for email verification (optional; if not set, link will be logged in server console)
    SMTP_HOST = os.environ.get('SMTP_HOST', '').strip()
    SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
    SMTP_USER = os.environ.get('SMTP_USER', '').strip()
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '').strip()
    SMTP_USE_TLS = os.environ.get('SMTP_USE_TLS', 'true').lower() in ('1', 'true', 'yes', 'y')
    MAIL_FROM = os.environ.get('MAIL_FROM', os.environ.get('SMTP_USER', '')).strip()

    # MySQL Database connection (loads from .env)
    MYSQL_HOST = os.environ.get('MYSQL_HOST', 'localhost')
    MYSQL_PORT = int(os.environ.get('MYSQL_PORT', '3306'))
    MYSQL_USER = os.environ.get('MYSQL_USER', 'root')
    # No hardcoded fallback — the DB password must come from the environment.
    MYSQL_PASSWORD = os.environ.get('MYSQL_PASSWORD', '')
    MYSQL_DB = os.environ.get('MYSQL_DB', 'railway')

    # Database Selection: Use SQLite for development, MySQL for production
    # Set DB_TYPE=mysql in .env to use MySQL
    DB_TYPE = os.environ.get('DB_TYPE', 'sqlite').lower()  # Default to SQLite for development
    
    # SQLAlchemy Database URI (Uniform Resource Identifier)
    if DB_TYPE == 'mysql':
        # MySQL configurationalso jarvis where are these apps showed in the apps section in my laptop
        ENCODED_PASSWORD = quote(MYSQL_PASSWORD, safe='')
        SQLALCHEMY_DATABASE_URI = (
            f"mysql+pymysql://{MYSQL_USER}:{ENCODED_PASSWORD}"
            f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
        )
    else:
        # SQLite configuration (default for development)
        SQLALCHEMY_DATABASE_URI = 'sqlite:///edubot.db'
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False

