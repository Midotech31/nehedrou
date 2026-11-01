"""Read-only evidence tasks for an exact editorial version; never an approval.

Only identifiers, integrity/validity states and authored activity words leave this
module. Contracts, provenance text, account identities and storage keys do not.
The publication gates remain the authority; this dossier explains their gaps.
"""
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext as _
from qualification.models import EvidenceDocument
from qualification.services import REQUIRED_EVIDENCE, availability_for, has_competence
from qualification.validity import currently_valid
from .audio_checks import audio_binding_errors
from .content_validation import validate_item_definition
from .integrity import activity_reviews, evidence_document
from .readiness import activity_readiness, media_binding_current, referenced_asset
from .services import allowed


RIGHTS_FIELDS = ('holder', 'licence', 'permitted_use', 'territory', 'duration', 'attribution')


def _period_issues(validity, start, end, revoked):
    if revoked:
        return [('revoked', _('The permission or evidence is revoked.'))]
    if validity not in ('limited', 'unlimited'):
        return [('validity_unknown', _('Document the permission period in the structured validity fields.'))]
    if start and timezone.localdate() < start:
        return [('not_yet_valid', _('The permission or evidence is not yet valid.'))]
    if not currently_valid(validity, start, end):
        return [('expired', _('The permission or evidence has expired or lacks a valid expiry date.'))]
    return []


def _document(document, variety, category, expected_sha=None):
    # Even a misbound foreign document must not leak its identifier or metadata.
    if not document:
        return {}, [('evidence_missing', _('Attach the supporting evidence for this requirement.'))]
    if document.variety_id != variety.pk or document.category != category:
        return {}, [('evidence_scope', _('The evidence must concern this spoken variety and evidence category.'))]
    summary = {'id': str(document.pk), 'sha256': document.sha256,
        'validity': document.validity, 'valid_from': document.valid_from,
        'valid_until': document.valid_until, 'revoked': document.revoked}
    issues = _period_issues(document.validity, document.valid_from, document.valid_until, document.revoked)
    if expected_sha is not None and expected_sha != document.sha256:
        issues.append(('evidence_binding', _('The evidence fingerprint does not match the recorded reference.')))
    if not document.intact:
        issues.append(('evidence_bytes', _('The supporting evidence bytes are missing, changed or revoked.')))
    return summary, issues


def _check(checks, key, category, label, owner, action, issues, side='', **extra):
    check = {'key': key, 'category': category, 'side': side, 'label': label,
        'complete': not issues, 'responsible_role': owner, 'action': action,
        'reason_codes': [code for code, message in issues],
        'reasons': list(dict.fromkeys(str(message) for code, message in issues)), **extra}
    checks.append(check)
    return check


