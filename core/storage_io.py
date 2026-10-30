"""Read complete private objects within an explicit byte budget.

S3File.read() downloads an entire object before reading its local spool. Bypass
that adapter for S3Storage: request a bounded HTTP Range and consume only a
bounded StreamingBody, always closing it. No paths, contents or provider errors
are included in helper exceptions. This module never writes an object.
"""
import re
from django.core.exceptions import SuspiciousOperation
from botocore.exceptions import ClientError
from storages.backends.s3 import S3Storage, _filter_download_params
from storages.utils import clean_name
from core.storage_health import STORAGE_ERRORS


class StorageReadError(OSError):
    def __init__(self):
        super().__init__('Private storage could not be read safely.')


class StorageLimitExceeded(StorageReadError):
    def __init__(self, bytes_read=0):
        super().__init__()
        self.bytes_read = bytes_read


def _length(value):
    if type(value) is not int or value < 0:
        raise StorageReadError()
    return value


def _consume_s3_response(response, limit):
    body = response.get('Body') if isinstance(response, dict) else None
    if body is None or not callable(getattr(body, 'read', None)) or not callable(getattr(body, 'close', None)):
        if body is not None and callable(getattr(body, 'close', None)):
            body.close()
        raise StorageReadError()
    try:
        status = response.get('ResponseMetadata', {}).get('HTTPStatusCode')
        length = _length(response.get('ContentLength'))
        if length > limit:
            raise StorageLimitExceeded()
        # Stored encodings are never silently decompressed or relabelled. Existing
        # media/evidence are exact raw bytes; compressed or unknown encodings fail closed.
        if response.get('ContentEncoding', '').strip().lower() not in ('', 'identity'):
            raise StorageReadError()
        if status == 206:
            match = re.fullmatch(r'bytes 0-(\d+)/(\d+)', response.get('ContentRange', ''))
            if not match:
                raise StorageReadError()
            end, total = map(int, match.groups())
            if total > limit:
                raise StorageLimitExceeded()
            if total == 0 or end + 1 != length or length != total:
                raise StorageReadError()
        elif status != 200 or response.get('ContentRange'):
            raise StorageReadError()
        # A server ignoring Range is accepted only for a complete declared object
        # already within the cap. Check actual EOF and reject short/trailing bodies.
        chunks, consumed, budget = [], 0, length + 1
        while budget:
            chunk = body.read(budget)
            if not isinstance(chunk, bytes) or len(chunk) > budget:
                raise StorageReadError()
            if not chunk:
                break
            chunks.append(chunk)
            consumed += len(chunk)
            budget -= len(chunk)
            if consumed > limit:
                raise StorageLimitExceeded(consumed)
        if consumed != length:
            raise StorageReadError()
        return b''.join(chunks)
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise StorageReadError() from None
    finally:
        try:
            body.close()
        except Exception:
            raise StorageReadError() from None


def _read_s3(storage, name, limit):
    try:
        # Match the installed backend's location and Windows/POSIX normalization.
        key = storage._normalize_name(clean_name(name))
        relative_name = key[len(storage.location):].lstrip('/')
        options = _filter_download_params(storage.get_object_parameters(relative_name))
        client = storage.connection.meta.client
        arguments = {'Bucket': storage.bucket_name, 'Key': key, **options}
        try:
            response = client.get_object(**arguments, Range=f'bytes=0-{limit}')
        except ClientError as error:
            # Standard S3 returns 416 for a range on an empty object. Confirm a
            # zero-byte version, then GET only that version using its ETag.
            if error.response.get('ResponseMetadata', {}).get('HTTPStatusCode') != 416:
                raise
            metadata = client.head_object(**arguments)
            if _length(metadata.get('ContentLength')) != 0:
                raise StorageReadError() from None
            etag = metadata.get('ETag')
            if not isinstance(etag, str) or not etag or any(ord(c) < 32 or ord(c) == 127 for c in etag):
                raise StorageReadError() from None
            response = client.get_object(**arguments, IfMatch=etag)
            limit = 0  # The confirmed empty version must still be empty.
        return _consume_s3_response(response, limit)
    except (SuspiciousOperation, AttributeError, TypeError, ValueError, OverflowError):
        raise StorageReadError() from None


def read_bounded(storage, name, max_bytes):
    """Return complete raw bytes, or fail closed; at most max_bytes+1 are read.

    S3 must return a coherent complete object within the cap. Unknown/compressed
    ContentEncoding is rejected. Empty-object 416 uses a conditional empty GET.
    Filesystem and other Django storage backends retain their normal open/read.
    The configured SDK/socket timeouts remain in force; no total-time guarantee
    or additional retry is introduced here.
    """
    if type(max_bytes) is not int or max_bytes < 0:
        raise StorageReadError()
    try:
        if isinstance(storage, S3Storage):
            return _read_s3(storage, name, max_bytes)
        with storage.open(name, 'rb') as stream:
            data = stream.read(max_bytes + 1)
        if not isinstance(data, bytes):
            raise StorageReadError()
        if len(data) > max_bytes:
            raise StorageLimitExceeded(len(data))
        return data
    except StorageReadError:
        raise
    except (SuspiciousOperation, *STORAGE_ERRORS):
        raise StorageReadError() from None
