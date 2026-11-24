"""Explicit, idempotent saving of a tab-local recording; never an association."""
import hashlib
import json
from uuid import UUID

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET

from core.services import audit
from core.storage_io import STORAGE_ERRORS
from .guided_audio import (read_capture_context, display_context, saved_media_context,
                           validate_upload_form)
from .media_validation import MAX_BYTES
from .models import Activity, EditorialGrant, MediaUploadReceipt

SCHEMA = 'nehdrou-recording-upload-v1'
HEADER = 'X-Nehedrou-Recording-Retention'


def requested(request):
    return request.method == 'POST' and request.headers.get(HEADER) == '1'


def _json(status, *, code=200, **values):
    response = JsonResponse({'schema': SCHEMA, 'status': status, **values}, status=code)
    response['Cache-Control'] = 'private, no-store'
    return response


def _saved(receipt, *, replayed=False):
    return _json('saved', result_url=reverse('editorial_upload_result', args=[receipt.pk]),
                 replayed=replayed)


def _unavailable(receipt):
    return _json('unavailable', code=409,
                 result_url=reverse('editorial_upload_result', args=[receipt.pk]))


def _conflict(receipt=None, actor=None):
    result = {}
    if receipt and receipt.actor_id == actor.pk:
        result['result_url'] = reverse('editorial_upload_result', args=[receipt.pk])
    return _json('conflict', code=409, **result)


def _require_editor(actor, collection, *, variety_id=None, lock=False):
    if not actor.is_active:
        raise PermissionDenied
    grants = EditorialGrant.objects.filter(user=actor, edit=True)
    if collection:
        grants = grants.filter(variety=collection['variety'])
    elif variety_id:
        grants = grants.filter(variety_id=variety_id)
    if lock:
        grants = grants.select_for_update()
    if not actor.is_superuser and not grants.order_by('pk').first():
        raise PermissionDenied


def _payload_digest(request, draft):
    files = request.FILES.getlist('file')
    if len(files) != 1 or files[0].size > MAX_BYTES:
        raise ValidationError(_('The file must be smaller than 15 MB.'))
    file = files[0]
    try:
        file.seek(0)
        contents = file.read(MAX_BYTES + 1)
    finally:
        file.seek(0)
    if len(contents) > MAX_BYTES:
        raise ValidationError(_('The file must be smaller than 15 MB.'))
    values = {key: request.POST.getlist(key) for key in request.POST
              if key not in ('csrfmiddlewaretoken', 'upload_attempt')}
    values['_file'] = {'name': file.name, 'sha256': hashlib.sha256(contents).hexdigest()}
    values['_draft'] = str(draft.pk) if draft else ''
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _form_errors(form):
    return [{'field': name, 'label': str(form.fields[name].label or '') if name in form.fields else '',
             'messages': [str(message) for message in messages]}
            for name, messages in form.errors.items()]


def save_recording(request, form, draft, collection):
    """Use the existing form and fresh edit scope; create asset/receipt/audit once.

    The key is not a capability. The actor and exact attempted fields/file must
    match for a replay. Only newly written files from a rolled-back transaction
    are eligible for best-effort storage cleanup, as in generated-pack imports.
    """
    try:
        key = UUID(request.POST.get('upload_attempt', ''))
    except (ValueError, TypeError, AttributeError):
        return _json('invalid', code=400, errors=[{'field':'', 'label':'', 'messages':[
            _('This recording upload request is invalid. Keep your WAV and reload the collection page.')]}])
    try:
        digest = _payload_digest(request, draft)
    except ValidationError as error:
        return _json('invalid', code=422, errors=[{'field':'file', 'label':str(form.fields['file'].label),
                                                   'messages':error.messages}])
    created_files = []
    database_writes_finished = False
    try:
        with transaction.atomic():
            # Serialize retries for this actor across workers. Recheck authority
            # after acquiring the lock, including permissions withdrawn in wait.
            actor = get_user_model().objects.select_for_update(no_key=True).get(pk=request.user.pk)
            try:
                selected_variety = UUID(request.POST.get('audio_variety', ''))
            except (ValueError, TypeError, AttributeError):
                selected_variety = None  # The ordinary form will reject it.
            # Grant withdrawal uses the same row lock. The transaction which
            # obtains it first wins; a later withdrawal is not retroactive.
            _require_editor(actor, collection, variety_id=selected_variety, lock=True)
            receipt = MediaUploadReceipt.objects.select_related('asset').filter(pk=key).first()
            if receipt:
                if receipt.actor_id != actor.pk or receipt.payload_digest != digest:
                    return _conflict(receipt, actor)
                if receipt.asset.revoked or not receipt.asset.intact:
                    return _unavailable(receipt)
                return _saved(receipt, replayed=True)
            valid = form.is_valid()
            if valid and form.cleaned_data.get('kind') != 'audio':
                form.add_error('kind', _('This collection step accepts an audio recording only.'))
                valid = False
            if valid and collection:
                valid = validate_upload_form(form, collection)
            if not valid:
                return _json('invalid', code=422, errors=_form_errors(form))
            asset = form.instance
            try:
                asset = form.save()
            finally:
                if asset.file._committed:
                    created_files.append((asset.file.storage, asset.file.name))
            receipt = MediaUploadReceipt.objects.create(id=key, actor=actor, asset=asset,
                payload_digest=digest, draft=draft,
                capture_context=collection['token'] if collection else '')
            audit(actor, 'catalog.media_uploaded', asset)
            # COMMIT acknowledgement can be lost after a real commit. From this
            # point cleanup must not assume a rollback or delete the saved WAV.
            database_writes_finished = True
        return _saved(receipt)
    except Exception as error:
        if database_writes_finished:
            if isinstance(error, DatabaseError):
                return _json('uncertain', code=503)
            raise
        # Never delete a pre-existing take or a replayed upload. Clean only names
        # newly committed to storage by this failed DB transaction.
        for storage, name in created_files:
            try:
                storage.delete(name)
            except STORAGE_ERRORS:
                pass
        if isinstance(error, IntegrityError):
            # A cross-actor UUID collision may win its own actor lock. Do not
            # disclose the other receipt or create a replacement request.
            receipt = MediaUploadReceipt.objects.filter(pk=key).first()
            if receipt:
                return _conflict(receipt, request.user)
        if isinstance(error, STORAGE_ERRORS) or isinstance(error, IntegrityError):
            return _json('retry', code=503, errors=[{'field':'', 'label':'', 'messages':[
                _('Media storage is temporarily unavailable. Keep your local file and try again.')]}])
        raise


@login_required
@require_GET
def result(request, pk):
    receipt = get_object_or_404(MediaUploadReceipt.objects.select_related('asset', 'draft'),
                                pk=pk, actor=request.user, asset__uploaded_by=request.user)
    collection = None
    if receipt.capture_context:
        try:
            data, variety, expired = read_capture_context(receipt.capture_context, request.user)
        except signing.BadSignature:
            raise Http404 from None
        activity = Activity.objects.select_related('variety').filter(pk=data['activity'], variety=variety).first()
        collection = {'token':receipt.capture_context, 'expired':expired,
                      'display':display_context(data, variety, receipt.capture_context, expired, activity)}
    else:
        _require_editor(request.user, None)
        activity = receipt.draft
    context = saved_media_context(receipt.asset, activity, collection)
    if receipt.asset.revoked or not receipt.asset.intact:
        context.update(can_associate=False,
            association_error=_('This recording is revoked, missing or changed. It was not linked; upload a new recording.'))
    response = render(request, 'editorial/media.html', context)
    response['Cache-Control'] = 'private, no-store'
    return response
