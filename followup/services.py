from django.utils.translation import gettext as _
"""Scoped, transactional human follow-up. No automatic speech evaluation."""
import copy
import hashlib
import json
import uuid
from collections import defaultdict
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from core.access import professional_children, visible_children
from core.models import Organization, Membership, User, AuditEvent
from core.services import audit, check_entitlement, lock_clinical_child
from catalog.models import MediaAsset
from catalog.services import allowed, require_review_snapshot
from .models import (ClinicalGoal, ProbeDefinition, ProbeReview, ProbeAdministration, ProbeRating,
                     ProbeRatingRevision, ProbeExposure, ParentCoaching, HomePracticeFeedback, RATING_FIELDS)
from .validation import validate_items, validate_conditions, validate_variants, validate_rating, word_key, phoneme_key, reserve_word_key, target_match_errors, validate_observation_target

DEFINITION_FIELDS = ['variety', 'title', 'protocol', 'task', 'target_phoneme', 'target_position', 'target_scope', 'items', 'rights', 'rights_status', 'evidence', 'is_demo']
GOAL_FIELDS = ['variety', 'target_phoneme', 'contrast', 'target_position', 'target_scope', 'context', 'rationale', 'expected_realization', 'accepted_variants', 'functional_goal', 'review_date', 'external_assessment_status', 'external_assessment_note', 'probe_definition']


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


def _lock_definition(definition):
    if definition.organization_id:
        Organization.objects.select_for_update().get(pk=definition.organization_id)
    return ProbeDefinition.objects.select_for_update().get(pk=definition.pk)


def definition_queryset(actor):
    if not actor.is_authenticated:
        return ProbeDefinition.objects.none()
    if actor.is_superuser:
        return ProbeDefinition.objects.all()
    editorial_varieties = actor.editorialgrant_set.values('variety_id')
    clinical_varieties = professional_children(actor).values('varieties')
    orgs = Membership.objects.filter(user=actor, active=True).values('organization_id')
    return ProbeDefinition.objects.filter(Q(variety_id__in=editorial_varieties) |
        (Q(variety_id__in=clinical_varieties) & (Q(organization__isnull=True) | Q(organization_id__in=orgs)))).distinct()


def can_edit_definition(actor, definition):
    return allowed(actor, definition.variety, 'edit') or (
        definition.authored_by_id == actor.pk and definition.organization_id is not None
        and Membership.objects.filter(user=actor, organization_id=definition.organization_id, active=True).exists()
        and professional_children(actor).filter(organization_id=definition.organization_id, varieties=definition.variety).exists())


def professional_administrations(actor):
    return ProbeAdministration.objects.filter(child__in=professional_children(actor)).select_related('goal', 'definition', 'child', 'definition__variety')


def media_manifest(items):
    manifest = {}
    for item in items:
        for key, kind in [('image_asset', 'image'), ('audio_asset', 'audio')]:
            reference = item.get(key)
            entry = {'reference': reference, 'kind': kind, 'available': False}
            if reference:
                try:
                    asset = MediaAsset.objects.filter(pk=uuid.UUID(str(reference)), kind=kind).first()
                except (ValueError, TypeError, ValidationError):
                    asset = None
                if asset:
                    entry.update(sha256=asset.technical_metadata.get('sha256'), rights=asset.rights,
                        metadata=asset.technical_metadata, file=asset.file.name)
                    # Include structured evidence when the catalog supplies it.
                    for field in ['rights_status', 'provenance', 'rights_validity', 'rights_valid_from', 'rights_valid_until', 'revoked', 'revocation_reason']:
                        if hasattr(asset, field):
                            entry[field] = str(getattr(asset, field)) if field in ['rights_valid_from', 'rights_valid_until'] and getattr(asset, field) else getattr(asset, field)
                    proof = asset.rights_evidence if asset.rights_evidence_id else None
                    entry['rights_evidence'] = {'id': str(proof.pk), 'sha256': proof.sha256, 'intact': proof.intact, 'revoked': proof.revoked,
                        'validity': proof.validity, 'valid_from': str(proof.valid_from) if proof.valid_from else None,
                        'valid_until': str(proof.valid_until) if proof.valid_until else None, 'usable': proof.usable} if proof else None
                    if asset.file.storage.exists(asset.file.name):
                        with asset.file.open('rb') as stream:
                            actual = hashlib.sha256(stream.read(15 * 1024 * 1024 + 1)).hexdigest()
                        entry['actual_sha256'] = actual
                        entry['available'] = bool(entry['sha256'] and actual == entry['sha256'] and asset.documented and asset.intact)
            manifest[item['id'] + ':' + key] = entry
    return manifest


