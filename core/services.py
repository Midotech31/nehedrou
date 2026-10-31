import hashlib
import json
from django.core.exceptions import ValidationError
from django.db import transaction
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _
from care.models import Child, Program, ProgramItem, PracticeSession, FamilyLink, PracticeRun, PracticeRunTask, ProgramFeedback
from .models import Organization, Entitlement, Invitation, AuditEvent, Membership

def _audit_purpose(action):
    if action.startswith(('privacy.', 'data.rights.')):
        return 'data_rights'
    if action.startswith('security.'):
        return 'account_security'
    if action.startswith(('catalog.', 'qualification.')):
        return 'content_review'
    if action.startswith(('entitlement.', 'invoice.')):
        return 'billing_admin'
    if action.startswith(('membership.', 'organization.', 'invitation.')):
        return 'practice_admin'
    if action.startswith(('child.', 'program.', 'practice.', 'practice_run.', 'observation.', 'family.', 'followup.')):
        return 'care_delivery'
    return ''


def audit(actor, action, obj, organization=None, *, purpose_code=None):
    """Append a purpose-coded event without copying clinical content into the log."""
    if organization is None:
        organization = getattr(obj, 'organization', None)
    actor_ref = str(actor.pk) if actor is not None and getattr(actor, 'pk', None) is not None else ''
    return AuditEvent.objects.create(
        actor=actor,
        actor_ref=actor_ref,
        action=action,
        purpose_code=purpose_code or _audit_purpose(action),
        object_id=str(obj.pk) if obj is not None and getattr(obj, 'pk', None) is not None else '',
        organization=organization,
    )


def log_child_access(actor, child, *, resource, purpose_code):
    """Log an authorized consultation by its actor, purpose, and pseudonymous subject ref."""
    if purpose_code not in {'care_delivery', 'family_practice', 'clinical_followup', 'data_portability'}:
        raise ValueError('Unsupported child-data access purpose.')
    if not child or not child.pk or not child.organization_id:
        raise ValueError('A persisted child record is required.')
    if actor is None or not getattr(actor, 'is_authenticated', False):
        return None
    return audit(actor, f'data.consult.{resource}', child, child.organization,
                 purpose_code=purpose_code)

def issue_and_deliver_invitation(actor, organization, child, email, kind='family', replacing=None):
    from smtplib import SMTPException
    from django.core.mail import send_mail
    from django.urls import reverse
    with transaction.atomic():
        org = Organization.objects.select_for_update().get(pk=organization.pk)
        if kind == 'family':
            from .access import professional_children
            child = Child.objects.select_for_update().get(pk=child.pk)
            if not child.active or not professional_children(actor).filter(pk=child.pk).exists():
                raise ValidationError(_('Access is no longer available.'))
        elif not Membership.objects.filter(user=actor, organization=org, active=True, role='owner').exists():
            raise ValidationError(_('Access is no longer available.'))
        if replacing:
            old = Invitation.objects.select_for_update().get(pk=replacing.pk, organization=org)
            if not old.available:
                raise ValidationError(_('This invitation is unavailable or belongs to another account.'))
            old.revoked = True
            old.save()
        invite, token = Invitation.issue(org, child, email, actor, kind=kind)
        audit(actor, 'invitation.created', invite, org)
    url = settings.PUBLIC_ORIGIN.rstrip('/') + reverse('invite', args=[token])
    try:
        sent = send_mail(_('Your Nehedrou invitation'), _('You have been invited to Nehedrou. Sign in or create an account to accept this invitation:') + '\n' + url, settings.DEFAULT_FROM_EMAIL, [invite.email])
        delivery = ('console' if settings.EMAIL_BACKEND.endswith('console.EmailBackend') else 'sent') if sent else 'failed'
    except (OSError, SMTPException):
        delivery = 'failed'
    with transaction.atomic():
        invite.delivery = delivery
        invite.save(update_fields=['delivery'])
        audit(actor, 'invitation.delivery_' + delivery, invite, org)
    return invite

