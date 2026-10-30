"""Authenticated, bounded byte-range delivery for private speech models."""
import hashlib
import re
from pathlib import Path
from django.http import Http404, HttpResponse
from .media_validation import MAX_BYTES


def protected_media_response(request, asset):
    # Authentication and scope are checked by the view before even HEAD/Range.
    try:
        with asset.file.open('rb') as stream:
            data = stream.read(MAX_BYTES + 1)
    except Exception as error:
        from botocore.exceptions import BotoCoreError, ClientError
        if isinstance(error, (OSError, BotoCoreError, ClientError)):
            raise Http404 from None
        raise
    if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != asset.technical_metadata.get('sha256'):
        raise Http404
    size = len(data)
    content_types = {'WAV': 'audio/wav', 'MP3': 'audio/mpeg', 'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}
    headers = {'Accept-Ranges': 'bytes', 'Cache-Control': 'private, no-store',
               'X-Content-Type-Options': 'nosniff', 'Content-Length': str(size),
               'Content-Disposition': 'inline; filename="model.' + Path(asset.file.name).suffix.lstrip('.') + '"'}
    start, end, status = 0, size - 1, 200
    # HEAD ignores Range, as required for a non-GET request. Multiple ranges are
    # intentionally ignored (full 200); only a single range is supported.
    value = request.headers.get('Range', '') if request.method == 'GET' else ''
    if value.startswith('bytes=') and ',' not in value and not request.headers.get('If-Range'):
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', value)
        if match and any(match.groups()):
            left, right = match.groups()
            if len(left) > 20 or len(right) > 20:
                valid = False
            elif left:
                start, end = int(left), min(int(right) if right else size - 1, size - 1)
                valid = start < size and end >= start
            else:
                suffix = int(right)
                start, end = max(0, size - suffix), size - 1
                valid = suffix > 0 and size > 0
            if not valid:
                headers.update({'Content-Range': f'bytes */{size}', 'Content-Length': '0'})
                return HttpResponse(status=416, headers=headers)
            status = 206
            headers.update({'Content-Range': f'bytes {start}-{end}/{size}', 'Content-Length': str(end - start + 1)})
    body = b'' if request.method == 'HEAD' else data[start:end + 1]
    return HttpResponse(body, status=status, content_type=content_types.get(asset.technical_metadata.get('format'), 'application/octet-stream'), headers=headers)