def _current_reviews(definition):
    digest = definition.fingerprint()
    decisions = []
    for kind in ['clinical', 'linguistic']:
        decision = definition.reviews.filter(kind=kind, content_digest=digest).order_by('-created_at', '-pk').first()
        if not decision or not decision.approved:
            return []
        try:
            from qualification.services import has_competence
            if not has_competence(decision.author, definition.variety, kind):
                return []
        except ImportError:
            return []
        if not allowed(decision.author, definition.variety, kind + '_review'):
            return []
        decisions.append(decision)
    return decisions if len({d.author_id for d in decisions}) == 2 else []


def content_reasons(definition):
    reasons = []
    if definition.is_demo:
        reasons.append(_('Demonstration protocols cannot be qualified for real use.'))
    if not definition.target_scope:
        reasons.append(_('Document structured target position and context before real use.'))
    if definition.rights_status not in ['original_documented', 'open_commercial_compatible'] or not definition.rights.strip():
        reasons.append(_('Document the protocol rights and their evidence.'))
    from qualification.models import EvidenceDocument
    for field, category in [('rights_evidence', 'rights'), ('familiarity_evidence', 'familiarity'), ('linguistic_evidence', 'linguistic')]:
        evidence = definition.evidence.get(field)
        proof = None
        if isinstance(evidence, dict):
            try:
                proof = EvidenceDocument.objects.filter(pk=uuid.UUID(str(evidence.get('id'))), variety=definition.variety, category=category).first()
            except (ValueError, TypeError):
                pass
        if not proof or proof.sha256 != evidence.get('sha256') or not proof.usable:
            reasons.append(_('Exact intact rights, familiarity and linguistic evidence is required for this protocol version.'))
            break
    if any(not item.get('familiarity_verified') or not item.get('reviewed') for item in definition.items):
        reasons.append(_('Human item familiarity and linguistic review evidence are missing.'))
    for item in definition.items:
        segments = item.get('segments', [])
        index = item['target_occurrence_index']
        occurrences = item.get('target_occurrences', [])
        documented_target = any(o['index'] == index and phoneme_key(o['phoneme']) == phoneme_key(definition.target_phoneme)
            and (not definition.target_scope or o.get('position') == definition.target_scope['position']) for o in occurrences)
        if not item.get('meaning', '').strip() or not segments or index >= len(segments) or phoneme_key(segments[index]) != phoneme_key(definition.target_phoneme) or not documented_target:
            reasons.append(_('Real use requires a documented meaning and phonemic segmentation with a target index matching the protocol phoneme.'))
            break
    manifest = media_manifest(definition.items)
    from catalog.audio_checks import audio_binding_errors
    for item in definition.items:
        for field, kind in [('image_asset', 'image'), ('audio_asset', 'audio')]:
            if not item.get(field):
                continue
            asset = MediaAsset.objects.select_related('rights_evidence').filter(pk=item[field], kind=kind).first()
            if asset:
                if not asset.rights_evidence_id or asset.rights_evidence.variety_id != definition.variety_id:
                    reasons.append(_('Exact reviewed image/audio files with rights are missing or changed.'))
                if kind == 'audio':
                    reasons.extend(audio_binding_errors(asset, item.get('word', ''), definition.variety))
    if any(not row['available'] for row in manifest.values()):
        reasons.append(_('Exact reviewed image/audio files with rights are missing or changed.'))
    return reasons


def readiness_reasons(definition):
    reasons = content_reasons(definition)
    if not _current_reviews(definition):
        reasons.append(_('Two distinct human reviewers with current, independently verified clinical and linguistic competence are required.'))
    return reasons


