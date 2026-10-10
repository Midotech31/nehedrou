import uuid
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from core.models import CheckedModel, Membership
from catalog.models import Variety, Activity

class Child(CheckedModel):
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    organization = models.ForeignKey('core.Organization', on_delete=models.PROTECT)
    code = models.CharField(max_length=60, verbose_name=_('Pseudonym'))
    age_years = models.PositiveSmallIntegerField(verbose_name=_('Age in years'))
    responsible = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    varieties = models.ManyToManyField(Variety)
    active = models.BooleanField(default=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'code'], name='unique_child_code'), models.CheckConstraint(condition=models.Q(age_years__gte=4, age_years__lte=7), name='pilot_age_range')]
    def __str__(self):
        return self.code
    def clean(self):
        if self.responsible_id and not Membership.objects.filter(organization_id=self.organization_id, user_id=self.responsible_id, active=True).exists():
            raise ValidationError(_('The responsible clinician must be an active practice member.'))

class FamilyLink(CheckedModel):
    child = models.ForeignKey(Child, on_delete=models.CASCADE, related_name='family_links')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    active = models.BooleanField(default=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['child', 'user'], name='unique_family_link')]

class Program(CheckedModel):
    organization = models.ForeignKey('core.Organization', on_delete=models.PROTECT)
    child = models.ForeignKey(Child, on_delete=models.PROTECT, related_name='programs')
    variety = models.ForeignKey(Variety, on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    title = models.CharField(max_length=120, verbose_name=_('Program title'))
    goal = models.CharField(max_length=240, blank=True)
    guidance = models.TextField(blank=True, verbose_name=_('Personal instructions'))
    schedule = models.CharField(max_length=160, blank=True, verbose_name=_('Frequency and duration chosen by clinician'))
    state = models.CharField(max_length=12, default='active', choices=[('active', _('Active')), ('completed', _('Completed'))])
    created_at = models.DateTimeField(auto_now_add=True)
    def clean(self):
        if self.child_id and self.child.organization_id != self.organization_id:
            raise ValidationError(_('The child must belong to this practice.'))
        old = Program.objects.filter(pk=self.pk).first()
        if old and old.items.exists() and any(getattr(old, field) != getattr(self, field) for field in ['child_id', 'organization_id', 'variety_id']):
            raise ValidationError(_('Assigned program identity cannot be changed.'))
        if self.child_id and self.variety_id and not self.child.varieties.filter(pk=self.variety_id).exists():
            raise ValidationError(_('Select a spoken variety recorded for this child.'))
        if not old and self.created_by_id and not Membership.objects.filter(organization_id=self.organization_id, user_id=self.created_by_id, active=True).exists():
            raise ValidationError(_('An active practice member is required.'))

class ProgramItem(CheckedModel):
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='items')
    activity = models.ForeignKey(Activity, on_delete=models.PROTECT)
    position = models.PositiveIntegerField(default=1)
    class Meta:
        ordering = ['position']
        constraints = [models.UniqueConstraint(fields=['program', 'position'], name='unique_program_position')]
    def clean(self):
        if self.activity_id and self.program_id:
            old = ProgramItem.objects.filter(pk=self.pk).first()
            if old and any(getattr(old, field) != getattr(self, field) for field in ['program_id', 'activity_id', 'position']):
                raise ValidationError(_('Assigned activities cannot be changed. Create an adjusted program.'))
            if self.activity.variety_id != self.program.variety_id:
                raise ValidationError(_('The activity must match the program variety.'))
            if self.activity.state != 'published':
                raise ValidationError(_('Only published activities can be assigned.'))
            if self.activity.is_demo and not settings.DEMO_MODE:
                raise ValidationError(_('Demo content cannot be assigned outside demonstration mode.'))

class PracticeRun(CheckedModel):
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='practice_runs')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    state = models.CharField(max_length=12, default='active', choices=[('active', _('In progress')), ('completed', _('Completed')), ('stopped', _('Stopped'))])
    started_at = models.DateTimeField(default=timezone.now, editable=False)
    finished_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        ordering = ['-started_at']
        constraints = [models.UniqueConstraint(fields=['program', 'user'], condition=models.Q(state='active'), name='unique_active_practice_run')]
    def clean(self):
        old = PracticeRun.objects.filter(pk=self.pk).first()
        if old and (old.program_id != self.program_id or old.user_id != self.user_id or (old.state != 'active' and old.state != self.state)):
            raise ValidationError(_('A finished practice run cannot be reopened or reassigned.'))
        if (self.state == 'active') != (self.finished_at is None):
            raise ValidationError(_('The practice run state and finish date must agree.'))

