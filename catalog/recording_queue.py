"""Per-side recording worksheet context, never a clinical or rights approval.

The existing dossier is the only media diagnostic source. No file, contract,
speaker identity or storage location is read or exported by this helper.
"""
from urllib.parse import urlencode

from django.conf import settings
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from .services import allowed


RECORDING_CONTEXT_COLUMNS = (
    'audio_work_status',
    'audio_work_label',
    'current_audio_asset_id',
    'current_audio_sha256',
    'audio_reason_codes',
    'audio_current_gaps',
    'editorial_version_url',
    'audio_collection_url',
    'audio_documentation_url',
)

_INTEGRITY_OR_BINDING = frozenset(('media_bytes', 'audio_binding'))
_COLLECTION_STATUSES = frozenset(('audio_missing', 'integrity_or_binding_issue'))
_STATUS_LABELS = {
    'audio_missing': _('Record or attach an audio file'),
    'integrity_or_binding_issue': _('Check the existing file and its link to this word'),
    'documentation_required': _('Complete the audio documentation'),
    'human_review_required': _('Listen and verify during human review'),
}


def _unique_text(values):
    """Keep the dossier's display order while removing repeated diagnostics."""
    return list(dict.fromkeys(value.strip() for value in values
                              if isinstance(value, str) and value.strip()))


def _status(media, reason_codes):
    if not media.get('asset_id') or 'media_missing' in reason_codes:
        return 'audio_missing'
    if _INTEGRITY_OR_BINDING.intersection(reason_codes):
        return 'integrity_or_binding_issue'
    if not media.get('complete') or reason_codes:
        return 'documentation_required'
    # Technical/documentary checks never replace listening and human judgement.
    # This code does not infer the existence or outcome of a content review.
    return 'human_review_required'


def _can_collect(activity, user):
    # The collection endpoint checks permissions afresh when the link is opened.
    return (activity.state == 'draft' and user.is_authenticated and user.is_active
            and allowed(user, activity.variety, 'edit'))


def _documentation_required(media, codes, status):
    return (status == 'documentation_required' and media.get('voice_source') == 'human'
            and not media.get('revoked') and media.get('rights_status') != 'excluded'
            and 'evidence_scope' not in codes)


def recording_context_by_side(activity, dossier, user):
    """Return exactly A/B context rows in RECORDING_CONTEXT_COLUMNS order.

    Callers append these values to their existing exact-version worksheet row
    and retain its CSV escaping. Collection is offered only for a recording or
    binding/integrity task in an editable draft. A documentation-only gap must
    not silently become another recording request. A separate documentation
    link is available for an eligible linked adult take. Opening the normal endpoint
    creates its fresh signed context; no expiring capability is exported here.
    """
    media_by_side = {}
    for media in dossier.get('media', ()):
        side = media.get('side')
        if (side in ('a', 'b') and media.get('kind') == 'audio'
                and media.get('field') == 'audio_' + side):
            media_by_side.setdefault(side, media)

    rows = {}
    for side in ('a', 'b'):
        media = media_by_side.get(side, {})
        codes = _unique_text(media.get('reason_codes', ()))
        if not media and 'media_missing' not in codes:
            codes.append('media_missing')
        rows[side] = (media, codes, _status(media, codes))

    can_edit = (any(status in _COLLECTION_STATUSES or _documentation_required(media, codes, status)
                    for media, codes, status in rows.values()) and _can_collect(activity, user))
    can_document = can_edit and not activity.is_demo
    origin = settings.PUBLIC_ORIGIN.rstrip('/')
    version_url = origin + reverse('editorial_detail', args=[activity.pk])
    upload_url = origin + reverse('editorial_upload')
    result = {}
    for side, (media, codes, status) in rows.items():
        collection_url = ''
        if can_edit and status in _COLLECTION_STATUSES:
            collection_url = upload_url + '?' + urlencode({'draft': str(activity.pk), 'audio_side': side})
        documentation_url = ''
        if can_document and _documentation_required(media, codes, status):
            documentation_url = origin + reverse('editorial_audio_rights', args=[activity.pk, side])
        result[side] = [status, str(_STATUS_LABELS[status]), str(media.get('asset_id') or ''), str(media.get('sha256') or ''),
            ' / '.join(codes), ' / '.join(_unique_text(media.get('reasons', ()))),
            version_url, collection_url, documentation_url]
    return result
