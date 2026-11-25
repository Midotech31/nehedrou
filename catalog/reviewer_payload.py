"""Allowlisted read-only definitions for scoped editorial reviewers.

This is presentation only. The ordinary review/competence/publication services
remain authoritative; documentary integrity is never a clinical approval.
"""
import re
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from catalog.integrity import evidence_document
from catalog.models import Activity, EditorialGrant
from qualification.validity import currently_valid


def text(value):
    return value if isinstance(value, str) and value.strip() else ''


def evidence_status(activity, proof):
    proof = proof if isinstance(proof, dict) else {}
    result = {'state': 'missing', 'label': _('No evidence reference recorded.'), 'reference': '', 'sha256': '', 'url': ''}
    if not proof.get('evidence'):
        return result
    document = evidence_document(proof['evidence'])
    if not document or document.variety_id != activity.variety_id or document.category != 'familiarity':
        result.update(state='unavailable', label=_('Evidence reference unavailable for this variety and category.'))
        return result
    result['reference'] = str(document.pk)
    recorded_sha = text(proof.get('sha256'))
    result['sha256'] = recorded_sha if re.fullmatch(r'[0-9a-fA-F]{64}', recorded_sha) else ''
    if document.revoked:
        result.update(state='revoked', label=_('Evidence revoked.'))
        return result
    intact = document.intact
    if intact:
        result['url'] = reverse('qualification:evidence_file', args=[document.pk])
    if not result['sha256']:
        result.update(state='fingerprint_missing', label=_('No evidence fingerprint recorded.'))
    elif recorded_sha != document.sha256:
        result.update(state='fingerprint_mismatch', label=_('Recorded evidence fingerprint differs from the document.'))
    elif not intact:
        result.update(state='bytes_changed', label=_('Evidence bytes missing or changed.'))
    elif not currently_valid(document.validity, document.valid_from, document.valid_until):
        result.update(state='validity_unknown', label=_('Evidence validity is unknown, expired or not yet current.'))
    else:
        result.update(state='current', label=_('Recorded reference matches intact evidence within its declared validity period.'))
    return result


def reviewer_payload(activity, actor):
    # The detail route already scopes the activity. Keep this reusable include
    # independently private, including when called without that route's context.
    if not actor or not actor.is_authenticated or (not actor.is_superuser and not
            EditorialGrant.objects.filter(user=actor, variety_id=activity.variety_id).exists()):
        return None
    mode = activity.response_mode if activity.response_mode in dict(Activity.RESPONSE_CHOICES) else ''
    target = activity.requested_target
    target_word = ''
    if mode == 'matching' and target in ('a', 'b'):
        target_state, target_label = target, dict(Activity._meta.get_field('requested_target').choices)[target]
        target_word = getattr(activity, 'word_' + target)
    elif mode == 'matching' and not target:
        target_state, target_label = 'random', _('Either word may be requested; the activity link selects the picture.')
    elif mode in ('free', 'observation') and not target:
        target_state, target_label = 'none', _('No requested picture for this response mode.')
    else:
        target_state, target_label = 'unknown', _('Unknown stored task value.')
    positions = {'initial': _('Initial'), 'medial': _('Medial'), 'final': _('Final'), 'other': _('Other')}
    metadata = activity.item_metadata if isinstance(activity.item_metadata, dict) else {}
    words = []
    for side in ('a', 'b'):
        entry = metadata.get(side, {})
        entry = entry if isinstance(entry, dict) else {}
        proof = entry.get('familiarity', {})
        note = text(proof.get('note')) if isinstance(proof, dict) else text(proof)
        segments = entry.get('segments', [])
        segments = segments if isinstance(segments, list) else []
        targets = entry.get('target_occurrences', [])
        targets = targets if isinstance(targets, list) else []
        variants = entry.get('accepted_variants', [])
        variants = variants if isinstance(variants, list) else []
        words.append({'side': side, 'word': getattr(activity, 'word_' + side),
            'meaning': text(entry.get('meaning')),
            'segments': [{'index': index, 'phoneme': text(value)} for index, value in enumerate(segments)],
            'targets': [{'index': row.get('index') if type(row.get('index')) is int and row['index'] >= 0 else None,
                         'phoneme': text(row.get('phoneme')), 'position': positions.get(text(row.get('position')), _('Unknown'))}
                        for row in targets if isinstance(row, dict)],
            'variants': [{'ipa': text(row.get('ipa')), 'reason': text(row.get('reason'))}
                         for row in variants if isinstance(row, dict)],
            'familiarity_note': note, 'evidence': evidence_status(activity, proof)})
    return {'kind_label': dict(Activity.KIND_CHOICES).get(activity.kind, _('Unknown')),
            'response_mode': mode or 'unknown', 'response_label': dict(Activity.RESPONSE_CHOICES).get(mode, _('Unknown')),
            'target_state': target_state, 'target_label': target_label, 'target_word': target_word, 'words': words}