@transaction.atomic
def resolve_privacy(actor, request_id, data):
    from .models import PrivacyRequest
    from .access import professional_children
    from care.models import Observation
    reference = PrivacyRequest.objects.get(pk=request_id)
    org = Organization.objects.select_for_update().get(pk=reference.organization_id)
    child = Child.objects.select_for_update().filter(pk=reference.child_id).first()
    obj = PrivacyRequest.objects.select_for_update().get(pk=request_id)
    professional = child and professional_children(actor).filter(pk=child.pk).exists()
    owner = Membership.objects.filter(user=actor, organization=org, active=True, role='owner').exists()
    if not (professional or owner):
        raise ValidationError(_('Access is no longer available.'))
    if obj.status != 'pending':
        raise ValidationError(_('This request has already been resolved.'))
    if data['decision'] == 'erase':
        if not professional:
            raise ValidationError(_('Access is no longer available.'))
        if data['confirmation'] != child.code:
            raise ValidationError(_('The pseudonym does not match.'))
        if org.retention_days is None:
            raise ValidationError(_('Configure the practice retention policy before processing erasure.'))
        from .complete_views import retention_anchor
        if retention_anchor(child) + timezone.timedelta(days=org.retention_days) > timezone.now():
            raise ValidationError(_('The configured retention period has not elapsed. Retain with a documented reason.'))
        audit(actor, 'child.erased', child, org)
        from followup.services import erase_child_followup
        erase_child_followup(child)
        ProgramFeedback.objects.filter(program__child=child).delete()
        PracticeSession.objects.filter(item__program__child=child).delete()
        PracticeRun.objects.filter(program__child=child).delete()
        Observation.objects.filter(program__child=child).delete()
        ProgramItem.objects.filter(program__child=child).delete()
        Program.objects.filter(child=child).delete()
        FamilyLink.objects.filter(child=child).delete()
        Invitation.objects.filter(child=child).delete()
        child.delete()
        obj.child = None
    obj.status = 'resolved'
    obj.decision_reason = data['reason']
    obj.resolved_at = timezone.now()
    obj.save()
    audit(actor, 'privacy.resolved', obj, org)

@transaction.atomic
def revoke_membership(actor, organization, membership_id):
    """Use the same practice lock as creation, transfer and clinical mutations."""
    org = Organization.objects.select_for_update().get(pk=organization.pk)
    if not Membership.objects.filter(user=actor, organization=org, active=True, role='owner').exists():
        raise ValidationError(_('Access is no longer available.'))
    target = Membership.objects.select_for_update().filter(pk=membership_id, organization=org).first()
    if not target:
        raise ValidationError(_('Access is no longer available.'))
    if target.user_id == actor.pk or target.role == 'owner':
        raise ValidationError(_('A practice manager cannot be removed here.'))
    # Archived dossiers still hold goals, history, programs and privacy requests.
    if Child.objects.filter(organization=org, responsible_id=target.user_id).exists():
        raise ValidationError(_('Transfer all assigned child profiles, including archived profiles, before revoking this practitioner. The responsible clinician must transfer each profile to an active practice member.'))
    if target.active:
        target.active = False
        target.save(update_fields=['active'])
        audit(actor, 'member.revoked', target, org)
    return target


@transaction.atomic
def transfer_child(actor, reference, recipient):
    from .models import ChildResponsibilityTransfer, User
    child = lock_clinical_child(actor, reference)
    # Recheck current account and membership after locking: form choices can become stale.
    recipient = User.objects.select_for_update().filter(pk=recipient.pk, is_active=True).first()
    if not recipient:
        raise ValidationError(_('The responsible clinician must be an active practice member.'))
    membership = Membership.objects.select_for_update().filter(
        organization_id=child.organization_id, user=recipient, active=True).first()
    if not membership:
        raise ValidationError(_('The responsible clinician must be an active practice member.'))
    if child.responsible_id == recipient.pk:
        raise ValidationError(_('Choose a different responsible clinician.'))
    previous = child.responsible_id
    child.responsible = recipient
    child.save(update_fields=['responsible'])
    ChildResponsibilityTransfer.objects.create(
        organization=child.organization, child=child, previous_clinician_id=previous,
        new_clinician=recipient, actor=actor)
    audit(actor, 'child.reassigned', child, child.organization)
    return child


def check_entitlement(organization, creating_child=False):
    # Call within a transaction after locking Organization: serializes quota checks.
    entitlement = Entitlement.objects.filter(organization=organization).first()
    if not entitlement or not entitlement.usable:
        raise ValidationError(_('Access has expired. Existing records and exports remain available.'))
    if creating_child and organization.child_set.filter(active=True).count() >= entitlement.child_quota:
        raise ValidationError(_('The active child quota has been reached.'))

def lock_clinical_child(actor, child):
    """All clinical mutations lock practice, then child, then dependent records."""
    Organization.objects.select_for_update().get(pk=child.organization_id)
    locked = Child.objects.select_for_update().filter(pk=child.pk).first()
    if not locked:
        raise ValidationError(_('Access is no longer available.'))
    from .access import professional_children
    if not professional_children(actor).filter(pk=locked.pk).exists():
        raise ValidationError(_('Access is no longer available.'))
    return locked

