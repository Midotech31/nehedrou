"""Document saved draft media rights while retaining the original private asset."""
from copy import deepcopy
import hashlib

from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from core.services import audit
from core.storage_io import STORAGE_ERRORS, read_bounded
from qualification.models import EvidenceDocument
from qualification.validity import currently_valid
from .audio_checks import audio_binding_errors
from .guided_audio import media_reference
from .integrity import invalidate_integrity
from .media_authoring import MediaAuthoringForm, RIGHTS_LABELS
from .media_validation import MAX_BYTES
from .models import Activity, EditorialGrant, MediaAsset
from .readiness import reference_asset_id


SALT = 'catalog.image-rights.v1'
SUFFIXES = {'image': {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'},
            'audio': {'WAV': '.wav', 'MP3': '.mp3'}}
RIGHTS_STATUS = ('original_documented', 'open_commercial_compatible')


class DraftMediaRightsForm(MediaAuthoringForm):
    def __init__(self, actor, variety, kind, data=None, upload=None, audio_profile=None):
        super().__init__(data, {'file': upload} if upload else None,
            instance=MediaAsset(kind=kind, uploaded_by=actor), actor=actor)
        self.audio_profile = audio_profile
        if kind == 'audio':
            self.initial.update(audio_variety=variety.pk, audio_text=audio_profile['text'],
                audio_source=audio_profile['source'], audio_region=audio_profile.get('region', ''))
            for name in ('audio_variety', 'audio_text', 'audio_source', 'audio_region'):
                self.fields[name].disabled = True
            self.fields['confirm_adult_consent'] = forms.BooleanField(
                label=_('I confirm this evidence covers this adult voice recording and the stated uses.'))
        else:
            del self.fields['rights_adult_speaker_permission']
        self.fields['kind'].disabled = True
        blank = [('', '---------')]
        self.fields['rights_status'].choices = blank + [choice for choice in self.fields['rights_status'].choices
            if choice[0] in RIGHTS_STATUS]
        self.fields['rights_validity'].choices = blank + [choice for choice in self.fields['rights_validity'].choices
            if choice[0] and choice[0] != 'unknown']
        for name in ('rights_validity', 'rights_evidence', *('rights_' + key for key in RIGHTS_LABELS
                if 'rights_' + key in self.fields)):
            self.fields[name].required = True
        self.fields['rights_evidence'].queryset = EvidenceDocument.objects.filter(
            variety=variety, category='rights', revoked=False).order_by('-created_at', 'pk')
        self.rights_fields = [field for field in self if field.name not in ('file', 'kind')
                              and not field.name.startswith('audio_')]

    def clean(self):
        data = super().clean()
        if self.audio_profile is not None:
            self.instance.provenance['audio'] = deepcopy(self.audio_profile)
        if data.get('rights_validity') in ('limited', 'unlimited') and not currently_valid(
                data['rights_validity'], data.get('rights_valid_from'), data.get('rights_valid_until')):
            self.add_error('rights_validity', _('The permission or evidence has expired or lacks a valid expiry date.'))
        return data


def _asset(activity, kind, side, *, lock=False):
    reference = reference_asset_id(getattr(activity, kind + '_' + side), kind)
    assets = MediaAsset.objects.filter(pk=reference, kind=kind).select_related('rights_evidence')
    if lock:
        assets = assets.select_for_update(of=('self',))
    asset = assets.first()
    if (not asset or asset.revoked or asset.technical_metadata.get('format') not in SUFFIXES[kind]
            or (asset.rights_evidence_id and asset.rights_evidence.variety_id != activity.variety_id)):
        return None
    if kind == 'audio' and (asset.rights_status == 'excluded'
            or audio_binding_errors(asset, getattr(activity, 'word_' + side), activity.variety)
            or asset.provenance['audio']['source'] != 'human'
            or not asset.intact or asset.documented):
        return None
    return asset


def _snapshot(actor, activity, field, asset):
    return [str(actor.pk), str(activity.pk), field, activity.fingerprint(), asset.manifest_fingerprint()]


def eligible_media(activity, kind):
    if activity.state != 'draft' or activity.is_demo:
        return []
    return [(side, getattr(activity, 'word_' + side)) for side in ('a', 'b')
            if _asset(activity, kind, side)]


@login_required
@require_http_methods(['GET', 'POST'])
@csrf_protect
def document(request, pk, side, *, kind='image'):
    if side not in ('a', 'b') or kind not in SUFFIXES:
        raise Http404
    from .views import editorial_activities
    from .services import allowed
    activity = get_object_or_404(editorial_activities(request.user).select_related('variety'), pk=pk, is_demo=False)
    if not allowed(request.user, activity.variety, 'edit'):
        raise PermissionDenied
    field = kind + '_' + side
    word = getattr(activity, 'word_' + side)
    is_audio = kind == 'audio'
    salt = 'catalog.audio-rights.v1' if is_audio else SALT

    def rights_form(actor, variety, source, data=None, upload=None):
        return DraftMediaRightsForm(actor, variety, kind, data, upload,
            audio_profile=source.provenance.get('audio') if is_audio else None)

    def page(*, asset=None, form=None, token='', error='', status=200):
        response = render(request, 'editorial/image_rights.html', {'activity': activity, 'word': word,
            'asset': asset, 'form': form, 'rights_context': token, 'error': error, 'is_audio': is_audio}, status=status)
        response['Cache-Control'] = 'private, no-store'
        return response

    if request.method == 'GET':
        asset = _asset(activity, kind, side)
        if activity.state != 'draft' or not asset:
            raise Http404
        token = signing.dumps(_snapshot(request.user, activity, field, asset), salt=salt)
        return page(asset=asset, form=rights_form(request.user, activity.variety, asset), token=token)

    token = request.POST.get('rights_context', '')
    try:
        expected = signing.loads(token, salt=salt, max_age=7200)
    except signing.BadSignature:
        expected = None
    stale = (_('The draft or recording changed. Open the current draft and check the recording again.')
        if is_audio else _('The draft or illustration changed. Open the current draft and review the illustration again.'))
    if not isinstance(expected, list) or expected[:3] != [str(request.user.pk), str(pk), field]:
        return page(error=stale, status=409)

    created_file = None
    database_writes_finished = False
    try:
        with transaction.atomic():
            actor = get_user_model().objects.select_for_update(no_key=True).filter(pk=request.user.pk, is_active=True).first()
            if not actor:
                raise PermissionDenied
            current = Activity.objects.select_for_update(of=('self',)).select_related('variety').filter(pk=pk).first()
            if not current or current.state != 'draft' or current.is_demo:
                return page(error=stale, status=409)
            if not actor.is_superuser and not EditorialGrant.objects.select_for_update().filter(
                    user=actor, variety=current.variety, edit=True).first():
                raise PermissionDenied
            invalidate_integrity()
            source = _asset(current, kind, side, lock=True)
            if not source or expected != _snapshot(actor, current, field, source):
                return page(error=stale, status=409)
            contents = read_bounded(source.file.storage, source.file.name, MAX_BYTES)
            if len(contents) > MAX_BYTES or hashlib.sha256(contents).hexdigest() != source.technical_metadata.get('sha256'):
                return page(error=_('The media bytes are missing or differ from their recorded fingerprint.'), status=409)
            upload = SimpleUploadedFile(kind + SUFFIXES[kind][source.technical_metadata['format']], contents)
            form = rights_form(actor, current.variety, source, request.POST, upload)
            if not form.is_valid():
                return page(asset=source, form=form, token=token, status=422)
            evidence = EvidenceDocument.objects.select_for_update().filter(pk=form.cleaned_data['rights_evidence'].pk,
                variety=current.variety, category='rights', revoked=False).first()
            if not evidence or not evidence.usable:
                form.add_error('rights_evidence', _('The selected rights evidence is missing, expired, changed or revoked.'))
                return page(asset=source, form=form, token=token, status=422)
            asset = form.instance
            asset.rights_evidence = evidence
            setattr(asset, kind + '_predecessor', source)
            try:
                asset.save()
            finally:
                if asset.file._committed and asset.file.name:
                    created_file = (asset.file.storage, asset.file.name)
            setattr(current, field, media_reference(asset))
            current.save(update_fields=[field])
            audit(actor, 'catalog.media_uploaded', asset)
            audit(actor, 'catalog.' + kind + '_rights_documented', current)
            database_writes_finished = True
    except Exception as error:
        # Never remove bytes when the server may have committed the new reference.
        if created_file and not database_writes_finished:
            try:
                created_file[0].delete(created_file[1])
            except STORAGE_ERRORS:
                pass
        if isinstance(error, (*STORAGE_ERRORS, DatabaseError, ValidationError)):
            return page(error=_('The result could not be confirmed. Reopen the draft before trying again.'), status=503)
        raise
    messages.success(request, _('Recording rights saved and linked to the draft.') if is_audio
        else _('Illustration rights saved and linked to the draft.'))
    return redirect('editorial_detail', pk=pk)
