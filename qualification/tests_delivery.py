"""Private evidence delivery uses only fictional bytes held in memory."""
import hashlib
from datetime import timedelta
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.test import RequestFactory, TestCase, override_settings
from django.test.client import closing_iterator_wrapper
from django.urls import reverse
from django.utils import timezone

from catalog.integrity import integrity_scope
from catalog.models import EditorialGrant, Variety
from core.models import User
from .models import EvidenceDocument
from .views import evidence_file


@override_settings(DEMO_MODE=False, MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class EvidenceDeliveryTests(TestCase):
    original = b'Fictional evidence original v1'
    changed = b'Fictional modified evidence v2'

    def setUp(self):
        self.actor = User.objects.create_user(username='evidence-delivery-editor', email='evidence-editor@example.test')
        self.family = User.objects.create_user(username='evidence-delivery-family', email='evidence-family@example.test')
        self.other = User.objects.create_user(username='evidence-delivery-other', email='evidence-other@example.test')
        self.variety = Variety.objects.create(code='fr-evidence-delivery', language='fr', label='Fictional evidence variety')
        other_variety = Variety.objects.create(code='en-evidence-delivery', language='en', label='Other fictional variety')
        self.grant = EditorialGrant.objects.create(user=self.actor, variety=self.variety, edit=True)
        EditorialGrant.objects.create(user=self.other, variety=other_variety, edit=True)
        self.document = EvidenceDocument.objects.create(variety=self.variety, uploaded_by=self.actor,
            title='Fictional delivery evidence', category='rights', provenance='Fictional in-memory regression only',
            file=SimpleUploadedFile('fictional-proof.txt', self.original))
        self.storage = self.document.file.storage
        self.path = reverse('qualification:evidence_file', args=[self.document.pk])
        self.factory = RequestFactory()

    def request(self, method='get'):
        request = getattr(self.factory, method)(self.path)
        request.user = self.actor
        return request

    def replace_bytes(self, data):
        name = self.document.file.name
        self.storage.delete(name)
        self.assertEqual(self.storage.save(name, ContentFile(data)), name)

    def read_response(self, response):
        # Match Django's client cleanup without closing an atomic TestCase DB connection.
        return b''.join(closing_iterator_wrapper(response.streaming_content, response.close))

    def test_get_and_head_keep_private_attachment_headers_and_verified_length(self):
        self.client.force_login(self.actor)
        for method in ['get', 'head']:
            with self.subTest(method=method):
                response = getattr(self.client, method)(self.path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Length'], str(len(self.original)))
                self.assertEqual(response['Content-Type'], 'application/octet-stream')
                self.assertEqual(response['Cache-Control'], 'private, no-store')
                self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
                self.assertIn('attachment;', response['Content-Disposition'])
                self.assertIn('evidence-' + str(self.document.pk) + '.txt', response['Content-Disposition'])
                self.assertEqual(self.read_response(response), self.original if method == 'get' else b'')

    def test_warmed_request_digest_never_allows_replaced_get_or_head_bytes(self):
        for method in ['get', 'head']:
            with self.subTest(method=method), integrity_scope():
                self.replace_bytes(self.original)
                self.assertTrue(self.document.intact)
                self.replace_bytes(self.changed)
                self.assertTrue(self.document.intact)  # Explicitly reproduce the cached precondition.
                with self.assertRaises(Http404):
                    evidence_file(self.request(method), self.document.pk)

    def test_cold_delivery_never_reopens_storage_after_verifying_other_bytes(self):
        # The former implementation verified the first open and delivered the second.
        with integrity_scope(), patch.object(self.storage, 'open',
            side_effect=[ContentFile(self.original), ContentFile(self.changed)]) as opened:
            response = evidence_file(self.request(), self.document.pk)
            self.assertEqual(self.read_response(response), self.original)
            self.assertEqual(opened.call_count, 1)

    def test_response_keeps_the_verified_body_if_storage_changes_before_streaming(self):
        response = evidence_file(self.request(), self.document.pk)
        with self.storage.open(self.document.file.name, 'wb') as stream:
            stream.write(self.changed)
        self.assertEqual(self.read_response(response), self.original)

    def test_authentication_variety_isolation_and_next_request_grant_revocation(self):
        self.assertEqual(self.client.get(self.path).status_code, 302)
        for user in [self.family, self.other]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.path).status_code, 404)
        self.client.force_login(self.actor)
        self.assertEqual(self.read_response(self.client.get(self.path)), self.original)
        self.grant.delete()
        self.assertEqual(self.client.get(self.path).status_code, 404)

    def test_intact_unknown_and_expired_archives_remain_accessible_but_revoked_do_not(self):
        self.client.force_login(self.actor)
        self.assertEqual(self.document.validity, 'unknown')
        self.assertEqual(self.read_response(self.client.get(self.path)), self.original)
        expired = EvidenceDocument.objects.create(variety=self.variety, uploaded_by=self.actor,
            title='Fictional expired archive', category='rights', provenance='Fictional archival contract',
            validity='limited', valid_until=timezone.localdate() - timedelta(days=1),
            file=SimpleUploadedFile('expired-fictional-proof.txt', self.original))
        self.assertTrue(expired.intact)
        self.assertFalse(expired.usable)
        path = reverse('qualification:evidence_file', args=[expired.pk])
        self.assertEqual(self.read_response(self.client.get(path)), self.original)
        expired.revoked = True
        expired.revocation_reason = 'Fictional explicit withdrawal'
        expired.save()
        self.assertEqual(self.client.get(path).status_code, 404)

    def test_oversized_body_is_bounded_even_if_its_recorded_hash_matches(self):
        limit = 15 * 1024 * 1024
        oversized = b'x' * (limit + 1)
        EvidenceDocument.objects.filter(pk=self.document.pk).update(sha256=hashlib.sha256(oversized).hexdigest())
        reads = []
        class TrackedContentFile(ContentFile):
            def read(self, size=-1):
                reads.append(size)
                return super().read(size)
        stream = TrackedContentFile(oversized)
        with patch.object(self.storage, 'open', return_value=stream) as opened:
            with self.assertRaises(Http404):
                evidence_file(self.request(), self.document.pk)
            self.assertEqual(opened.call_count, 1)
            self.assertEqual(reads, [limit + 1])

    def test_corruption_missing_files_and_storage_errors_fail_closed(self):
        self.replace_bytes(self.changed)
        with self.assertRaises(Http404):
            evidence_file(self.request(), self.document.pk)
        self.storage.delete(self.document.file.name)
        with self.assertRaises(Http404):
            evidence_file(self.request(), self.document.pk)
        with patch.object(self.storage, 'open', side_effect=OSError('Fictional storage unavailable')):
            with self.assertRaises(Http404):
                evidence_file(self.request(), self.document.pk)
