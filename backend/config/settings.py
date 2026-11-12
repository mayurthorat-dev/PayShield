import sys
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv(
    "SECRET_KEY",
    "django-insecure-j!ai$4(z$_tke_51oxm=6dta!37n_v^ne^1&=k$by5&9n-2o4y",
)

DEBUG = os.getenv("DEBUG", "True").lower() in ["true", "1", "yes"]

ALLOWED_HOSTS = [
    "127.0.0.1",
    "localhost",
    "*",
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",

    # PayShield modules
    "accounts",
    "banking",
    "transactions",
    "risk_engine",
    "authorization",
    "audit",
    "notifications",
]

FIREBASE_SERVICE_ACCOUNT_KEY = BASE_DIR / "firebase_service_account.json"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "accounts.authentication.ExpiringTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

PAYSHIELD_TOKEN_LIFETIME_HOURS = int(os.getenv("PAYSHIELD_TOKEN_LIFETIME_HOURS", "24"))

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
]
try:
    import whitenoise
    MIDDLEWARE.append('whitenoise.middleware.WhiteNoiseMiddleware')
except ImportError:
    pass
MIDDLEWARE.extend([
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
])

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

db_options = {"charset": "utf8mb4"}
if os.getenv("DB_SSL_CA"):
    db_options["ssl"] = {"ca": os.getenv("DB_SSL_CA")}
elif os.getenv("DB_SSL", "").lower() in ["true", "1", "yes"]:
    db_options["ssl"] = {"ssl_mode": "PREFERRED"}

DATABASES = {
    "default": {
        "ENGINE": os.getenv("DB_ENGINE", "django.db.backends.mysql"),
        "NAME": os.getenv("DB_NAME", "payshield_db"),
        "USER": os.getenv("DB_USER", "payshield_user"),
        "PASSWORD": os.getenv("DB_PASSWORD", "PayShield@2026"),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "3306"),
        "OPTIONS": db_options,
    }
}

if "test" in sys.argv:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LANGUAGE_CODE = 'en-us'

TIME_ZONE = "Asia/Kolkata"
USE_TZ = True

USE_I18N = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