class PracticeRunTask(CheckedModel):
    run = models.ForeignKey(PracticeRun, on_delete=models.CASCADE, related_name='tasks')
    item = models.ForeignKey(ProgramItem, on_delete=models.PROTECT)
    position = models.PositiveIntegerField()
    target = models.CharField(max_length=1, choices=[('a', 'A'), ('b', 'B')])
    nonce = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    class Meta:
        ordering = ['position']
        constraints = [models.UniqueConstraint(fields=['run', 'position'], name='unique_run_position'), models.UniqueConstraint(fields=['run', 'item'], name='unique_run_item')]
    def clean(self):
        if self.item_id and self.run_id and self.item.program_id != self.run.program_id:
            raise ValidationError(_('The activity must belong to this practice run.'))
        old = PracticeRunTask.objects.filter(pk=self.pk).first()
        if old and any(getattr(old, field) != getattr(self, field) for field in ['run_id', 'item_id', 'position', 'target', 'nonce']):
            raise ValidationError(_('Practice run steps cannot be changed.'))

class PracticeSession(CheckedModel):
    organization = models.ForeignKey('core.Organization', on_delete=models.PROTECT)
    item = models.ForeignKey(ProgramItem, on_delete=models.PROTECT, related_name='sessions')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    run_task = models.OneToOneField(PracticeRunTask, on_delete=models.SET_NULL, null=True, blank=True, related_name='report')
    reporter_role = models.CharField(max_length=12, default='caregiver', choices=[('caregiver', _('Caregiver')), ('clinician', _('Clinician'))])
    idempotency_key = models.UUIDField()
    payload_digest = models.CharField(max_length=64)
    answer = models.CharField(max_length=1, blank=True, choices=[('a', 'A'), ('b', 'B')])
    target = models.CharField(max_length=1, choices=[('a', 'A'), ('b', 'B')])
    correct = models.BooleanField(null=True, blank=True)
    completion = models.CharField(max_length=12, choices=[('completed', _('Completed')), ('stopped', _('Stopped'))])
    parent_report = models.CharField(max_length=20, choices=[('easy', _('Comfortable')), ('help', _('Needed help')), ('difficult', _('Difficult'))])
    support_used = models.CharField(max_length=20, blank=True, default='', choices=[('', _('Not recorded')), ('none', _('No support reported')), ('model', _('Clinician-taught word model')), ('gesture', _('Gesture')), ('instructions', _('Repeated instructions')), ('multiple', _('Several supports')), ('unsure', _('Unsure about the support'))])
    stop_reason = models.CharField(max_length=20, blank=True, default='', choices=[('', _('Not recorded')), ('fatigue', _('Fatigue')), ('upset', _('Upset')), ('understanding', _('Task not understood')), ('other', _('Another reason'))])
    comment = models.TextField(blank=True, max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'idempotency_key'], name='unique_practice_submission')]
        indexes = [models.Index(fields=['organization', 'created_at'])]
    def clean(self):
        if self.run_task_id and (self.run_task.item_id != self.item_id or self.run_task.run.user_id != self.user_id or self.run_task.run.program.organization_id != self.organization_id or self.run_task.target != self.target or self.run_task.nonce != self.idempotency_key):
            raise ValidationError(_('The report must match its practice run step.'))
        if self.item_id and self.item.program.organization_id != self.organization_id:
            raise ValidationError(_('The session must belong to the program practice.'))
        if self.completion == 'stopped' and (self.answer or self.correct is not None):
            raise ValidationError(_('Stopped attempts do not count as incorrect answers.'))
        if self.completion == 'completed' and not self.answer:
            raise ValidationError(_('Choose an answer or stop the activity.'))
        if self.stop_reason and self.completion != 'stopped':
            raise ValidationError(_('A stopping reason belongs to a stopped practice only.'))

class Observation(CheckedModel):
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='observations')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    text = models.TextField(max_length=2000, verbose_name=_('Professional observation'))
    created_at = models.DateTimeField(auto_now_add=True)
    def clean(self):
        if self.program_id and not Membership.objects.filter(user_id=self.author_id, organization=self.program.organization, active=True).exists():
            raise ValidationError(_('An active practice member is required.'))

class ProgramFeedback(CheckedModel):
    """Explicitly shared guidance; professional Observation remains private."""
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name='family_feedback')
    source_report = models.ForeignKey(PracticeSession, on_delete=models.SET_NULL, null=True, blank=True, related_name='clinician_feedback')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    text = models.TextField(max_length=2000, verbose_name=_('Feedback for the family'))
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    class Meta:
        ordering = ['-created_at', '-pk']
        indexes = [models.Index(fields=['program', 'created_at'])]
    def clean(self):
        if self.program_id and (self.program.child.responsible_id != self.author_id or not Membership.objects.filter(user_id=self.author_id, organization_id=self.program.organization_id, active=True).exists()):
            raise ValidationError(_('Only the responsible clinician can publish feedback for this family.'))
        if self.source_report_id and self.source_report.item.program_id != self.program_id:
            raise ValidationError(_('The report must belong to this program.'))
        old = ProgramFeedback.objects.filter(pk=self.pk).first()
        if old and any(getattr(old, field) != getattr(self, field) for field in ['program_id', 'source_report_id', 'author_id', 'text', 'created_at']):
            raise ValidationError(_('Published feedback cannot be changed. Publish a new clarification.'))