@transaction.atomic
def create_goal(actor, child, data):
    child = lock_clinical_child(actor, child)
    if not child.active:
        raise ValidationError(_('Archived profiles cannot acquire a new clinical goal.'))
    check_entitlement(child.organization)
    values = {k: data[k] for k in GOAL_FIELDS if k in data}
    definition = values.get('probe_definition')
    if definition:
        definition = ProbeDefinition.objects.select_for_update().get(pk=definition.pk)
        if not definition_queryset(actor).filter(pk=definition.pk).exists():
            raise PermissionDenied
        values['probe_definition'] = definition
    reserves = [word_key(i['word']) for i in definition.items if i['exposure_plan'] == 'reserved'] if definition else []
    goal = ClinicalGoal.objects.create(child=child, organization=child.organization, author=actor, reserved_words=reserves, **values)
    audit(actor, 'followup.goal_created', goal, child.organization)
    return goal


@transaction.atomic
def close_goal(actor, goal):
    """Close a current goal without altering observations or reserved snapshots."""
    if not professional_children(actor).filter(pk=goal.child_id).exists():
        raise PermissionDenied
    child = lock_clinical_child(actor, goal.child)
    goal = ClinicalGoal.objects.select_for_update().get(pk=goal.pk, child=child)
    if goal.active:
        goal.active = False
        goal.save(update_fields=['active'])
        audit(actor, 'followup.goal_closed', goal, child.organization)
    return goal


@transaction.atomic
def create_definition(actor, data):
    variety = data['variety']
    org = None
    if not allowed(actor, variety, 'edit'):
        child = professional_children(actor).filter(varieties=variety, active=True).first()
        if not child:
            raise PermissionDenied
        lock_clinical_child(actor, child)
        org = child.organization
    values = {k: data[k] for k in DEFINITION_FIELDS if k in data}
    definition = ProbeDefinition.objects.create(organization=org, authored_by=actor, state='draft', **values)
    audit(actor, 'followup.protocol_created', definition, org)
    return definition


@transaction.atomic
def update_definition(actor, definition, data):
    definition = _lock_definition(definition)
    if definition.state != 'draft' or not can_edit_definition(actor, definition):
        raise PermissionDenied
    for key in DEFINITION_FIELDS:
        if key in data:
            if key == 'variety' and data[key].pk != definition.variety_id:
                raise ValidationError(_('A protocol series must retain its spoken variety.'))
            if key == 'is_demo' and data[key] != definition.is_demo:
                raise ValidationError(_('A protocol version cannot change its demonstration identity.'))
            setattr(definition, key, data[key])
    definition.save()
    audit(actor, 'followup.protocol_saved', definition, definition.organization)
    return definition


@transaction.atomic
def clone_definition(actor, definition):
    if not definition_queryset(actor).filter(pk=definition.pk).exists():
        raise PermissionDenied
    source = ProbeDefinition.objects.get(pk=definition.pk)
    if not (allowed(actor, source.variety, 'edit') or professional_children(actor).filter(varieties=source.variety).exists()):
        raise PermissionDenied
    org = source.organization
    if not allowed(actor, source.variety, 'edit'):
        child = professional_children(actor).filter(varieties=source.variety, active=True).first()
        if not child:
            raise PermissionDenied
        lock_clinical_child(actor, child)
        org = child.organization
    elif org:
        Organization.objects.select_for_update().get(pk=org.pk)
    # Practice locks precede the single stable series lock, including audit FKs.
    first = ProbeDefinition.objects.filter(series=source.series).order_by('version').first()
    ProbeDefinition.objects.select_for_update().get(pk=first.pk)
    source = ProbeDefinition.objects.get(pk=source.pk)
    values = {k: copy.deepcopy(getattr(source, k)) for k in DEFINITION_FIELDS}
    version = ProbeDefinition.objects.filter(series=source.series).order_by('-version').first().version + 1
    result = ProbeDefinition.objects.create(series=source.series, version=version, organization=org, authored_by=actor, state='draft', **values)
    audit(actor, 'followup.protocol_cloned', result, org)
    return result


@transaction.atomic
def review_definition(actor, definition, kind, approved, note, competence, *, expected_digest):
    definition = _lock_definition(definition)
    from catalog.integrity import invalidate_integrity
    invalidate_integrity()
    if kind not in ['clinical', 'linguistic'] or not allowed(actor, definition.variety, kind + '_review'):
        raise PermissionDenied
    require_review_snapshot(definition, expected_digest)
    if approved:
        from qualification.services import has_competence
        if not has_competence(actor, definition.variety, kind):
            raise ValidationError(_('Independently verified competence for this variety is required.'))
    decision = ProbeReview.objects.create(definition=definition, author=actor, kind=kind, approved=approved, note=note, competence=competence)
    audit(actor, 'followup.protocol_reviewed', definition, definition.organization)
    return decision


