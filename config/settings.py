import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
IS_RENDER = os.getenv('RENDER') == 'true'
DEBUG = os.getenv('DJANGO_DEBUG', '0' if IS_RENDER else '1') == '1'
LOCAL_ADMIN_ENABLED = DEBUG
DEMO_MODE = os.getenv('DEMO_MODE', '1' if DEBUG else '0') == '1'
DEMO_EPHEMERAL = os.getenv('DEMO_EPHEMERAL', '0') == '1'
if IS_RENDER and DEBUG:
    raise ImproperlyConfigured('Debug must be disabled on Render.')
if DEMO_EPHEMERAL and not DEMO_MODE:
    raise ImproperlyConfigured('Temporary storage is restricted to fictional demonstration mode.')
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'local-demo-only-do-not-deploy-this-key')
if not DEBUG and (SECRET_KEY.startswith('local-demo') or len(SECRET_KEY) < 50):
    raise ImproperlyConfigured('A private DJANGO_SECRET_KEY of at least 50 characters is required.')
ALLOWED_HOSTS = os.getenv('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',')
RENDER_HOSTNAME = os.getenv('RENDER_EXTERNAL_HOSTNAME', '') if IS_RENDER else ''
if RENDER_HOSTNAME:
    if not RENDER_HOSTNAME.endswith('.onrender.com') or '/' in RENDER_HOSTNAME or ':' in RENDER_HOSTNAME:
        raise ImproperlyConfigured('Invalid Render hostname.')
    ALLOWED_HOSTS.append(RENDER_HOSTNAME)
INSTALLED_APPS = ['django.contrib.admin', 'django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions', 'django.contrib.messages', 'django.contrib.staticfiles', 'core', 'catalog', 'care', 'followup', 'qualification']
INSTALLED_APPS += ['django_otp', 'django_otp.plugins.otp_totp']
MFA_REQUIRED = os.getenv('MFA_REQUIRED', '0' if DEMO_MODE else '1') == '1'
PRODUCT_NAME = 'Nehedrou'
OTP_TOTP_ISSUER = PRODUCT_NAME
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware', 'django.middleware.locale.LocaleMiddleware', 'django.middleware.common.CommonMiddleware', 'django.middleware.csrf.CsrfViewMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware', 'core.middleware.AccessMiddleware', 'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware']
MIDDLEWARE.insert(MIDDLEWARE.index('core.middleware.AccessMiddleware'), 'django_otp.middleware.OTPMiddleware')
MIDDLEWARE.insert(MIDDLEWARE.index('core.middleware.AccessMiddleware') + 1, 'core.security.MFAMiddleware')
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
MEDIA_ROOT = Path(os.getenv('NEHEDROU_MEDIA_ROOT', str(BASE_DIR / 'editorial_uploads')))
if not MEDIA_ROOT.is_absolute():
    raise ImproperlyConfigured('NEHEDROU_MEDIA_ROOT must be an absolute private directory.')
MEDIA_STORAGE_DURABLE = os.getenv('NEHEDROU_MEDIA_DURABLE', '0') == '1'

DATA_UPLOAD_MAX_MEMORY_SIZE = 20 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND': 'django.template.backends.django.DjangoTemplates', 'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True, 'OPTIONS': {'context_processors': ['django.template.context_processors.request', 'django.contrib.auth.context_processors.auth', 'django.contrib.messages.context_processors.messages', 'core.context.navigation']}}]
WSGI_APPLICATION = 'config.wsgi.application'
if os.getenv('POSTGRES_HOST'):
    DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'HOST': os.environ['POSTGRES_HOST'], 'PORT': os.getenv('POSTGRES_PORT', '5432'), 'NAME': os.getenv('POSTGRES_DB', 'nehdrou'), 'USER': os.getenv('POSTGRES_USER', 'nehdrou'), 'PASSWORD': os.environ['POSTGRES_PASSWORD'], 'CONN_MAX_AGE': 60, 'CONN_HEALTH_CHECKS': True, 'DISABLE_SERVER_SIDE_CURSORS': '-pooler.' in os.environ['POSTGRES_HOST']}}
