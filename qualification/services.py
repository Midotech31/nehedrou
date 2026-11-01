"""Evidence gates are documentary checks, never automated clinical validation."""
import uuid
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.translation import gettext as _
from catalog.models import EditorialGrant, Variety
from catalog.services import allowed, require_review_snapshot
from core.services import audit
from .models import EvidenceDocument, ReviewerCompetence, ReviewerCompetenceDecision, AvailabilityDecision, LexicalPack, LexicalCandidate, FamiliarityStudy, PackReview

REQUIRED_EVIDENCE = ('clinical_content', 'rights', 'governance', 'pilot', 'operations')
COMPETENCE_DECLARATION_FIELDS = ('variety', 'discipline', 'professional_role', 'experience',
                                 'credential_reference', 'evidence', 'active')

def has_competence(user, variety, discipline):
    if not user.is_active:
        return False
    from catalog.integrity import request_value
    def load_competence():
        rows = list(ReviewerCompetence.objects.filter(user=user, variety=variety, discipline=discipline, active=True).select_related('evidence','current_decision__decided_by'))
        return rows[0] if rows else None
    competence = request_value('competences', (user.pk, variety.pk, discipline), load_competence)
    return bool(competence and competence.professional_role.strip() and competence.experience.strip() and competence.independently_verified)

@transaction.atomic
def save_competence_declaration(actor, data, competence_id=None):
    """Save the owner's declaration without writing a stale verification pointer."""
    if not actor.is_active:
        raise PermissionDenied
    if competence_id:
        competence = (ReviewerCompetence.objects.select_for_update()
            .filter(pk=competence_id, user=actor).first())
        if competence is None:
            raise PermissionDenied
    else:
        competence = ReviewerCompetence(user=actor)
    for field in COMPETENCE_DECLARATION_FIELDS:
        if field in data:
            setattr(competence, field, data[field])
    if not competence.variety_id or (not actor.is_superuser and not
            EditorialGrant.objects.filter(user=actor, variety_id=competence.variety_id).exists()):
        raise PermissionDenied
    if competence._state.adding:
        competence.save()
    else:
        competence.save(update_fields=[*COMPETENCE_DECLARATION_FIELDS, 'declared_at'])
    audit(actor, 'qualification.competence_declared', competence)
    return competence


@transaction.atomic
def record_competence_decision(actor, competence_id, status, basis, checked_on, *, expected_digest):
    competence = ReviewerCompetence.objects.select_for_update(of=('self',)).select_related('user', 'variety', 'evidence').get(pk=competence_id)
    if not allowed(actor, competence.variety, 'publish'):
        raise PermissionDenied
    current_digest = competence.fingerprint()
    if expected_digest != current_digest:
        raise ValidationError(
            _('This reviewer declaration changed. Reload this page and read the current declaration before recording a decision.'),
            code='competence_snapshot_changed')
    decision = ReviewerCompetenceDecision(
        competence=competence,
        snapshot_digest=current_digest,
        status=status,
        checked_on=checked_on,
        basis=basis,
        decided_by=actor,
    )
    decision.save()
    competence.current_decision = decision
    competence.save(update_fields=['current_decision'])
    audit(actor, 'qualification.competence_' + status, decision)
    return decision

def evidence_snapshot(documents):
    return {document.category: {'id': str(document.pk), 'sha256': document.sha256} for document in documents}

def decision_evidence_reasons(decision):
    reasons = []
    if not isinstance(decision.evidence, dict):
        return [_('Availability evidence must be a category-indexed document manifest.')]
    for category in REQUIRED_EVIDENCE:
        entry = decision.evidence.get(category, {})
        try:
            from catalog.integrity import evidence_document
            document = evidence_document(entry.get('id', '')) if isinstance(entry, dict) else None
        except (ValueError, AttributeError):
            document = None
        if not document or document.variety_id != decision.variety_id or document.category != category or entry.get('sha256') != document.sha256 or not document.usable:
            reasons.append(_('Missing or revoked availability evidence: %(category)s.') % {'category': category})
    return reasons

def availability_for(module, variety, version):
    from catalog.integrity import request_value
    decision = request_value('availability', (module, variety.pk, version), lambda: AvailabilityDecision.objects.filter(module=module, variety=variety, version=version).select_related('decided_by', 'variety').first())
    reasons = []
    if not decision or decision.status != 'available':
        reasons.append(_('No current authorised availability decision for this exact version.'))
    else:
        reasons.extend(decision_evidence_reasons(decision))
        if not allowed(decision.decided_by, decision.variety, 'publish') or not has_competence(decision.decided_by, decision.variety, 'clinical'):
            reasons.append(_('The availability decision owner no longer has the required authority or independently verified competence.'))
    return {'available': not reasons, 'reasons': reasons, 'decision': decision}