DEFINITION_TRANSITIONS = {
    'draft': ('review',), 'review': ('draft', 'approved'),
    'approved': ('draft', 'published'), 'published': ('withdrawn',), 'withdrawn': (),
}


def definition_transition_capability(target):
    return 'publish' if target in ['approved', 'published', 'withdrawn'] else 'edit'


def can_transition_definition(actor, definition, target):
    capability = definition_transition_capability(target)
    return (allowed(actor, definition.variety, capability)
            or (capability == 'edit' and can_edit_definition(actor, definition)))


def definition_transition_choices(actor, definition):
    labels = dict(ProbeDefinition._meta.get_field('state').choices)
    labels['approved'] = _('Internally reviewed')
    return [(target, labels[target]) for target in DEFINITION_TRANSITIONS.get(definition.state, ())
            if can_transition_definition(actor, definition, target)
            and not (definition.is_demo and target in ['approved', 'published'])]


@transaction.atomic
def transition_definition(actor, definition, target):
    definition = _lock_definition(definition)
    from catalog.integrity import invalidate_integrity
    invalidate_integrity()
    if not can_transition_definition(actor, definition, target):
        raise PermissionDenied
    if target not in DEFINITION_TRANSITIONS[definition.state]:
        raise ValidationError(_('This protocol transition is not allowed.'))
    if definition.is_demo and target in ['approved', 'published']:
        raise ValidationError(_('A demonstration remains an unapproved simulation.'))
    if target == 'approved' and not _current_reviews(definition):
        raise ValidationError(_('Two distinct, current human reviews are required.'))
    definition.state = target
    definition.save()
    audit(actor, 'followup.protocol_' + target, definition, definition.organization)
    return definition


def _exposure_status(child, variety, word, at):
    from care.models import PracticeSession
    events = ProbeExposure.objects.filter(child=child, variety=variety, occurred_at__lte=at)
    history = PracticeSession.objects.filter(item__program__child=child, item__program__variety=variety,
        created_at__lte=at, completion='completed')
    if variety.language == 'ar':
        key = reserve_word_key(word, variety)
        # Read conservative aliases without changing append-only events or snapshots.
        matching_events = [event for event in events.order_by('-occurred_at', '-created_at', '-pk')
                           if reserve_word_key(event.normalized_word, variety) == key]
        if any(event.status == 'trained' for event in matching_events):
            return 'trained'
        if any(any(reserve_word_key(value, variety) == key for value in pair)
               for pair in history.values_list('item__activity__word_a', 'item__activity__word_b').iterator()):
            return 'trained'
        latest = matching_events[0] if matching_events else None
    else:
        events = events.filter(normalized_word=word_key(word))
        if events.filter(status='trained').exists():
            return 'trained'
        if history.filter(Q(item__activity__word_a__iexact=word) | Q(item__activity__word_b__iexact=word)).exists():
            return 'trained'
        latest = events.order_by('-occurred_at', '-created_at', '-pk').first()
    if latest:
        return latest.status
    # Assignment alone does not establish actual training or non-exposure.
    return 'uncertain'