else:
    if not DEBUG and not (DEMO_MODE and DEMO_EPHEMERAL):
        raise ImproperlyConfigured('Production requires PostgreSQL.')
    demo_database = Path(os.environ['DEMO_DATABASE_PATH']) if DEMO_EPHEMERAL and os.getenv('DEMO_DATABASE_PATH') else BASE_DIR / 'demo.sqlite3'
    # Acquire the write reservation before reads, avoiding DEFERRED lock upgrades.
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': demo_database, 'OPTIONS': {'timeout': 20, 'transaction_mode': 'IMMEDIATE'}}}
if os.getenv('POSTGRES_SSLMODE') and DATABASES['default']['ENGINE'].endswith('postgresql'):
    mode = os.environ['POSTGRES_SSLMODE']
    if mode not in ['require', 'verify-ca', 'verify-full']:
        raise ImproperlyConfigured('Choose an authenticated/encrypted PostgreSQL SSL mode.')
    DATABASES['default']['OPTIONS'] = {'sslmode':mode}
AUTH_USER_MODEL = 'core.User'
AUTH_PASSWORD_VALIDATORS = [{'NAME': 'django.contrib.auth.password_validation.' + name} for name in ['UserAttributeSimilarityValidator', 'MinimumLengthValidator', 'CommonPasswordValidator', 'NumericPasswordValidator']]
LANGUAGE_CODE = 'fr'
LANGUAGES = [('fr', 'Français'), ('en', 'English'), ('ar', 'العربية')]
LOCALE_PATHS = [BASE_DIR / 'locale']
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage' if not DEBUG else 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}
# Optional private S3-compatible uploads; static assets continue through WhiteNoise.
MEDIA_STORAGE_BACKEND = os.getenv('NEHEDROU_MEDIA_BACKEND', 'filesystem')
if MEDIA_STORAGE_BACKEND not in ['filesystem', 's3']:
    raise ImproperlyConfigured('Choose filesystem or s3 for private media.')
if MEDIA_STORAGE_BACKEND == 's3':
    from urllib.parse import urlsplit
    names = ['NEHEDROU_S3_BUCKET', 'AWS_ENDPOINT_URL_S3', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_REGION']
    if not all(os.getenv(name) for name in names):
        raise ImproperlyConfigured('Private object storage requires all five server-side settings.')
    endpoint = urlsplit(os.environ['AWS_ENDPOINT_URL_S3'])
    if endpoint.scheme != 'https' or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or endpoint.path not in ['', '/']:
        raise ImproperlyConfigured('Private storage requires a clean HTTPS endpoint.')
    from botocore.config import Config
    storage_client_config = Config(signature_version='s3v4', s3={'addressing_style':'path'},
        connect_timeout=5, read_timeout=10, retries={'max_attempts':2,'mode':'standard'},
        request_checksum_calculation='when_required', response_checksum_validation='when_required')
    STORAGES['default'] = {'BACKEND': 'storages.backends.s3.S3Storage', 'OPTIONS': {
        'bucket_name': os.environ['NEHEDROU_S3_BUCKET'],
        'endpoint_url': os.environ['AWS_ENDPOINT_URL_S3'],
        'access_key': os.environ['AWS_ACCESS_KEY_ID'],
        'secret_key': os.environ['AWS_SECRET_ACCESS_KEY'],
        'region_name': os.environ['AWS_REGION'],
        'addressing_style': 'path', 'signature_version': 's3v4', 'client_config':storage_client_config,
        'default_acl': None, 'querystring_auth': True, 'querystring_expire': 60,
        'file_overwrite': False, 'max_memory_size': 2 * 1024 * 1024,
        'object_parameters': {'CacheControl': 'private, no-store'},
    }}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'home'
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', '1') == '1'
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'access@nehdrou.example')
PUBLIC_ORIGIN = os.getenv('PUBLIC_ORIGIN', 'https://' + RENDER_HOSTNAME if RENDER_HOSTNAME else 'http://127.0.0.1:8000')
if IS_RENDER:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 60 * 60 * 8
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

