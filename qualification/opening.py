"""Human opening decisions anchored to actual scoped content, never inferred approvals."""
from copy import deepcopy
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils.translation import gettext as _
from catalog.models import Activity, EditorialGrant
from core.models import Organization, Membership
from core.services import audit
from .models import AvailabilityDecision, EvidenceDocument, MODULES
from .services import evidence_snapshot, REQUIRED_EVIDENCE


class ContentChanged(ValidationError):
    pass


def target_queryset(actor, module, *, publish=True):
    from followup.models import ProbeDefinition
    from followup.services import definition_queryset
    model = Activity if module == 'practice' else ProbeDefinition
    if module not in dict(MODULES) or not actor.is_authenticated or not actor.is_active:
        return model.objects.none()
    grants = EditorialGrant.objects.filter(user=actor)
    if publish:
        grants = grants.filter(publish=True)
    if module == 'practice':
        queryset = Activity.objects.all()
    else:
        # Keep permission joins in a subquery: DISTINCT cannot be row-locked on PostgreSQL.
        queryset = ProbeDefinition.objects.filter(pk__in=definition_queryset(actor).values('pk'))
        if not actor.is_superuser:
            organizations = Membership.objects.filter(user=actor, active=True).values('organization_id')
            queryset = queryset.filter(Q(organization__isnull=True) | Q(organization_id__in=organizations))
    queryset = queryset.filter(is_demo=False)
    if not actor.is_superuser:
        queryset = queryset.filter(variety_id__in=grants.values('variety_id'))
    return queryset


def decision_queryset(actor, *, publish=False):
    if not actor.is_authenticated or not actor.is_active:
        return AvailabilityDecision.objects.none()
    if actor.is_superuser:
        return AvailabilityDecision.objects.all()
    grants = EditorialGrant.objects.filter(user=actor)
    if publish:
        grants = grants.filter(publish=True)
    organizations = [str(pk) for pk in Membership.objects.filter(user=actor, active=True).values_list('organization_id', flat=True)]
    public = Q(target_snapshot__organization=None, target_snapshot__id__isnull=False)
    private = Q(target_snapshot__organization__in=organizations)
    legacy = Q(target_snapshot={}, decided_by=actor)
    return AvailabilityDecision.objects.filter(variety_id__in=grants.values('variety_id')).filter(public | private | legacy)


def target_key(module, target):
    return module + ':' + str(target.pk)


def target_snapshot(module, target):
    return {'module': module, 'id': str(target.pk), 'series': str(target.series),
        'version': target.version, 'title': target.title, 'variety': str(target.variety_id),
        'organization': str(target.organization_id) if module == 'production_followup' and target.organization_id else None}


def target_label(module, target):
    return '%s · %s · %s · v%s · %s' % (dict(MODULES)[module], target.variety.display_label,
        target.title, target.version, target.get_state_display())


def resolve_target(actor, key, *, lock=False):
    try:
        module, reference = key.split(':', 1)
        queryset = target_queryset(actor, module)
        target = queryset.select_related('variety').get(pk=reference)
        if lock:
            if module == 'production_followup' and target.organization_id:
                Organization.objects.select_for_update().get(pk=target.organization_id)
            target = queryset.select_for_update(of=('self',)).select_related('variety').get(pk=reference)
    except (ValueError, TypeError, AttributeError, ObjectDoesNotExist, ValidationError):
        raise PermissionDenied from None
    return module, target


def validate_decision_target(decision):
    """New decisions need a real target; legacy records are never backfilled."""
    if decision.status == 'revoked':
        previous = decision_queryset(decision.decided_by, publish=True).filter(module=decision.module, variety_id=decision.variety_id,
            version=decision.version, target_snapshot=decision.target_snapshot).exists()
        if not previous:
            raise ValidationError(_('Revoke an existing decision without changing its historical target.'))
        return
    snapshot = decision.target_snapshot
    if not isinstance(snapshot, dict) or not snapshot.get('id'):
        raise ValidationError(_('Choose an existing real activity or protocol for this decision.'))
    try:
        module, target = resolve_target(decision.decided_by, decision.module + ':' + str(snapshot['id']))
    except PermissionDenied:
        raise ValidationError(_('The decision target is no longer accessible.')) from None
    if target.variety_id != decision.variety_id or snapshot != target_snapshot(module, target):
        raise ValidationError(_('The decision must retain the selected module, variety and content version.'))
    if target.fingerprint() != decision.version:
        raise ContentChanged(_('The content changed. Review the current version before recording a decision.'))
    if decision.status == 'available' and target.state == 'withdrawn':
        raise ValidationError(_('Withdrawn content cannot receive a new opening decision.'))