def review_dossier(activity):
    """Describe recorded requirements without writing or inferring human results.

    HTTP callers use the normal request integrity scope and prepare_activities.
    Standalone callers may use integrity_scope for the same bounded batch reads.
    """
    checks, media = [], []
    digest = activity.fingerprint()
    editor = _('Content editor and rights holder')
    linguist = _('Competent reviewer for this spoken variety')
    clinician = _('Clinical reviewer')
    publisher = _('Authorised publisher')
    for side in ('a', 'b'):
        word = getattr(activity, 'word_' + side)
        definition = (activity.item_metadata or {}).get(side, {})
        issues = []
        try:
            validate_item_definition(definition, required=True,
                require_targets=activity.kind in ('word_pair', 'phonological_contrast'))
        except ValidationError as exc:
            issues = [('item_definition', message) for message in exc.messages]
        _check(checks, 'definition_' + side, 'definition',
            _('Word definition and phonological context: %(word)s') % {'word': word}, linguist,
            _('Document the meaning, ordered segments, target occurrences and justified variants in a draft.'), issues, side)
        proof = definition.get('familiarity', {}) if isinstance(definition, dict) else {}
        proof = proof if isinstance(proof, dict) else {}
        document = evidence_document(proof.get('evidence'))
        summary, issues = _document(document, activity.variety, 'familiarity', proof.get('sha256', ''))
        _check(checks, 'familiarity_' + side, 'familiarity',
            _('Word and image familiarity: %(word)s') % {'word': word}, clinician,
            _('Collect unprimed naming and recognition observations under a prospectively defined protocol; attach the actual evidence and its fingerprint.'),
            issues, side, evidence=summary)
        for kind in ('image', 'audio'):
            field = kind + '_' + side
            asset = referenced_asset(getattr(activity, field), kind)
            issues, summary = [], {}
            evidence = {}
            if not asset:
                issues.append(('media_missing', _('Upload and select a protected media asset for this exact word.')))
            else:
                provenance = asset.provenance if isinstance(asset.provenance, dict) else {}
                required = RIGHTS_FIELDS + (('adult_speaker_permission',) if kind == 'audio' else ())
                missing = [key for key in required if not isinstance(provenance.get(key), str) or not provenance[key].strip()]
                if not asset.intact:
                    issues.append(('media_bytes', _('The media bytes are missing or differ from their recorded fingerprint.')))
                if not asset.rights.strip() or asset.rights_status not in ('original_documented', 'open_commercial_compatible'):
                    issues.append(('rights_status', _('Usage rights are unknown, excluded or still require permission.')))
                issues.extend(_period_issues(asset.rights_validity, asset.rights_valid_from, asset.rights_valid_until, asset.revoked))
                if missing:
                    issues.append(('rights_fields', _('Complete the structured rights holder, licence, use, territory, duration, attribution and any adult speaker permission.')))
                evidence, document_issues = _document(asset.rights_evidence, activity.variety, 'rights')
                issues.extend(document_issues)
                if kind == 'audio':
                    issues.extend(('audio_binding', reason) for reason in audio_binding_errors(asset, word, activity.variety))
                profile = provenance.get('audio', {})
                summary = {'asset_id': str(asset.pk), 'sha256': asset.technical_metadata.get('sha256', ''),
                    'rights_status': asset.rights_status, 'rights_validity': asset.rights_validity,
                    'rights_valid_from': asset.rights_valid_from, 'rights_valid_until': asset.rights_valid_until,
                    'revoked': asset.revoked, 'missing_rights_fields': missing,
                    'voice_source': profile.get('source', '') if isinstance(profile, dict) and profile.get('source') in ('human', 'synthetic', 'unspecified') else ''}
            label = (_('Illustration: %(word)s') if kind == 'image' else _('Recording: %(word)s')) % {'word': word}
            check = _check(checks, field, kind, label, editor,
                _('Obtain the actual permissions and valid evidence, then upload documented media; a written rights claim alone is insufficient.'),
                issues, side, media=summary, evidence=evidence)
            media.append({'field': field, 'side': side, 'word': word, 'kind': kind,
                **summary, 'evidence': evidence, 'complete': check['complete'],
                'reason_codes': check['reason_codes'], 'reasons': check['reasons']})
        transcription = getattr(activity, 'transcription_' + side).strip()
        _check(checks, 'transcription_' + side, 'transcription',
            _('Transcription: %(word)s') % {'word': word}, linguist,
            _('Compare the proposed transcription with the exact recording before recording a linguistic decision.'),
            [] if transcription else [('transcription_missing', _('Reviewed audio and transcription are required.'))], side)
    binding = media_binding_current(activity)
    _check(checks, 'media_manifest', 'manifest', _('Exact media and rights manifest'), editor,
        _('Complete the media evidence, then submit the draft for review to bind its current media manifest.'),
        [] if binding else [('manifest_stale', _('The exact media and commercial rights manifest is missing, changed or revoked.'))])
    reviews = activity_reviews(activity)
    # Exact duplicate side-specific candidates are a human review prompt only;
    # shared forms may be intentional in a local variety.
    metadata = activity.item_metadata if isinstance(activity.item_metadata, dict) else {}
    definition_a, definition_b = metadata.get('a', {}), metadata.get('b', {})
    candidates_a = definition_a.get('family_word_candidates', []) if isinstance(definition_a, dict) else []
    candidates_b = definition_b.get('family_word_candidates', []) if isinstance(definition_b, dict) else []
    current_linguistic_decision = next(
        (row for row in reviews if row.kind == 'linguistic' and row.content_digest == digest),
        None,
    )
    current_linguistic_approval = bool(
        current_linguistic_decision and current_linguistic_decision.approved
        and allowed(current_linguistic_decision.reviewer, activity.variety, 'linguistic_review')
        and has_competence(current_linguistic_decision.reviewer, activity.variety, 'linguistic')
    )
    if (activity.word_a.strip() != activity.word_b.strip() and candidates_a and
            candidates_a == candidates_b and not current_linguistic_approval):
        _check(checks, 'family_candidate_lists', 'linguistic_metadata',
            _('Check word-specific family vocabulary candidates'), linguist,
            _('Confirm that the candidate lists belong to the intended word and local variety. Record the rationale if the same forms are intentionally shared; otherwise correct the draft before reviewing it.'),
            [('candidate_list_reuse', _('The two different words have identical family-vocabulary candidate lists; this may be intentional, but requires an explicit linguistic check.'))])
    selected = []
    for discipline, owner in (('clinical', clinician), ('linguistic', linguist)):
        decision = next((row for row in reviews if row.kind == discipline and row.content_digest == digest), None)
        issues = []
        if not decision:
            issues.append(('review_stale' if any(row.kind == discipline for row in reviews) else 'review_missing',
                _('Record a new decision for this exact content fingerprint.')))
        elif not decision.approved:
            issues.append(('changes_requested', _('The latest decision for this exact version requests changes.')))
        else:
            capability = 'clinical_review' if discipline == 'clinical' else 'linguistic_review'
            if not allowed(decision.reviewer, activity.variety, capability) or not has_competence(decision.reviewer, activity.variety, discipline):
                issues.append(('review_authority', _('The decision owner no longer has the required permission or current competence declaration.')))
            if not binding:
                issues.append(('review_media_binding', _('Complete the current media evidence before a review can qualify.')))
        selected.append(decision)
        _check(checks, 'review_' + discipline, 'review',
            _('Clinical decision') if discipline == 'clinical' else _('Linguistic decision'), owner,
            _('Use the existing review form after checking this exact version; the two approving reviewers must be different people.'), issues)
    independent = bool(all(selected) and selected[0].reviewer_id != selected[1].reviewer_id)
    _check(checks, 'independent_reviews', 'review', _('Two distinct reviewers'), publisher,
        _('Arrange independent clinical and linguistic decisions by two competent people.'),
        [] if independent else [('independent_reviewers', _('Clinical and linguistic approval must come from two different people.'))])
    availability = availability_for('practice', activity.variety, digest)
    decision = availability['decision']
    for category in REQUIRED_EVIDENCE:
        entry = (decision.evidence or {}).get(category, {}) if decision and isinstance(decision.evidence, dict) else {}
        entry = entry if isinstance(entry, dict) else {}
        summary, issues = _document(evidence_document(entry.get('id')), activity.variety, category, entry.get('sha256', ''))
        _check(checks, 'availability_' + category, 'availability_evidence',
            _('Availability evidence: %(category)s') % {'category': dict(EvidenceDocument._meta.get_field('category').choices)[category]},
            publisher, _('Attach current evidence in this category to the authorised availability decision for this exact fingerprint.'), issues, evidence=summary)
    _check(checks, 'availability', 'availability', _('Authorised availability decision'), publisher,
        _('Record an explicit availability decision for the exact version and documented scope after the evidence is reviewed.'),
        [('availability_gate', reason) for reason in availability['reasons']])
    readiness = activity_readiness(activity, require_availability=True)
    tasks = [check for check in checks if not check['complete']]
    return {'schema': 'nehedrou-evidence-dossier-v1', 'checked_at': timezone.now().isoformat(),
        'activity_id': str(activity.pk), 'series': str(activity.series), 'version': activity.version, 'content_sha256': digest,
        'variety': activity.variety.code, 'is_demo': activity.is_demo, 'state': activity.state,
        'clinical_validation': 'not_assessed_by_dossier', 'checks': checks, 'tasks': tasks,
        'task_count': len(tasks), 'media': media, 'blocking_reasons': readiness['reasons']}
