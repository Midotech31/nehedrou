"""Private storage configuration; no connection to an external bucket."""
import json, os, subprocess, sys
from django.conf import settings
from django.test import SimpleTestCase

class PrivateStorageSettingsTests(SimpleTestCase):
    def load(self, **extra):
        environment = {key:value for key,value in os.environ.items() if not key.startswith(('AWS_', 'POSTGRES_', 'NEHEDROU_', 'DEMO_', 'RENDER', 'DJANGO_'))}
        environment.update(DJANGO_DEBUG='1', DEMO_MODE='1', NEHEDROU_MEDIA_BACKEND='s3',
            NEHEDROU_S3_BUCKET='fictional-private-bucket', AWS_ENDPOINT_URL_S3='https://fictional.example.test',
            AWS_ACCESS_KEY_ID='fictional-access', AWS_SECRET_ACCESS_KEY='fictional-secret', AWS_REGION='eu-central-1')
        environment.update(extra)
        code = "import json;from config import settings as s; o=s.STORAGES['default']['OPTIONS']; print(json.dumps({k:o[k] for k in ['default_acl','querystring_auth','querystring_expire','file_overwrite','addressing_style','signature_version','object_parameters']}));print(s.STORAGES['staticfiles']['BACKEND'])"
        return subprocess.run([sys.executable, '-c', code], cwd=settings.BASE_DIR, env=environment, capture_output=True, text=True, timeout=10)

    def test_private_storage_keeps_protected_defaults_and_separate_static_assets(self):
        result=self.load()
        self.assertEqual(result.returncode,0,result.stderr)
        data=json.loads(result.stdout.splitlines()[0])
        self.assertIsNone(data['default_acl'])
        self.assertTrue(data['querystring_auth'])
        self.assertEqual(data['querystring_expire'],60)
        self.assertFalse(data['file_overwrite'])
        self.assertEqual(data['addressing_style'],'path')
        self.assertEqual(data['signature_version'],'s3v4')
        self.assertEqual(data['object_parameters']['CacheControl'],'private, no-store')
        self.assertIn('StaticFilesStorage',result.stdout.splitlines()[1])
        self.assertNotIn('fictional-secret',result.stdout)

    def test_missing_credentials_and_insecure_endpoint_fail_closed(self):
        for value in ['', 'http://fictional.example.test', 'https://user:password@example.test', 'https://example.test/?secret=value', 'https://example.test/path']:
            self.assertNotEqual(self.load(AWS_ENDPOINT_URL_S3=value).returncode,0)
        self.assertNotEqual(self.load(AWS_SECRET_ACCESS_KEY='').returncode,0)
        self.assertNotEqual(self.load(NEHEDROU_MEDIA_BACKEND='unknown').returncode,0)