@transaction.atomic
def start_administration(actor, goal, definition, conditions=None, familiarity=None, key=None, *, observation_scope='goal', alternate_context_label='', alternate_context_reason=''):
    child = lock_clinical_child(actor, goal.child)
    # Serialise actor mutations while allowing independent FK audit references.
    User.objects.select_for_update(no_key=True).get(pk=actor.pk)
    goal = ClinicalGoal.objects.select_for_update().get(pk=goal.pk, child=child)
    definition = ProbeDefinition.objects.select_for_update().get(pk=definition.pk)
    if not child.active or not goal.active or not definition_queryset(actor).filter(pk=definition.pk).exists():
        raise PermissionDenied
    check_entitlement(child.organization)
    conditions = conditions or {}
    familiarity = familiarity or {}
    validate_conditions(conditions)
    if not isinstance(familiarity, dict) or set(familiarity) != {i['id'] for i in definition.items}:
        raise ValidationError(_('Check familiarity for every protocol item.'))
    for value in familiarity.values():
        if not isinstance(value, dict) or set(value) - {'familiar', 'note'} or not isinstance(value.get('familiar'), bool) or not isinstance(value.get('note', ''), str) or len(value.get('note', '')) > 2000:
            raise ValidationError(_('Record item familiarity and uncertainty explicitly.'))
    validate_observation_target(goal, definition, observation_scope, alternate_context_label, alternate_context_reason)
    key = uuid.UUID(str(key)) if key else uuid.uuid4()
    body = {'goal': str(goal.pk), 'definition': str(definition.pk), 'conditions': conditions, 'familiarity': familiarity,
        'observation_scope': observation_scope, 'alternate_context_label': alternate_context_label, 'alternate_context_reason': alternate_context_reason}
    digest = _digest(body)
    existing = ProbeAdministration.objects.filter(professional=actor, idempotency_key=key).first()
    if existing:
        if existing.payload_digest != digest:
            raise ValidationError(_('This administration key was already used with different conditions.'))
        return existing
    goal_variants = {variant['id']: variant for variant in goal.accepted_variants}
    for item in definition.items:
        if any(variant['id'] in goal_variants and variant != goal_variants[variant['id']] for variant in item.get('accepted_variants', [])):
            raise ValidationError(_('Variant identifiers shared by the goal and an item must have identical definitions.'))
    from catalog.integrity import invalidate_integrity
    invalidate_integrity()
    if definition.state == 'withdrawn':
        raise ValidationError(_('A withdrawn protocol cannot start a new observation.'))
    if definition.is_demo:
        if not settings.DEMO_MODE or not child.code.endswith('· fictif'):
            raise ValidationError(_('Simulation protocols require demonstration mode and an explicitly fictitious child.'))
    else:
        if definition.state != 'published' or not definition.ready:
            raise ValidationError(_('A complete published protocol with current reviews is required.'))
        if goal.external_assessment_status != 'confirmed' or not all(x['familiar'] for x in familiarity.values()):
            raise ValidationError(_('Confirm the external evaluation and all item familiarity before real use.'))
        from qualification.services import availability_for
        decision = availability_for('production_followup', definition.variety, definition.fingerprint())
        if not decision['available']:
            raise ValidationError(decision['reasons'] or [_('The intended scope has not been released for real use.')])
    at = timezone.now()
    items = copy.deepcopy(definition.items)
    for item in items:
        item['exposure_at_start'] = _exposure_status(child, definition.variety, item['word'], at)
    snapshot = {'schema_version': 2, 'definition_id': str(definition.pk), 'series': str(definition.series),
        'version': definition.version, 'digest': definition.fingerprint(), 'title': definition.title,
        'variety': definition.variety.code, 'target': definition.target_phoneme, 'target_position': definition.target_position,
        'target_scope': copy.deepcopy(definition.target_scope), 'observation_scope': observation_scope,
        'alternate_context_label': alternate_context_label, 'alternate_context_reason': alternate_context_reason,
        'protocol': definition.protocol, 'task': definition.task, 'is_demo': definition.is_demo, 'items': items,
        'media': media_manifest(definition.items),
        'reserved_words': [word_key(i['word']) for i in items if i['exposure_plan'] == 'reserved'],
        'goal': {k: copy.deepcopy(getattr(goal, k)) for k in ['target_phoneme', 'target_position', 'target_scope', 'contrast', 'context', 'rationale',
            'expected_realization', 'accepted_variants', 'functional_goal', 'external_assessment_status', 'external_assessment_note']}}
    snapshot['goal'].update(author_id=str(goal.author_id), review_date=goal.review_date.isoformat() if goal.review_date else None)
    admin = ProbeAdministration.objects.create(child=child, organization=child.organization, goal=goal,
        definition=definition, professional=actor, idempotency_key=key, payload_digest=digest, conditions=conditions,
        familiarity=familiarity, snapshot=snapshot, started_at=at, observation_scope=observation_scope,
        alternate_context_label=alternate_context_label, alternate_context_reason=alternate_context_reason)
    audit(actor, 'followup.observation_started', admin, child.organization)
    return admin


def _lock_admin(actor, reference):
    child = lock_clinical_child(actor, reference.child)
    admin = ProbeAdministration.objects.select_for_update().get(pk=reference.pk, child=child)
    if not child.active:
        raise ValidationError(_('The profile is archived; existing observations remain available.'))
    return admin