@transaction.atomic
def create_program(actor, child, data):
    org = Organization.objects.select_for_update().get(pk=child.organization_id)
    child = Child.objects.select_for_update().filter(pk=child.pk).first()
    if child is None:
        raise ValidationError(_('Access is no longer available.'))
    from .access import professional_children
    from catalog.models import Activity
    if not professional_children(actor).filter(pk=child.pk).exists():
        raise ValidationError(_('Access is no longer available.'))
    if not child.active:
        raise ValidationError(_('This profile is archived. Existing records remain accessible.'))
    check_entitlement(org)
    selected = list(data['activities'])
    from catalog.content_catalog import current_catalog
    locked = {a.pk: a for a in current_catalog(Activity.objects.select_for_update().filter(pk__in=[a.pk for a in selected])).order_by('pk')}
    if not selected or len(locked) != len(selected) or not child.varieties.filter(pk=data['variety'].pk).exists():
        raise ValidationError(_('All activities must match the selected variety.'))
    activities = [locked[a.pk] for a in selected]
    if any(not a.usable or a.variety_id != data['variety'].pk for a in activities):
        raise ValidationError(_('This activity is no longer available. Contact your clinician.'))
    from .reserves import reserved_activity_ids
    if reserved_activity_ids(child, activities):
        raise ValidationError(_('Reserve items belong to professional follow-up and cannot be assigned to family games.'))
    if not settings.DEMO_MODE:
        from qualification.services import availability_for
        for activity in activities:
            decision = availability_for('practice', activity.variety, activity.fingerprint())
            if not decision['available']:
                raise ValidationError(decision['reasons'])
    program = Program.objects.create(organization=org, child=child, variety=data['variety'], created_by=actor, title=data['title'], goal=data.get('goal', ''), guidance=data['guidance'], schedule=data['schedule'], **{field: data.get(field, [] if field == 'practice_days' else None) for field in ['practice_start', 'practice_end', 'practice_days', 'practice_minutes']})
    for index, activity in enumerate(activities, 1):
        ProgramItem.objects.create(program=program, activity=activity, position=index)
    audit(actor, 'program.created', program, org)
    return program

@transaction.atomic
def publish_feedback(actor, reference, text, source_report=None):
    child = lock_clinical_child(actor, reference.child)
    program = Program.objects.select_for_update().filter(pk=reference.pk, child=child).first()
    if not program or not child.active or program.state != 'active':
        raise ValidationError(_('This activity is no longer available. Contact your clinician.'))
    if source_report:
        source_report = PracticeSession.objects.select_for_update().filter(pk=source_report.pk, item__program=program).first()
        if not source_report:
            raise ValidationError(_('The report must belong to this program.'))
    feedback = ProgramFeedback.objects.create(program=program, author=actor, text=text.strip(), source_report=source_report)
    audit(actor, 'family_feedback.published', feedback, program.organization)
    return feedback

@transaction.atomic
def accept_invitation(actor, token):
    ref = Invitation.objects.filter(token_hash=hashlib.sha256(token.encode()).hexdigest()).first()
    if not ref:
        raise ValidationError(_('This invitation is unavailable or belongs to another account.'))
    Organization.objects.select_for_update().get(pk=ref.organization_id)
    invite = Invitation.objects.select_for_update().filter(token_hash=hashlib.sha256(token.encode()).hexdigest()).first()
    if not invite or not invite.available or actor.email.lower() != invite.email.lower():
        raise ValidationError(_('This invitation is unavailable or belongs to another account.'))
    if invite.kind == 'clinician':
        org = Organization.objects.select_for_update().get(pk=invite.organization_id)
        check_entitlement(org)
        member = Membership.objects.filter(organization=org, user=actor).first()
        if not member or not member.active:
            if Membership.objects.filter(organization=org, active=True).count() >= org.entitlement.practitioner_quota:
                raise ValidationError(_('The practitioner quota has been reached.'))
            if member:
                member.active = True
                member.save()
            else:
                Membership.objects.create(organization=org, user=actor, role='clinician')
    else:
        link, _created = FamilyLink.objects.get_or_create(child=invite.child, user=actor)
        if not link.active:
            link.active = True
            link.save()
    invite.used_at = timezone.now()
    invite.save()
    audit(actor, 'invitation.accepted', invite, invite.organization)
    return invite.child

