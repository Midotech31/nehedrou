"""Exact-byte and evidence checks, independent of publication state."""
from urllib.parse import urlsplit
from uuid import UUID
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _
from .models import MediaAsset
from .content_validation import validate_item_metadata

def referenced_asset(reference, kind):
    try:
        if kind == 'image' and reference.startswith('editorial/asset-'):
            asset_id = UUID(reference[len('editorial/asset-'):])
        elif kind == 'audio':
            source, origin = urlsplit(reference), urlsplit(settings.PUBLIC_ORIGIN)
            parts = source.path.strip('/').split('/')
            if source.scheme != origin.scheme or source.netloc != origin.netloc or source.query or source.fragment or len(parts) != 3 or parts[0] not in dict(settings.LANGUAGES) or parts[1] != 'media':
                return None
            asset_id = UUID(parts[2])
        else:
            return None
    except (ValueError, AttributeError):
        return None
    return MediaAsset.objects.select_related('rights_evidence').filter(pk=asset_id,kind=kind).first()

def snapshot_media(activity):
    snapshot = {}
    for key, kind in [('image_a','image'),('image_b','image'),('audio_a','audio'),('audio_b','audio')]:
        asset = referenced_asset(getattr(activity,key),kind)
        if asset:
            snapshot[key] = {'asset':str(asset.pk),'sha256':asset.technical_metadata.get('sha256',''),'manifest':asset.manifest_fingerprint()}
    return snapshot

def media_binding_current(activity):
    if set(activity.media_manifest or {}) != {'image_a','image_b','audio_a','audio_b'}:
        return False
    for key,kind in [('image_a','image'),('image_b','image'),('audio_a','audio'),('audio_b','audio')]:
        asset = referenced_asset(getattr(activity,key),kind)
        if not asset or not asset.documented or asset.rights_evidence.variety_id != activity.variety_id:
            return False
    return activity.media_manifest == snapshot_media(activity)

def activity_content_reasons(activity):
    from qualification.models import EvidenceDocument
    reasons = []
    try:
        validate_item_metadata(activity.item_metadata,required=True,require_targets=activity.kind in ['word_pair','phonological_contrast'])
    except ValidationError as exc:
        reasons.extend(exc.messages)
    for key in ['a','b']:
        entry = (activity.item_metadata or {}).get(key,{})
        proof = entry.get('familiarity',{}) if isinstance(entry,dict) else {}
        try:
            document = EvidenceDocument.objects.filter(pk=UUID(str(proof.get('evidence',''))),category='familiarity',variety=activity.variety).first()
        except (ValueError, AttributeError):
            document = None
        if not document or proof.get('sha256') != document.sha256 or not document.intact:
            reasons.append(_('Missing intact word and image familiarity evidence: %(word)s.') % {'word':getattr(activity,'word_'+key)})
    if not media_binding_current(activity):
        reasons.append(_('The exact media and commercial rights manifest is missing, changed or revoked.'))
    if not activity.transcription_a or not activity.transcription_b:
        reasons.append(_('Reviewed audio and transcription are required.'))
    return list(dict.fromkeys(reasons))

def activity_readiness(activity,require_availability=True):
    reasons = activity_content_reasons(activity)
    if not activity.has_current_reviews():
        reasons.append(_('Two current approvals by distinct competent reviewers are required.'))
    if require_availability:
        from qualification.services import availability_for
        reasons.extend(availability_for('practice',activity.variety,activity.fingerprint())['reasons'])
    return {'ready':not reasons,'reasons':list(dict.fromkeys(reasons))}