@transaction.atomic
def save_rating(actor, administration, item_key, data, reason=''):
    admin = _lock_admin(actor, administration)
    item = next((i for i in admin.snapshot['items'] if i['id'] == item_key), None)
    if not item:
        raise ValidationError(_('The item is not part of this frozen protocol.'))
    values = {k: data.get(k, '' if k not in ['attempt_index', 'attempted_expected_word', 'target_identifiable'] else (1 if k == 'attempt_index' else False)) for k in RATING_FIELDS}
    validate_rating(values, item, admin.snapshot['goal']['accepted_variants'])
    rating = ProbeRating.objects.select_for_update().filter(administration=admin, item_key=item_key, occurrence_index=item['target_occurrence_index']).first()
    if rating:
        if rating.current_data() == values:
            return rating
        if not reason.strip():
            raise ValidationError(_('Explain a correction; the previous rating is retained.'))
        ProbeRatingRevision.objects.create(rating=rating, author=actor, reason=reason.strip(), data=values)
        audit(actor, 'followup.rating_corrected', rating, admin.organization)
    else:
        if admin.status != 'draft':
            raise ValidationError(_('A finalized observation cannot acquire new occurrences.'))
        rating = ProbeRating.objects.create(administration=admin, item_key=item_key, occurrence_index=item['target_occurrence_index'], author=actor, **values)
        audit(actor, 'followup.rating_recorded', rating, admin.organization)
    return rating


def _groups(admin):
    groups = {}
    item_map = {item['id']: item for item in admin.snapshot['items']}
    for rating in admin.ratings.prefetch_related('revisions'):
        data = rating.current_data()
        item = item_map[rating.item_key]
        key = (admin.snapshot['target'], admin.snapshot['variety'], item['exposure_at_start'], data['elicitation'], data['assistance'])
        group = groups.setdefault(key, {'target': key[0], 'variety': key[1], 'exposure': key[2], 'elicitation': key[3], 'assistance': key[4],
            'numerator': 0, 'denominator': 0, 'excluded': 0, 'not_presented': 0})
        if data['code'] in ['TARGET_ACCEPTABLE', 'VARIANT_ACCEPTABLE']:
            group['numerator'] += 1
        if data['code'] in ['TARGET_ACCEPTABLE', 'VARIANT_ACCEPTABLE', 'TARGET_INCORRECT']:
            group['denominator'] += 1
        if data['code'] == 'NOT_SCORABLE':
            group['excluded'] += 1
        if data['code'] == 'NOT_PRESENTED':
            group['not_presented'] += 1
    for group in groups.values():
        group['ratio'] = group['numerator'] / group['denominator'] if group['denominator'] else None
    return list(groups.values())


@transaction.atomic
def finalize_administration(actor, administration):
    admin = _lock_admin(actor, administration)
    if admin.status == 'finalized':
        return admin
    expected = {(item['id'], item['target_occurrence_index']) for item in admin.snapshot['items']}
    actual = set(admin.ratings.values_list('item_key', 'occurrence_index'))
    if expected != actual:
        raise ValidationError(_('Rate every planned occurrence, explicitly marking unpresented items.'))
    admin.summary_snapshot = _groups(admin)
    admin.status = 'finalized'
    admin.finalized_at = timezone.now()
    admin.finalized_by = actor
    admin.save()
    audit(actor, 'followup.observation_finalized', admin, admin.organization)
    return admin


@transaction.atomic
def share_summary(actor, administration, text):
    admin = _lock_admin(actor, administration)
    if admin.status != 'finalized':
        raise ValidationError(_('Review and finalize the observation before sharing a summary.'))
    admin.shared_text = text.strip()
    admin.shared_at = timezone.now() if admin.shared_text else None
    admin.shared_by = actor if admin.shared_text else None
    admin.save()
    audit(actor, 'followup.summary_shared' if admin.shared_text else 'followup.summary_revoked', admin, admin.organization)
    return admin