@transaction.atomic
def record_practice(actor, item, payload, ticket):
    # Serialize same-user submissions for idempotency, including requests racing on PostgreSQL.
    from .models import User
    Organization.objects.select_for_update().get(pk=item.program.organization_id)
    User.objects.select_for_update().get(pk=actor.pk)
    from .access import visible_programs
    if not Child.objects.select_for_update().filter(pk=item.program.child_id).first():
        raise ValidationError(_('Access is no longer available.'))
    if not Program.objects.select_for_update().filter(pk=item.program_id).first():
        raise ValidationError(_('Access is no longer available.'))
    from catalog.models import Activity
    Activity.objects.select_for_update().get(pk=item.activity_id)
    item = ProgramItem.objects.select_for_update(of=('self',)).select_related('activity', 'program__child').filter(pk=item.pk).first()
    if item is None:
        raise ValidationError(_('Access is no longer available.'))
    if not visible_programs(actor).filter(pk=item.program_id).exists():
        raise ValidationError(_('Access is no longer available.'))
    body = {k: payload.get(k, '') for k in ['answer', 'completion', 'parent_report', 'comment']}
    response_mode = item.activity.response_mode
    if response_mode != 'matching':
        body['response_mode'] = response_mode
    if response_mode == 'observation' or body['completion'] == 'stopped':
        body['answer'] = ''
    # Empty new declarations preserve digests of historical submissions.
    body.update({k: payload[k] for k in ['support_used', 'stop_reason'] if payload.get(k)})
    body.update(item=str(item.pk), target=ticket['target'])
    task = None
    run = None
    if ticket.get('run_task'):
        run = PracticeRun.objects.select_for_update().filter(pk=ticket.get('run'), program_id=item.program_id, user=actor).first()
        task = PracticeRunTask.objects.select_for_update().filter(pk=ticket['run_task'], run=run, item=item).first() if run else None
        if not task or str(task.nonce) != str(ticket['key']) or task.target != ticket['target'] or task.position != ticket.get('position'):
            raise ValidationError(_('The activity link has expired. Reload the page.'))
        body['run_task'] = str(task.pk)
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    existing = PracticeSession.objects.filter(user=actor, idempotency_key=ticket['key']).first()
    if existing:
        if existing.payload_digest != digest:
            raise ValidationError(_('This submission key was already used with different answers.'))
        return existing
    if response_mode == 'matching' and item.activity.requested_target and ticket['target'] != item.activity.requested_target:
        raise ValidationError(_('The requested picture must match this activity’s instruction.'))
    if not item.program.child.active or item.program.state != 'active' or not item.activity.usable:
        raise ValidationError(_('This activity is no longer available. Contact your clinician.'))
    from .reserves import activity_is_reserved
    if activity_is_reserved(item.program.child, item.activity):
        raise ValidationError(_('Reserve items belong to professional follow-up and cannot be assigned to family games.'))
    if run:
        pending = run.tasks.filter(report__isnull=True).order_by('position').first()
        if run.state != 'active' or not pending or pending.pk != task.pk:
            raise ValidationError(_('Resume the current activity from your practice run.'))
        if not item.activity.instructions.get(actor.instruction_language):
            raise ValidationError(_('Choose another instruction language in your preferences or contact your clinician.'))
    reporter_role = 'caregiver' if FamilyLink.objects.filter(child=item.program.child, user=actor, active=True).exists() else 'clinician'
    session = PracticeSession.objects.create(organization=item.program.organization, item=item, user=actor, run_task=task, reporter_role=reporter_role, idempotency_key=ticket['key'], payload_digest=digest, answer=body['answer'], target=ticket['target'], response_mode=response_mode, completion=body['completion'], correct=(body['answer'] == ticket['target']) if body['completion'] == 'completed' and response_mode == 'matching' else None, parent_report=body['parent_report'], comment=body['comment'], support_used=body.get('support_used', ''), stop_reason=body.get('stop_reason', ''))
    from followup.services import record_practice_exposure
    record_practice_exposure(actor, session)
    if run and (body['completion'] == 'stopped' or not run.tasks.filter(report__isnull=True).exists()):
        run.state = 'stopped' if body['completion'] == 'stopped' else 'completed'
        run.finished_at = timezone.now()
        run.save(update_fields=['state', 'finished_at'])
        audit(actor, 'practice_run.' + run.state, run, item.program.organization)
    audit(actor, 'practice.recorded', session, item.program.organization)
    return session
