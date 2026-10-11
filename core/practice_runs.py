"""Ordered, resumable participation records; no speech assessment or dosage."""
import secrets
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from care.models import Child, Program, ProgramItem, PracticeRun, PracticeRunTask
from catalog.models import Activity
from .access import visible_programs
from .models import Organization, User
from .services import audit


def lock_program(actor, reference):
    # Same order as clinical mutations; the practice lock serializes erasure/revocation.
    Organization.objects.select_for_update().get(pk=reference.organization_id)
    User.objects.select_for_update().get(pk=actor.pk)
    child = Child.objects.select_for_update().filter(pk=reference.child_id).first()
    program = Program.objects.select_for_update().filter(pk=reference.pk).first()
    if not child or not program or not visible_programs(actor).filter(pk=program.pk).exists():
        raise ValidationError(_('Access is no longer available.'))
    program.child = child
    return program


def task_ticket(task):
    return {'user': task.run.user_id, 'item': str(task.item_id), 'key': str(task.nonce), 'target': task.target,
            'run_task': str(task.pk), 'run': str(task.run_id), 'position': task.position}


def task_url(task):
    return reverse('practice', args=[task.item_id]) + '?task=' + str(task.pk)


@transaction.atomic
def start_run(actor, reference):
    program = lock_program(actor, reference)
    existing = PracticeRun.objects.select_for_update().filter(program=program, user=actor, state='active').first()
    if existing:
        return existing
    if not program.child.active or program.state != 'active':
        raise ValidationError(_('This activity is no longer available. Contact your clinician.'))
    items = list(program.items.order_by('position', 'pk'))
    activities = {a.pk: a for a in Activity.objects.select_for_update().filter(pk__in=[i.activity_id for i in items]).order_by('pk')}
    if not items or any(not activities[i.activity_id].usable for i in items):
        raise ValidationError(_('This activity is no longer available. Contact your clinician.'))
    from .reserves import reserved_activity_ids
    if reserved_activity_ids(program.child, activities.values()):
        raise ValidationError(_('This activity is no longer available. Contact your clinician.'))
    if any(not activities[i.activity_id].instructions.get(actor.instruction_language) for i in items):
        raise ValidationError(_('Choose another instruction language in your preferences or contact your clinician.'))
    # Assignment identity is immutable; these rows are the ordered snapshot.
    list(ProgramItem.objects.select_for_update().filter(pk__in=[i.pk for i in items]).order_by('pk'))
    run = PracticeRun.objects.create(program=program, user=actor)
    for position, item in enumerate(items, 1):
        activity = activities[item.activity_id]
        requested_target = activity.requested_target if activity.response_mode == 'matching' else ''
        PracticeRunTask.objects.create(run=run, item=item, position=position, target=requested_target or secrets.choice(['a', 'b']))
    audit(actor, 'practice_run.started', run, program.organization)
    return run


@transaction.atomic
def stop_run(actor, reference):
    program = lock_program(actor, reference.program)
    run = PracticeRun.objects.select_for_update().filter(pk=reference.pk, program=program, user=actor).first()
    if not run:
        raise ValidationError(_('Access is no longer available.'))
    if run.state == 'active':
        run.state = 'stopped'
        run.finished_at = timezone.now()
        run.save(update_fields=['state', 'finished_at'])
        audit(actor, 'practice_run.stopped', run, program.organization)
    return run


def run_summary(run, actor):
    tasks = list(run.tasks.select_related('item__activity', 'report').order_by('position'))
    pending = None
    reported = 0
    for task in tasks:
        report = getattr(task, 'report', None)
        task.saved_report = report
        if report:
            reported += 1
        elif pending is None:
            pending = task
    own = run.user_id == actor.pk
    blocked = None
    if run.state == 'active' and pending:
        from .reserves import activity_is_reserved
        if not run.program.child.active or run.program.state != 'active' or not pending.item.activity.usable or activity_is_reserved(run.program.child, pending.item.activity):
            blocked = _('This activity is no longer available. Contact your clinician.')
        elif not pending.item.activity.instructions.get(actor.instruction_language):
            blocked = _('Choose another instruction language in your preferences or contact your clinician.')
    return {'run': run, 'tasks': tasks, 'reported_count': reported, 'task_count': len(tasks),
            'pending': pending, 'resume_url': task_url(pending) if own and pending and run.state == 'active' and not blocked else None,
            'blocked_reason': blocked, 'own_run': own, 'progress_percent': round(reported / len(tasks) * 100) if tasks else 0}
