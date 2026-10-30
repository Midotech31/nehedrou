"""Two explicit steps from an exact draft word to a private recording.

A signed capture context describes a proposal, never an approval or a native
speaker claim. The later POST binds one owned asset to one unchanged draft slot.
"""
from urllib.parse import urlencode
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .audio_checks import audio_binding_errors
from .models import Activity, EditorialGrant, MediaAsset, Variety

CAPTURE_SALT = 'catalog.guided-audio.capture.v1'
ASSOCIATION_SALT = 'catalog.guided-audio.association.v1'
CONTEXT_MAX_AGE = 2 * 60 * 60


def _permitted(actor, variety):
    if not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied
    # Do not reuse a grant cached before acquiring the target/media locks.
    superuser = get_user_model().objects.filter(pk=actor.pk, is_active=True).values_list('is_superuser', flat=True).first()
    if superuser is None or (not superuser and not EditorialGrant.objects.filter(user=actor, variety=variety, edit=True).exists()):
        raise PermissionDenied


def _uuid(value):
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise signing.BadSignature from None


def _load(token, salt):
    try:
        return signing.loads(token, salt=salt, max_age=CONTEXT_MAX_AGE), False
    except signing.SignatureExpired:
        # Read the still-authentic source only to retain/recover its owned file.
        # An expired context can never authorise an association.
        return signing.loads(token, salt=salt), True


def make_capture_context(actor, activity, side):
    if side not in ('a', 'b'):
        raise Http404
    _permitted(actor, activity.variety)
    if activity.state != 'draft':
        raise Http404
    entry = (activity.item_metadata or {}).get(side, {})
    entry = entry if isinstance(entry, dict) else {}
    from .templatetags.content_language import valid_language
    data = {'schema': 1, 'actor': str(actor.pk), 'activity': str(activity.pk),
        'version': activity.version, 'side': side, 'variety_id': str(activity.variety_id),
        'variety': activity.variety.code, 'word': getattr(activity, 'word_' + side),
        'meaning': str(entry.get('meaning', '')), 'meaning_language': valid_language(entry.get('meaning_language', 'und')), 'transcription': getattr(activity, 'transcription_' + side),
        'fingerprint': activity.fingerprint()}
    return signing.dumps(data, salt=CAPTURE_SALT, compress=True)


def read_capture_context(token, actor):
    data, expired = _load(token, CAPTURE_SALT)
    if not isinstance(data, dict) or data.get('schema') != 1 or data.get('side') not in ('a', 'b'):
        raise signing.BadSignature
    if data.get('actor') != str(actor.pk):
        raise PermissionDenied
    if not isinstance(data.get('version'), int) or not isinstance(data.get('fingerprint'), str) or len(data['fingerprint']) != 64:
        raise signing.BadSignature
    if any(not isinstance(data.get(key), str) for key in ('variety', 'word', 'meaning', 'meaning_language', 'transcription')):
        raise signing.BadSignature
    _uuid(data.get('activity'))
    variety = Variety.objects.filter(pk=_uuid(data.get('variety_id')), code=data['variety']).first()
    if not variety:
        raise signing.BadSignature
    _permitted(actor, variety)
    return data, variety, expired


def display_context(data, variety, token, expired, activity=None):
    from .templatetags.content_language import spoken_language
    return_url = reverse('editorial_index')
    if activity:
        return_url = reverse('editorial_edit' if activity.state == 'draft' else 'editorial_detail', args=[activity.pk])
    return {'activity_id': data['activity'], 'version': data['version'], 'side': data['side'],
        'word': data['word'], 'meaning': data['meaning'], 'meaning_language': data['meaning_language'], 'transcription': data['transcription'],
        'variety_label': str(variety.display_label), 'word_language': spoken_language(variety),
        'fingerprint': data['fingerprint'], 'capture_token': token, 'expired': expired,
        'return_url': return_url}


def prepare_upload(request):
    """Return a source snapshot, without modifying a file or an activity."""
    token = request.POST.get('guided_context', '') if request.method == 'POST' else ''
    side = request.POST.get('audio_side') or request.GET.get('audio_side')
    if not token and not side:
        return None
    if token:
        try:
            data, variety, expired = read_capture_context(token, request.user)
            if side != data['side']:
                raise signing.BadSignature
            supplied = request.POST.get('draft') or request.GET.get('draft')
            if supplied and _uuid(supplied) != _uuid(data['activity']):
                raise signing.BadSignature
        except signing.BadSignature:
            raise Http404 from None
        # The source may have changed or disappeared since capture. Save the
        # otherwise valid owned recording; the second step will refuse binding.
        activity = Activity.objects.filter(pk=data['activity'], variety=variety).select_related('variety').first()
    else:
        if request.method != 'GET' or side not in ('a', 'b'):
            raise Http404
        try:
            reference = _uuid(request.GET.get('draft'))
        except signing.BadSignature:
            raise Http404 from None
        from .views import editorial_activities
        activity = editorial_activities(request.user).filter(pk=reference, state='draft').select_related('variety').first()
        if not activity:
            raise Http404
        token = make_capture_context(request.user, activity, side)
        data, variety, expired = read_capture_context(token, request.user)
    return {'data': data, 'variety': variety, 'activity': activity,
        'display': display_context(data, variety, token, expired, activity),
        'token': token, 'expired': expired}