def pack_content_reasons(pack):
    from catalog.content_validation import validate_item_definition
    reasons = []
    candidates = list(pack.candidates.select_related('image', 'audio'))
    if not candidates:
        reasons.append(_('The regional pack has no lexical candidates.'))
    for candidate in candidates:
        try:
            validate_item_definition({'meaning': candidate.meaning, 'segments': candidate.segments, 'target_occurrences': candidate.occurrences, 'accepted_variants': candidate.accepted_variants}, required=True)
        except ValidationError:
            reasons.append(_('Incomplete phonetic definition: %(word)s.') % {'word': candidate.word})
        if not candidate.ipa.strip():
            reasons.append(_('Missing IPA transcription: %(word)s.') % {'word': candidate.word})
        for kind in ['image', 'audio']:
            asset = getattr(candidate, kind)
            if not asset or asset.kind != kind or not asset.documented or asset.rights_evidence.variety_id != pack.variety_id:
                reasons.append(_('Missing intact media and documented rights: %(word)s / %(kind)s.') % {'word': candidate.word, 'kind': kind})
        if candidate.audio:
            from catalog.audio_checks import audio_binding_errors
            reasons.extend(audio_binding_errors(candidate.audio, candidate.word, pack.variety))
        studies = list(candidate.familiarity.select_related('evidence'))
        if not studies or any(not study.evidence.usable for study in studies):
            reasons.append(_('Missing intact exploratory familiarity evidence: %(word)s.') % {'word': candidate.word})
    return reasons

def pack_readiness_reasons(pack):
    reasons = pack_content_reasons(pack)
    decisions = []
    for kind in ['clinical', 'linguistic']:
        review = pack.reviews.filter(kind=kind, content_digest=pack.fingerprint()).order_by('-created_at', '-pk').first()
        capability = 'clinical_review' if kind == 'clinical' else 'linguistic_review'
        if not review or not review.approved or not allowed(review.reviewer, pack.variety, capability) or not has_competence(review.reviewer, pack.variety, kind):
            reasons.append(_('Two current approvals by distinct reviewers with independently verified competence are required.'))
        else:
            decisions.append(review)
    if len(decisions) == 2 and decisions[0].reviewer_id == decisions[1].reviewer_id:
        reasons.append(_('Clinical and linguistic approval must come from two different people.'))
    return list(dict.fromkeys(reasons))


@transaction.atomic
def review_pack(actor, pack, kind, approved, note, *, expected_digest):
    pack = LexicalPack.objects.select_for_update().get(pk=pack.pk)
    from catalog.integrity import invalidate_integrity
    invalidate_integrity()
    if kind not in ['clinical', 'linguistic'] or not allowed(actor, pack.variety, kind + '_review'):
        raise PermissionDenied
    require_review_snapshot(pack, expected_digest)
    review = PackReview.objects.create(pack=pack, reviewer=actor, kind=kind, approved=approved, note=note)
    audit(actor, 'qualification.pack_reviewed', review)
    return review


@transaction.atomic
def change_pack_state(actor, pack_id, target):
    pack = LexicalPack.objects.select_for_update().get(pk=pack_id)
    from catalog.integrity import invalidate_integrity
    invalidate_integrity()
    capability = 'publish' if target in ['published', 'withdrawn'] else 'edit'
    if not allowed(actor, pack.variety, capability):
        raise PermissionDenied
    if target not in {'draft':['review'], 'review':['draft','published'], 'published':['withdrawn'], 'withdrawn':[]}[pack.state]:
        raise ValidationError(_('This editorial transition is not allowed.'))
    pack.state = target
    pack.save()
    audit(actor, 'qualification.pack_' + target, pack)
    return pack

@transaction.atomic
def clone_pack(actor, source):
    Variety.objects.select_for_update().get(pk=source.variety_id)
    source = LexicalPack.objects.select_for_update().get(pk=source.pk)
    if not allowed(actor, source.variety, 'edit'):
        raise PermissionDenied
    values = {f.attname:getattr(source,f.attname) for f in source._meta.concrete_fields if f.name not in ['id','version','state','created_by','created_at']}
    latest = LexicalPack.objects.filter(series=source.series).order_by('-version').first()
    result = LexicalPack.objects.create(**values, version=latest.version+1, state='draft', created_by=actor)
    for candidate in source.candidates.all():
        candidate_values = {f.attname:getattr(candidate,f.attname) for f in candidate._meta.concrete_fields if f.name not in ['id','pack']}
        copy = LexicalCandidate.objects.create(pack=result, **candidate_values)
        for study in candidate.familiarity.all():
            study_values = {f.attname:getattr(study,f.attname) for f in study._meta.concrete_fields if f.name not in ['id','candidate','created_at']}
            FamiliarityStudy.objects.create(candidate=copy, **study_values)
    audit(actor, 'qualification.pack_version', result)
    return result