@transaction.atomic
def record_decision(actor, key, expected_version, data):
    module, target = resolve_target(actor, key, lock=True)
    from catalog.integrity import invalidate_integrity
    invalidate_integrity()
    digest = target.fingerprint()
    if digest != expected_version:
        raise ContentChanged(_('The content changed. Review the current version before recording a decision.'))
    documents = list(EvidenceDocument.objects.filter(pk__in=[doc.pk for doc in data['documents']]))
    if any(doc.variety_id != target.variety_id or doc.revoked for doc in documents):
        raise ValidationError(_('Use supporting documents for the selected spoken variety.'))
    if data['status'] == 'available' and (len(documents) != len(REQUIRED_EVIDENCE)
            or {doc.category for doc in documents} != set(REQUIRED_EVIDENCE)):
        raise ValidationError(_('Select one document for each required availability category.'))
    decision = AvailabilityDecision.objects.create(module=module, variety=target.variety,
        version=digest, status=data['status'], scope=data['scope'], reason=data['reason'],
        decided_by=actor, evidence=evidence_snapshot(documents), target_snapshot=target_snapshot(module, target))
    audit(actor, 'qualification.availability_' + decision.status, decision,
        target.organization if module == 'production_followup' else None)
    return decision


def _lock_recorded_target(decision):
    """Serialise revocation with writes using this exact activity/protocol row.

    Historical decisions without a surviving target remain revocable. They do
    not acquire a target row lock, and no target or approval is manufactured.
    """
    from followup.models import ProbeDefinition
    snapshot = decision.target_snapshot
    if not isinstance(snapshot, dict) or not snapshot.get('id'):
        return
    model = Activity if decision.module == 'practice' else ProbeDefinition
    try:
        target = model.objects.filter(pk=snapshot['id'], variety_id=decision.variety_id).first()
    except (ValueError, TypeError, ValidationError):
        return
    if target is None:
        return
    if decision.module == 'production_followup' and target.organization_id:
        Organization.objects.select_for_update().get(pk=target.organization_id)
    model.objects.select_for_update().get(pk=target.pk)


@transaction.atomic
def revoke_decision(actor, reference, reason):
    from catalog.services import allowed
    try:
        previous = decision_queryset(actor, publish=True).select_related('variety').get(pk=reference)
        _lock_recorded_target(previous)
        previous = decision_queryset(actor, publish=True).select_for_update(of=('self',)).select_related('variety').get(pk=reference)
    except AvailabilityDecision.DoesNotExist:
        raise PermissionDenied from None
    from catalog.integrity import invalidate_integrity
    invalidate_integrity()
    if not allowed(actor, previous.variety, 'publish') or not actor.is_active:
        raise PermissionDenied
    if not reason.strip():
        raise ValidationError(_('A revocation reason is required.'))
    decision = AvailabilityDecision.objects.create(module=previous.module, variety=previous.variety,
        version=previous.version, status='revoked', scope=previous.scope, reason=reason.strip(),
        decided_by=actor, evidence=deepcopy(previous.evidence), target_snapshot=deepcopy(previous.target_snapshot))
    audit(actor, 'qualification.availability_revoked', decision)
    return decision


def decision_target_display(actor, decision):
    snapshot = decision.target_snapshot
    if not isinstance(snapshot, dict) or not snapshot.get('id'):
        return {'label': _('Historical content target unavailable'), 'url': '', 'current': False}
    module = snapshot.get('module')
    try:
        target = target_queryset(actor, module, publish=False).get(pk=snapshot['id'])
    except (ValueError, TypeError, ObjectDoesNotExist, ValidationError):
        return {'label': _('Historical content target unavailable'), 'url': '', 'current': False}
    url = reverse('editorial_detail' if module == 'practice' else 'followup:definition_detail', args=[target.pk])
    label = '%s · v%s' % (snapshot.get('title', ''), snapshot.get('version', ''))
    return {'label': label, 'url': url, 'current': target.fingerprint() == decision.version}
