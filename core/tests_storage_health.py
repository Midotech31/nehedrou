from unittest.mock import Mock
from botocore.exceptions import ClientError, EndpointConnectionError
from django.test import SimpleTestCase
from core.storage_health import file_exists
from qualification.models import digest_file

class PrivateStorageFailureTests(SimpleTestCase):
    def test_missing_or_unreachable_files_never_appear_verified(self):
        file=Mock(name='file');file.name='editorial/fixture.wav'
        for error in [OSError('Unavailable'), ClientError({'Error':{'Code':'AccessDenied','Message':'private'}},'HeadObject'), EndpointConnectionError(endpoint_url='https://fictional.example.test')]:
            file.storage.exists.side_effect=error
            self.assertFalse(file_exists(file))
            self.assertEqual(digest_file(file),'')

    def test_interrupted_download_never_keeps_a_verified_digest(self):
        file=Mock(name='file');file.name='private_evidence/fixture'
        file.storage.exists.return_value=True
        file.storage.open.side_effect=EndpointConnectionError(endpoint_url='https://fictional.example.test')
        self.assertEqual(digest_file(file),'')