def professional_report(actor, administration):
    admin = professional_administrations(actor).filter(pk=administration.pk).first()
    if not admin:
        raise Http404
    ratings = []
    corrections = []
    for rating in admin.ratings.prefetch_related('revisions__author', 'author'):
        ratings.append({'id': str(rating.pk), 'item_key': rating.item_key, 'occurrence_index': rating.occurrence_index,
            'author': rating.author.username, 'created_at': rating.created_at.isoformat(), **rating.current_data()})
        for revision in sorted(rating.revisions.all(), key=lambda r: (r.created_at, str(r.pk))):
            corrections.append({'rating_id': str(rating.pk), 'reason': revision.reason, 'author': revision.author.username,
                'created_at': revision.created_at.isoformat(), 'data': revision.data})
    contamination = []
    for item in admin.snapshot['items']:
        if item['exposure_plan'] == 'reserved':
            events = ProbeExposure.objects.filter(child=admin.child, variety=admin.definition.variety,
                status='trained', occurred_at__gt=admin.started_at).order_by('occurred_at', 'pk')
            if admin.definition.variety.language == 'ar':
                key = reserve_word_key(item['word'], admin.definition.variety)
                future = next((event for event in events.iterator()
                    if reserve_word_key(event.normalized_word, admin.definition.variety) == key), None)
            else:
                future = events.filter(normalized_word=word_key(item['word'])).first()
            if future:
                contamination.append({'item_key': item['id'], 'word': item['word'], 'at': future.occurred_at.isoformat(),
                    'original_exposure': item['exposure_at_start']})
    previous = professional_administrations(actor).filter(goal=admin.goal, status='finalized', started_at__lt=admin.started_at).order_by('-started_at').first()
    comparable = bool(previous and admin.observation_scope == previous.observation_scope == 'goal'
        and admin.snapshot.get('target_scope') and previous.snapshot.get('target_scope')
        and _comparison_context(previous) == _comparison_context(admin))
    return {'administration': admin, 'goal': admin.goal, 'snapshot': copy.deepcopy(admin.snapshot), 'groups': _groups(admin),
        'ratings': ratings, 'corrections': corrections, 'contamination': contamination, 'original_groups': admin.summary_snapshot,
        'clinical_goal_snapshot': copy.deepcopy(admin.snapshot['goal']),
        'comparable': comparable, 'conditions': admin.conditions, 'familiarity': admin.familiarity}


def _comparison_context(admin):
    """A conservative procedural match; this never establishes psychometric equivalence."""
    supports = []
    for rating in admin.ratings.prefetch_related('revisions'):
        data = rating.current_data()
        supports.append((rating.item_key, rating.occurrence_index, data['elicitation'], data['assistance']))
    return {'digest': admin.snapshot['digest'], 'conditions': admin.conditions, 'familiarity': admin.familiarity,
        'goal': admin.snapshot['goal'], 'exposure': [(i['id'], i['exposure_at_start']) for i in admin.snapshot['items']],
        'supports': sorted(supports)}


def family_summary(actor, administration):
    admin = ProbeAdministration.objects.filter(pk=administration.pk, child__in=visible_children(actor), status='finalized').first()
    if not admin or not admin.shared_text:
        raise Http404
    return {'shared_text': admin.shared_text, 'shared_at': admin.shared_at, 'variety': admin.snapshot['variety'],
        'title': _('Professional observation summary'), 'is_demo': admin.snapshot['is_demo']}


def reserved_words_for(child, variety):
    words = set()
    for value in ClinicalGoal.objects.filter(child=child, variety=variety, active=True).values_list('reserved_words', flat=True):
        words.update(value)
    for snapshot in ProbeAdministration.objects.filter(child=child, definition__variety=variety).values_list('snapshot', flat=True):
        words.update(snapshot.get('reserved_words', []))
    return words


@transaction.atomic
def record_exposure(actor, child, variety, word, status, note, occurred_at=None):
    child = lock_clinical_child(actor, child)
    if not child.varieties.filter(pk=variety.pk).exists():
        raise ValidationError(_('The exposure variety must be recorded for this child.'))
    event = ProbeExposure.objects.create(child=child, variety=variety, word=word, status=status, note=note,
        occurred_at=occurred_at or timezone.now(), author=actor)
    audit(actor, 'followup.exposure_declared', event, child.organization)
    return event


def record_practice_exposure(actor, session):
    """Called within the already locked practice transaction; never speech accuracy."""
    child = session.item.program.child
    variety = session.item.program.variety
    if actor.pk != session.user_id or not visible_children(actor).filter(pk=child.pk).exists():
        raise PermissionDenied
    for word in [session.item.activity.word_a, session.item.activity.word_b]:
        ProbeExposure.objects.get_or_create(source_session=session, normalized_word=word_key(word), defaults={
            'child': child, 'variety': variety, 'word': word, 'status': 'trained' if session.completion == 'completed' else 'uncertain',
            'author': actor, 'occurred_at': session.created_at, 'note': 'Declared guided practice exposure; this does not rate vocal production.'})