def configure_upload_form(form, context):
    data = context['data']
    form.initial.update(kind='audio', audio_text=data['word'], audio_variety=context['variety'].pk)
    # The expected word/variety is visible separately; actual provenance stays
    # explicit, and no source is selected for an imported file.
    form.fields['rights_evidence'].queryset = form.fields['rights_evidence'].queryset.filter(variety=context['variety'])


def validate_upload_form(form, context):
    data = form.cleaned_data
    if data.get('kind') != 'audio':
        form.add_error('kind', _('This collection step accepts an audio recording only.'))
    if data.get('audio_text') != context['data']['word']:
        form.add_error('audio_text', _('The spoken text must match this exact draft word. Use a separate upload for another word or variant.'))
    if data.get('audio_variety') != context['variety']:
        form.add_error('audio_variety', _('The recording must use the spoken variety shown for this draft word.'))
    if data.get('audio_source') not in ('human', 'synthetic'):
        form.add_error('audio_source', _('Choose the actual source of this recording before continuing.'))
    if form.instance.technical_metadata.get('signal', {}).get('silent'):
        form.add_error('file', _('A silent recording cannot be used as a speech model.'))
    return not form.errors


def media_reference(asset):
    return ('editorial/asset-' + str(asset.pk) if asset.kind == 'image'
        else settings.PUBLIC_ORIGIN.rstrip('/') + reverse('editorial_media', args=[asset.pk]))


def saved_media_context(asset, draft=None, collection=None):
    result = {'asset': asset, 'draft': draft, 'media_reference': media_reference(asset)}
    if collection:
        result.update(guided=collection['display'], can_associate=not collection['expired'],
            association_token=signing.dumps({'schema': 1, 'capture': collection['token'], 'asset': str(asset.pk)}, salt=ASSOCIATION_SALT, compress=True))
        if collection['expired']:
            result['association_error'] = _('This collection context expired. Your recording is saved; return to the draft and select it after checking the current word and variety.')
    return result



@login_required
@require_POST
@csrf_protect
def associate(request, pk, side):
    if side not in ('a', 'b'):
        raise Http404
    try:
        envelope, expired = _load(request.POST.get('association_token', ''), ASSOCIATION_SALT)
        if not isinstance(envelope, dict) or envelope.get('schema') != 1 or not isinstance(envelope.get('capture'), str):
            raise signing.BadSignature
        data, variety, capture_expired = read_capture_context(envelope['capture'], request.user)
        if _uuid(data['activity']) != pk or data['side'] != side or _uuid(request.POST.get('asset_id')) != _uuid(envelope.get('asset')):
            raise signing.BadSignature
    except signing.BadSignature:
        return HttpResponseBadRequest(_('The recording context is invalid. Open the current draft before trying again.'))
    error = None
    with transaction.atomic():
        # Stable order: Activity, then MediaAsset. Revocation UPDATEs also wait
        # for this media row, so current provenance is checked before binding.
        activity = Activity.objects.select_for_update(of=('self',)).select_related('variety').filter(pk=pk).first()
        asset = MediaAsset.objects.select_for_update(of=('self',)).select_related('rights_evidence').filter(pk=envelope['asset'], uploaded_by=request.user, kind='audio').first()
        if not asset:
            raise Http404
        _permitted(request.user, variety)
        if expired or capture_expired:
            error = (_('This collection context expired. Your recording is saved; return to the draft and select it after checking the current word and variety.'), 410)
        elif not activity or activity.state != 'draft' or activity.variety_id != variety.pk or activity.version != data['version'] or activity.fingerprint() != data['fingerprint']:
            error = (_('The draft changed after this recording was prepared. Your recording is saved, but it was not linked. Review the current draft before selecting it.'), 409)
        elif asset.revoked or not asset.intact:
            error = (_('This recording is revoked, missing or changed. It was not linked; upload a new recording.'), 409)
        else:
            reasons = audio_binding_errors(asset, getattr(activity, 'word_' + side), activity.variety)
            if reasons:
                error = (' '.join(str(reason) for reason in reasons), 400)
            else:
                setattr(activity, 'audio_' + side, media_reference(asset))
                try:
                    activity.save(update_fields=['audio_' + side])
                except ValidationError:
                    error = (_('The draft has unresolved validation errors. Your recording is saved; correct the draft before selecting it.'), 409)
                else:
                    from core.services import audit
                    audit(request.user, 'catalog.audio_associated', activity)
    if error:
        context = saved_media_context(asset, activity if activity and activity.state == 'draft' else None)
        context.update(guided=display_context(data, variety, envelope['capture'], expired or capture_expired, activity),
            can_associate=False, association_error=error[0])
        response = render(request, 'editorial/media.html', context, status=error[1])
    else:
        return redirect('editorial_detail', pk=pk)
    response['Cache-Control'] = 'private, no-store'
    return response
