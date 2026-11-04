import os
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent
CLIENT_DIR = PROJECT_DIR / 'client'
load_dotenv(PROJECT_DIR / '.env')

SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-reactxtract-local-development')
DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() in {'1', 'true', 'yes'}
ALLOWED_HOSTS = [item.strip() for item in os.environ.get('DJANGO_ALLOWED_HOSTS', '127.0.0.1,localhost').split(',') if item.strip()]

INSTALLED_APPS = [
    'main.apps.MainConfig',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'main.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [CLIENT_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
    ]},
}]
WSGI_APPLICATION = 'main.wsgi.application'
ASGI_APPLICATION = 'main.asgi.application'

DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'db.sqlite3'}}
AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Manila'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [CLIENT_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = 'media/'
MEDIA_ROOT = PROJECT_DIR / 'media'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
DATA_UPLOAD_MAX_MEMORY_SIZE = 60 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 4 * 1024 * 1024

AI_PDF_CHUNK_PAGES = int(os.environ.get('AI_PDF_CHUNK_PAGES', '10'))
AI_KEYWORD_CONTEXT_PAGES = int(os.environ.get('AI_KEYWORD_CONTEXT_PAGES', '1'))
AI_INPUT_MODE = os.environ.get('AI_INPUT_MODE', 'hybrid').strip().lower()
AI_ADAPTIVE_CHUNKING = os.environ.get('AI_ADAPTIVE_CHUNKING', 'true').strip().lower() in {'1', 'true', 'yes'}
AI_SINGLE_CALL_MAX_PAGES = max(1, int(os.environ.get('AI_SINGLE_CALL_MAX_PAGES', '8')))
AI_SINGLE_CALL_MAX_CHARS = max(1000, int(os.environ.get('AI_SINGLE_CALL_MAX_CHARS', '80000')))
AI_CHUNK_MAX_CHARS = max(1000, int(os.environ.get('AI_CHUNK_MAX_CHARS', '50000')))
AI_CHUNK_OVERLAP_PAGES = max(0, min(2, int(os.environ.get('AI_CHUNK_OVERLAP_PAGES', '1'))))
AI_MAX_PARALLEL_REQUESTS = max(1, min(4, int(os.environ.get('AI_MAX_PARALLEL_REQUESTS', '2'))))
AI_REACTION_DENSE_CHUNK_PAGES = max(1, int(os.environ.get('AI_REACTION_DENSE_CHUNK_PAGES', '2')))
AI_REQUEST_TIMEOUT_SECONDS = max(30, int(os.environ.get('AI_REQUEST_TIMEOUT_SECONDS', '300')))
AI_MAX_RETRIES = max(0, min(2, int(os.environ.get('AI_MAX_RETRIES', '1'))))
AI_REASONING_EFFORT = os.environ.get('AI_REASONING_EFFORT', 'none').strip().lower()
AI_INPUT_COST_PER_MILLION = Decimal(os.environ.get('AI_INPUT_COST_PER_MILLION', '2.00'))
AI_OUTPUT_COST_PER_MILLION = Decimal(os.environ.get('AI_OUTPUT_COST_PER_MILLION', '8.00'))
X_FRAME_OPTIONS = 'SAMEORIGIN'