@transaction.atomic
def create_coaching(actor, child, data):
    child = lock_clinical_child(actor, child)
    if not child.active:
        raise ValidationError(_('Archived profiles cannot acquire new coaching.'))
    coaching = ParentCoaching.objects.create(child=child, organization=child.organization, author=actor,
        **{k: data[k] for k in ['variety', 'instruction_language', 'instructions', 'example', 'accompanied_trial', 'understanding_checked', 'clinician_note', 'next_review'] if k in data})
    audit(actor, 'followup.coaching_created', coaching, child.organization)
    return coaching


def coaching_family_data(actor, coaching):
    if not visible_children(actor).filter(pk=coaching.child_id).exists():
        raise Http404
    return {'id': coaching.pk, 'child': coaching.child, 'variety': coaching.variety, 'instruction_language': coaching.instruction_language, 'instructions': coaching.instructions,
        'example': coaching.example, 'accompanied_trial': coaching.accompanied_trial,
        'understanding_checked': coaching.understanding_checked, 'next_review': coaching.next_review, 'created_at': coaching.created_at}


@transaction.atomic
def record_home_practice(actor, coaching, data, key=None):
    child = coaching.child
    Organization.objects.select_for_update().get(pk=child.organization_id)
    User.objects.select_for_update().get(pk=actor.pk)
    from care.models import Child
    child = Child.objects.select_for_update().get(pk=child.pk)
    if not child.active or not visible_children(actor).filter(pk=child.pk).exists():
        raise PermissionDenied
    coaching = ParentCoaching.objects.get(pk=coaching.pk, child=child)
    values = {k: data[k] for k in ['participation', 'support_used', 'difficulty', 'stop_reason', 'comment', 'occurred_at'] if k in data}
    key = uuid.UUID(str(key)) if key else uuid.uuid4()
    digest = _digest({'coaching': str(coaching.pk), **values})
    existing = HomePracticeFeedback.objects.filter(author=actor, idempotency_key=key).first()
    if existing:
        if existing.payload_digest != digest:
            raise ValidationError(_('This return key was already used with different observations.'))
        return existing
    obj = HomePracticeFeedback.objects.create(coaching=coaching, child=child, organization=child.organization,
        variety=coaching.variety, author=actor, idempotency_key=key, payload_digest=digest, **values)
    audit(actor, 'followup.home_practice_declared', obj, child.organization)
    return obj


def erase_child_followup(child):
    """Call only after the existing authorized retention decision and child lock."""
    ProbeAdministration.objects.filter(child=child).delete()
    ClinicalGoal.objects.filter(child=child).delete()
    ParentCoaching.objects.filter(child=child).delete()
    ProbeExposure.objects.filter(child=child).delete()


def retention_date(child):
    dates = []
    for model, field in [(ClinicalGoal, 'created_at'), (ProbeAdministration, 'started_at'), (ProbeAdministration, 'finalized_at'), (ProbeAdministration, 'shared_at'),
                         (ProbeRating, 'created_at'), (ProbeRatingRevision, 'created_at'), (ProbeExposure, 'created_at'),
                         (ParentCoaching, 'created_at'), (HomePracticeFeedback, 'created_at')]:
        query = model.objects
        if model == ProbeRating:
            query = query.filter(administration__child=child)
        elif model == ProbeRatingRevision:
            query = query.filter(rating__administration__child=child)
        else:
            query = query.filter(child=child)
        value = query.exclude(**{field + '__isnull': True}).order_by('-' + field).values_list(field, flat=True).first()
        if value:
            dates.append(value)
    # A revoked share clears shared_at; its append-only audit retains that date.
    # Explicit strings keep UUID matching consistent between SQLite and PostgreSQL.
    administration_ids = [str(pk) for pk in ProbeAdministration.objects.filter(child=child).values_list('pk', flat=True)]
    if administration_ids:
        latest_share_event = AuditEvent.objects.filter(organization_id=child.organization_id,
            object_id__in=administration_ids, action__in=['followup.summary_shared', 'followup.summary_revoked']).order_by('-created_at').values_list('created_at', flat=True).first()
        if latest_share_event:
            dates.append(latest_share_event)
    return max(dates) if dates else None
