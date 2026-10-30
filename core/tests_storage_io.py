"""Installed S3Storage + StreamingBody, mocked SDK only; no cloud or real files."""
import hashlib
import io
from types import SimpleNamespace
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from django.core.files.base import ContentFile
from django.core.files.storage import InMemoryStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.test.client import closing_iterator_wrapper
from django.urls import reverse
from django.utils.functional import SimpleLazyObject
from storages.backends.s3 import S3Storage

from catalog.audio_delivery import protected_media_response
from catalog.integrity import integrity_scope
from catalog.models import EditorialGrant, Variety
from core.models import User
from core.ops_readiness import storage_probe, operations_report, MAX_PROBE_BYTES
from core.storage_io import read_bounded, StorageReadError, StorageLimitExceeded
from qualification.models import EvidenceDocument, digest_file
from qualification.views import evidence_file


class TrackedRaw(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.read_sizes, self.bytes_read, self.closes = [], 0, 0

    def read(self, size=-1):
        self.read_sizes.append(size)
        data = super().read(size)
        self.bytes_read += len(data)
        return data

    def close(self):
        self.closes += 1
        super().close()


def s3_response(data, *, status=206, **changes):
    raw = TrackedRaw(data)
    response = {'Body': StreamingBody(raw, len(data)), 'ContentLength': len(data),
                'ResponseMetadata': {'HTTPStatusCode': status}}
    if status == 206:
        response['ContentRange'] = f'bytes 0-{len(data)-1}/{len(data)}'
    response.update(changes)
    return response, raw


class InstalledS3:
    def __init__(self, *, location='private-root', **options):
        # Explicit fictional credentials prevent metadata/profile discovery.
        self.storage = S3Storage(bucket_name='fictional-bucket', access_key='fixture-access',
            secret_key='fixture-secret', endpoint_url='https://s3.fixture.invalid',
            region_name='us-east-1', location=location, **options)
        self.client = Mock()
        self.storage._connections.connection = SimpleNamespace(meta=SimpleNamespace(client=self.client))
        self.client.head_object.side_effect = AssertionError('Unexpected HEAD')

    def response(self, data, **changes):
        response, raw = s3_response(data, **changes)
        self.client.get_object.return_value = response
        self.client.get_object.side_effect = None
        return raw


class BoundedStorageTests(SimpleTestCase):
    def setUp(self):
        self.s3 = InstalledS3()
        self.no_s3file = self.enterContext(patch('storages.backends.s3.S3File', side_effect=AssertionError('Whole-object adapter forbidden')))
        self.no_dns = self.enterContext(patch('socket.getaddrinfo', side_effect=AssertionError('Network forbidden')))

    def tearDown(self):
        self.no_s3file.assert_not_called()
        self.no_dns.assert_not_called()

    def test_real_backend_normalizes_location_and_preserves_allowed_get_parameters(self):
        s3 = InstalledS3(object_parameters={'SSECustomerAlgorithm':'AES256',
            'SSECustomerKey':'fictional-private-key', 'CacheControl':'private, no-store'})
        raw = s3.response(b'complete')
        self.assertEqual(read_bounded(s3.storage, 'folder\\word.bin', 8), b'complete')
        s3.client.get_object.assert_called_once_with(Bucket='fictional-bucket',
            Key='private-root/folder/word.bin', Range='bytes=0-8',
            SSECustomerAlgorithm='AES256', SSECustomerKey='fictional-private-key')
        self.assertEqual(raw.bytes_read, 8)
        self.assertTrue(all(0 < size <= 9 for size in raw.read_sizes))
        self.assertEqual(raw.closes, 1)
        for name in ['../outside.bin', '/outside.bin']:
            with self.subTest(name=name), self.assertRaises(StorageReadError) as error:
                read_bounded(s3.storage, name, 8)
            self.assertNotIn(name, str(error.exception))

    def test_lazy_django_storage_proxy_uses_the_same_bounded_s3_path(self):
        raw=self.s3.response(b'complete')
        storage=SimpleLazyObject(lambda:self.s3.storage)
        self.assertEqual(read_bounded(storage,'lazy.bin',8),b'complete')
        self.s3.client.get_object.assert_called_once_with(Bucket='fictional-bucket',
            Key='private-root/lazy.bin',Range='bytes=0-8')
        self.assertEqual(raw.closes,1)

    def test_declared_oversize_is_closed_without_reading_or_full_download(self):
        for status in (200,206):
            with self.subTest(status=status):
                raw = self.s3.response(b'prefix',status=status,ContentLength=1000000000)
                with self.assertRaises(StorageLimitExceeded):
                    read_bounded(self.s3.storage,'huge.bin',8)
                self.assertEqual(raw.bytes_read,0)
                self.assertEqual(raw.closes,1)

    def test_ignored_range_is_safe_only_for_declared_complete_small_body(self):
        raw = self.s3.response(b'complete',status=200)
        self.assertEqual(read_bounded(self.s3.storage,'small.bin',8),b'complete')
        self.assertEqual(raw.closes,1)
        self.assertLessEqual(raw.bytes_read,9)

    def test_partial_ranges_and_incoherent_metadata_are_never_accepted_as_whole_objects(self):
        cases = [dict(ContentRange='bytes 1-8/9'),dict(ContentRange='bytes 0-3/8'),
            dict(ContentRange='bytes 0-7/*'),dict(ContentRange='bytes 0-7/9'),
            dict(ContentLength=None),dict(ContentLength=True),dict(ContentLength=-1),
            dict(ContentLength='8'),dict(ResponseMetadata={'HTTPStatusCode':500}),
            dict(status=200,ContentRange='bytes 0-7/8')]
        for changes in cases:
            with self.subTest(changes=changes):
                raw = self.s3.response(b'complete',**changes)
                with self.assertRaises(StorageReadError):
                    read_bounded(self.s3.storage,'partial.bin',8)
                self.assertEqual(raw.closes,1)
                self.assertEqual(raw.bytes_read,0)

    def test_truncation_trailing_data_and_stream_errors_fail_closed_and_close(self):
        for data,length in [(b'short',8),(b'trailing',3)]:
            with self.subTest(length=length):
                response, raw = s3_response(data, status=200,ContentLength=length)
                response['Body'] = StreamingBody(raw,length)
                self.s3.client.get_object.return_value=response
                with self.assertRaises((StorageReadError,OSError)):
                    # StreamingBody also raises botocore IncompleteReadError.
                    read_bounded(self.s3.storage,'wrong-length.bin',8)
                self.assertEqual(raw.closes,1)
                self.assertLessEqual(raw.bytes_read,9)
        raw=self.s3.response(b'complete')
        with patch.object(raw,'read',side_effect=OSError('PRIVATE_PROVIDER_ERROR')):
            with self.assertRaises(OSError):
                read_bounded(self.s3.storage,'error.bin',8)
        self.assertEqual(raw.closes,1)

    def test_short_stream_chunks_are_consumed_to_exact_eof_within_the_budget(self):
        raw=self.s3.response(b'complete')
        original=raw.read
        with patch.object(raw,'read',side_effect=lambda size:original(min(size,2))):
            self.assertEqual(read_bounded(self.s3.storage,'chunked.bin',8),b'complete')
        self.assertEqual(raw.bytes_read,8)
        self.assertEqual(raw.closes,1)

    def test_encoded_objects_are_not_decompressed_or_delivered_under_another_hash(self):
        for encoding in ('gzip','br','gzip, identity',None):
            with self.subTest(encoding=encoding):
                raw=self.s3.response(b'complete',ContentEncoding=encoding)
                with self.assertRaises(StorageReadError):
                    read_bounded(self.s3.storage,'encoded.bin',8)
                self.assertEqual(raw.bytes_read,0)
                self.assertEqual(raw.closes,1)
        raw=self.s3.response(b'complete',ContentEncoding='identity')
        self.assertEqual(read_bounded(self.s3.storage,'identity.bin',8),b'complete')
        self.assertEqual(raw.closes,1)

    def test_sdk_failures_and_cleanup_errors_are_generic_without_private_details(self):
        private='PRIVATE_BUCKET_KEY_OR_PROVIDER_ERROR'
        error=ClientError({'Error':{'Code':'AccessDenied','Message':private},
            'ResponseMetadata':{'HTTPStatusCode':403}},'GetObject')
        self.s3.client.get_object.side_effect=error
        with self.assertRaises(StorageReadError) as raised:
            read_bounded(self.s3.storage,'private-key.bin',8)
        self.assertNotIn(private,str(raised.exception))
        raw=self.s3.response(b'complete')
        original=raw.close
        def failed_close():
            original()
            raise OSError(private)
        with patch.object(raw,'close',side_effect=failed_close):
            with self.assertRaises(StorageReadError) as raised:
                read_bounded(self.s3.storage,'private-key.bin',8)
        self.assertNotIn(private,str(raised.exception))
        self.assertEqual(raw.closes,1)

    def test_missing_body_or_invalid_limit_never_opens_a_whole_object(self):
        for invalid in (-1,True,None,'8'):
            with self.subTest(limit=invalid),self.assertRaises(StorageReadError):
                read_bounded(self.s3.storage,'fixture.bin',invalid)
        self.s3.client.get_object.assert_not_called()
        self.s3.client.get_object.return_value={'ContentLength':0,'ResponseMetadata':{'HTTPStatusCode':200}}
        with self.assertRaises(StorageReadError):
            read_bounded(self.s3.storage,'fixture.bin',8)

    def test_oversize_media_never_serves_get_head_or_range_prefixes(self):
        asset=SimpleNamespace(file=SimpleNamespace(storage=self.s3.storage,name='media/huge.wav'),
            technical_metadata={'sha256':hashlib.sha256(b'prefix').hexdigest(),'format':'WAV'})
        factory=RequestFactory()
        for method,headers in [('get',{}),('head',{}),('get',{'HTTP_RANGE':'bytes=0-2'})]:
            with self.subTest(method=method,range=bool(headers)):
                raw=self.s3.response(b'prefix',ContentLength=15*1024*1024+1)
                with self.assertRaises(Http404):
                    protected_media_response(getattr(factory,method)('/fixture/',**headers),asset)
                self.assertEqual(raw.bytes_read,0)
                self.assertEqual(raw.closes,1)

    def test_empty_objects_are_confirmed_and_conditionally_read_after_s3_416(self):
        invalid=ClientError({'Error':{'Code':'InvalidRange'},'ResponseMetadata':{'HTTPStatusCode':416}},'GetObject')
        response,raw=s3_response(b'',status=200)
        self.s3.client.get_object.side_effect=[invalid,response]
        self.s3.client.head_object.side_effect=None
        self.s3.client.head_object.return_value={'ContentLength':0,'ETag':'"fictional-empty-etag"'}
        self.assertEqual(read_bounded(self.s3.storage,'empty.bin',0),b'')
        self.assertEqual(self.s3.client.get_object.call_args_list[0].kwargs['Range'],'bytes=0-0')
        self.assertEqual(self.s3.client.get_object.call_args_list[1].kwargs['IfMatch'],'"fictional-empty-etag"')
        self.assertNotIn('Range',self.s3.client.get_object.call_args_list[1].kwargs)
        self.assertEqual(raw.closes,1)
        self.assertEqual(raw.read_sizes,[1])

    def test_empty_recovery_never_accepts_a_later_nonempty_object(self):
        invalid=ClientError({'Error':{'Code':'InvalidRange'},'ResponseMetadata':{'HTTPStatusCode':416}},'GetObject')
        for metadata in ({'ContentLength':1,'ETag':'"v"'},{'ContentLength':0}, {'ContentLength':0,'ETag':'"v"'}):
            with self.subTest(metadata=metadata):
                response,raw=s3_response(b'changed',status=200)
                self.s3.client.get_object.side_effect=[invalid,response]
                self.s3.client.head_object.side_effect=None
                self.s3.client.head_object.return_value=metadata
                with self.assertRaises(StorageReadError):
                    read_bounded(self.s3.storage,'empty.bin',8)
                if metadata.get('ETag') and metadata['ContentLength']==0:
                    self.assertEqual(raw.closes,1)
                    self.assertEqual(raw.bytes_read,0)

    def test_filesystem_like_backend_keeps_ordinary_open_read_and_closes(self):
        storage=InMemoryStorage()
        name=storage.save('fictional.bin',ContentFile(b'complete'))
        self.assertEqual(read_bounded(storage,name,8),b'complete')
        with self.assertRaises(StorageLimitExceeded):
            read_bounded(storage,name,7)
        missing='missing-fictional.bin'
        with self.assertRaises(OSError):
            read_bounded(storage,missing,8)
        self.s3.client.get_object.assert_not_called()

    def test_probe_verifies_only_expected_exact_bytes_and_hides_key_hash_body_errors(self):
        data=b'fictional probe'
        digest=hashlib.sha256(data).hexdigest()
        for expected,ok,verified in [(None,True,False),(digest,True,True),('0'*64,False,False)]:
            with self.subTest(expected_present=expected is not None):
                raw=self.s3.response(data)
                with override_settings(MEDIA_STORAGE_BACKEND='s3'),patch('django.core.files.storage.default_storage',self.s3.storage):
                    report=storage_probe('private-operator-sentinel.bin',expected_sha256=expected)
                self.assertEqual(report['ok'],ok)
                self.assertEqual(report['expected_content_verified'],verified)
                self.assertEqual(report['bytes_read'],len(data))
                self.assertEqual(raw.closes,1)
                for secret in ['private-operator-sentinel',digest,data.decode()]:
                    self.assertNotIn(secret,str(report))
        self.s3.client.reset_mock()
        for expected in ('invalid',digest.upper(),False):
            with self.subTest(invalid_expected=type(expected).__name__),override_settings(MEDIA_STORAGE_BACKEND='s3'),patch('django.core.files.storage.default_storage',self.s3.storage):
                report=storage_probe('private-operator-sentinel.bin',expected_sha256=expected)
                self.assertFalse(report['ok'])
                self.assertFalse(report['expected_content_verified'])
        self.s3.client.get_object.assert_not_called()

    def test_oversize_probe_closes_before_transferring_declared_object(self):
        raw=self.s3.response(b'prefix',status=200,ContentLength=4*MAX_PROBE_BYTES)
        with override_settings(MEDIA_STORAGE_BACKEND='s3'),patch('django.core.files.storage.default_storage',self.s3.storage):
            report=storage_probe('huge-operator-sentinel.bin')
        self.assertFalse(report['ok'])
        self.assertEqual(report['reason'],'sample_exceeds_1_mib')
        self.assertEqual(report['bytes_read'],0)
        self.assertFalse(report['expected_content_verified'])
        self.assertEqual(raw.bytes_read,0)
        self.assertEqual(raw.closes,1)

    def test_operations_passes_expected_digest_without_returning_it(self):
        digest=hashlib.sha256(b'fixture').hexdigest()
        with patch('core.ops_readiness.storage_probe',return_value={'requested':True,'ok':True,'expected_content_verified':True}) as probe:
            report=operations_report(storage_object='fixture.bin',storage_expected_sha256=digest)
        probe.assert_called_once_with('fixture.bin',expected_sha256=digest)
        self.assertNotIn(digest,str(report))

    def test_private_media_get_head_and_ranges_hash_the_exact_remote_body(self):
        data=b'fictional media bytes'
        asset=SimpleNamespace(file=SimpleNamespace(storage=self.s3.storage,name='media/model.wav'),
            technical_metadata={'sha256':hashlib.sha256(data).hexdigest(),'format':'WAV'})
        factory=RequestFactory()
        for method,headers,status,body in [('get',{},200,data),('head',{'HTTP_RANGE':'bytes=0-2'},200,b''),
                ('get',{'HTTP_RANGE':'bytes=0-2'},206,data[:3])]:
            with self.subTest(method=method,status=status):
                raw=self.s3.response(data)
                response=protected_media_response(getattr(factory,method)('/fixture/',**headers),asset)
                self.assertEqual(response.status_code,status)
                self.assertEqual(response.content,body)
                self.assertEqual(response['Cache-Control'],'private, no-store')
                self.assertEqual(raw.closes,1)
                self.assertLessEqual(raw.bytes_read,15*1024*1024+1)
        for method in ('get','head'):
            raw=self.s3.response(b'changed bytes')
            with self.subTest(corrupt_method=method),self.assertRaises(Http404):
                protected_media_response(getattr(factory,method)('/fixture/',HTTP_RANGE='bytes=0-2'),asset)
            self.assertEqual(raw.closes,1)


@override_settings(DEMO_MODE=False,MFA_REQUIRED=False,
    PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
    STORAGES={'default':{'BACKEND':'django.core.files.storage.InMemoryStorage'},
              'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class S3EvidenceDeliveryTests(TestCase):
    def setUp(self):
        self.actor=User.objects.create_user('s3-evidence-editor','s3-editor@example.test')
        self.other=User.objects.create_user('s3-evidence-other','s3-other@example.test')
        self.variety=Variety.objects.create(code='fr-s3-evidence',language='fr',label='Fictional evidence')
        self.grant=EditorialGrant.objects.create(user=self.actor,variety=self.variety,edit=True)
        self.data=b'fictional exact private evidence'
        self.document=EvidenceDocument.objects.create(variety=self.variety,uploaded_by=self.actor,
            title='Fictional S3 proof',category='rights',provenance='Fictional only',
            file=SimpleUploadedFile('proof.txt',self.data))
        self.s3=InstalledS3()
        self.s3.client.head_object.side_effect=None
        self.s3.client.head_object.return_value={}  # Existing digest existence check.
        self.enterContext(patch.object(EvidenceDocument._meta.get_field('file'),'storage',self.s3.storage))
        self.no_s3file=self.enterContext(patch('storages.backends.s3.S3File',side_effect=AssertionError('Whole-object adapter forbidden')))
        self.no_dns=self.enterContext(patch('socket.getaddrinfo',side_effect=AssertionError('Network forbidden')))
        self.path=reverse('qualification:evidence_file',args=[self.document.pk])

    def test_digest_and_delivery_keep_independent_reads_and_exact_get_head_bytes(self):
        document=EvidenceDocument.objects.get(pk=self.document.pk)
        with integrity_scope():
            raw=self.s3.response(self.data)
            self.assertTrue(document.intact)
            self.assertEqual(raw.closes,1)
            raw=self.s3.response(b'changed evidence')
            self.assertTrue(document.intact)  # The old request cache is warm.
            request=RequestFactory().get(self.path)
            request.user=self.actor
            with self.assertRaises(Http404):
                evidence_file(request,self.document.pk)
            self.assertEqual(raw.closes,1)
        with integrity_scope():
            self.s3.response(b'changed evidence')
            self.assertFalse(document.intact)
        self.client.force_login(self.actor)
        for method in ('get','head'):
            raw=self.s3.response(self.data)
            response=getattr(self.client,method)(self.path)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response['Content-Length'],str(len(self.data)))
            self.assertEqual(b''.join(closing_iterator_wrapper(response.streaming_content,response.close)),self.data if method=='get' else b'')
            self.assertEqual(raw.closes,1)

    def test_unauthorized_or_revoked_documents_never_read_remote_bytes(self):
        self.assertEqual(self.client.get(self.path).status_code,302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.path).status_code,404)
        self.client.force_login(self.actor)
        EvidenceDocument.objects.filter(pk=self.document.pk).update(revoked=True,revocation_reason='Fictional revocation')
        self.assertEqual(self.client.get(self.path).status_code,404)
        self.s3.client.get_object.assert_not_called()

    def test_oversize_or_encoded_digest_and_delivery_fail_closed(self):
        document=EvidenceDocument.objects.get(pk=self.document.pk)
        for changes in [dict(ContentLength=15*1024*1024+1),dict(ContentEncoding='gzip')]:
            with self.subTest(changes=changes):
                raw=self.s3.response(self.data,**changes)
                self.assertEqual(digest_file(document.file),'')
                self.assertEqual(raw.closes,1)
                self.client.force_login(self.actor)
                raw=self.s3.response(self.data,**changes)
                self.assertEqual(self.client.get(self.path).status_code,404)
                self.assertEqual(raw.closes,1)
