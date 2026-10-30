from django.utils.translation import gettext_lazy as _
"""Private descriptive production follow-up, separate from picture-choice practice."""
import hashlib
import json
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from core.models import CheckedModel, Membership
from .validation import CODES, ELICITATIONS, RIGHTS_STATUSES, validate_variants, validate_items, validate_conditions, validate_rating, validate_target_scope, target_match_errors, validate_observation_target

STATES = [('draft', _('Draft')), ('review', _('In review')), ('approved', _('Approved')), ('published', _('Published')), ('withdrawn', _('Withdrawn'))]


class ClinicalGoal(CheckedModel):
    organization = models.ForeignKey('core.Organization', on_delete=models.PROTECT)
    child = models.ForeignKey('care.Child', on_delete=models.PROTECT, related_name='clinical_goals')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    variety = models.ForeignKey('catalog.Variety', on_delete=models.PROTECT)
    target_phoneme = models.CharField(max_length=80)
    contrast = models.CharField(max_length=120, blank=True)
    target_position = models.CharField(max_length=160)
    target_scope = models.JSONField(default=dict, blank=True)
    context = models.TextField(blank=True, max_length=2000)
    rationale = models.TextField(max_length=2000)
    expected_realization = models.CharField(max_length=300)
    accepted_variants = models.JSONField(default=list, blank=True)
    functional_goal = models.TextField(max_length=2000)
    review_date = models.DateField(null=True, blank=True)
    external_assessment_status = models.CharField(max_length=20, default='not_recorded', choices=[('confirmed', _('Already assessed by the responsible professional')), ('pending', _('Pending')), ('not_recorded', _('Not recorded'))])
    external_assessment_note = models.TextField(blank=True, max_length=2000)
    active = models.BooleanField(default=True)
    probe_definition = models.ForeignKey('ProbeDefinition', on_delete=models.PROTECT, null=True, blank=True)
    reserved_words = models.JSONField(default=list, blank=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def clean(self):
        validate_variants(self.accepted_variants)
        validate_target_scope(self.target_scope)
        if self.target_scope and self.target_position.strip().lower() in ['initial', 'medial', 'final'] and self.target_scope['position'] != self.target_position.strip().lower():
            raise ValidationError(_('The structured position must agree with the target position.'))
        if self.child_id and self.child.organization_id != self.organization_id:
            raise ValidationError(_('The goal and child must belong to the same practice.'))
        if self.child_id and self.variety_id and not self.child.varieties.filter(pk=self.variety_id).exists():
            raise ValidationError(_('Use a spoken variety recorded for this child.'))
        old = ClinicalGoal.objects.filter(pk=self.pk).first()
        if not old and not self.target_scope:
            raise ValidationError(_('Document structured target position and context before real use.'))
        target_changed = not old or any(getattr(old, k) != getattr(self, k) for k in ['probe_definition_id', 'variety_id', 'target_phoneme', 'target_position', 'target_scope'])
        if self.probe_definition_id and target_changed:
            errors = target_match_errors(self, self.probe_definition)
            if errors:
                raise ValidationError(errors)
        if old and any(getattr(old, k) != getattr(self, k) for k in ['organization_id', 'child_id', 'author_id', 'variety_id']):
            raise ValidationError(_('A clinical goal cannot be reassigned.'))


class ProbeDefinition(CheckedModel):
    series = models.UUIDField(default=uuid.uuid4)
    version = models.PositiveIntegerField(default=1)
    variety = models.ForeignKey('catalog.Variety', on_delete=models.PROTECT)
    organization = models.ForeignKey('core.Organization', on_delete=models.PROTECT, null=True, blank=True)
    authored_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    title = models.CharField(max_length=160)
    protocol = models.TextField(max_length=6000)
    task = models.CharField(max_length=160)
    target_phoneme = models.CharField(max_length=80)
    target_position = models.CharField(max_length=160)
    target_scope = models.JSONField(default=dict, blank=True)
    items = models.JSONField(default=list)
    rights = models.TextField(blank=True, max_length=3000)
    rights_status = models.CharField(max_length=30, default='unknown', choices=[('unknown', _('Documentation missing')), ('original_documented', _('Original material with documented rights')), ('open_commercial_compatible', _('Documented compatible open licence')), ('permission_required', _('Permission required')), ('excluded', _('Excluded from use'))])
    evidence = models.JSONField(default=dict, blank=True)
    is_demo = models.BooleanField(default=True)
    state = models.CharField(max_length=12, default='draft', choices=STATES)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['series', 'version'], name='unique_probe_version')]
        indexes = [models.Index(fields=['variety', 'state'])]

    def __str__(self):
        return f'{self.title} · v{self.version}'

    def fingerprint(self):
        from .services import media_manifest
        data = {k: getattr(self, k) for k in ['series', 'version', 'variety_id', 'organization_id', 'title', 'protocol', 'task', 'target_phoneme', 'target_position', 'items', 'rights', 'rights_status', 'evidence', 'is_demo']}
        if self.target_scope:
            data['target_scope'] = self.target_scope
        data['media'] = media_manifest(self.items)
        return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

    @property
    def ready(self):
        from .services import readiness_reasons
        return not readiness_reasons(self)

    def clean(self):
        validate_items(self.items)
        validate_target_scope(self.target_scope)
        if self.target_scope and self.target_position.strip().lower() in ['initial', 'medial', 'final'] and self.target_scope['position'] != self.target_position.strip().lower():
            raise ValidationError(_('The structured position must agree with the target position.'))
        if not isinstance(self.evidence, dict):
            raise ValidationError(_('Protocol evidence must be an object.'))
        if ProbeDefinition.objects.filter(series=self.series).exclude(pk=self.pk).exclude(variety_id=self.variety_id).exists():
            raise ValidationError(_('A protocol series must retain its spoken variety.'))
        old = ProbeDefinition.objects.filter(pk=self.pk).first()
        fixed = ['series', 'version', 'variety_id', 'organization_id', 'authored_by_id', 'is_demo']
        if old and any(getattr(old, k) != getattr(self, k) for k in fixed):
            raise ValidationError(_('Protocol version identity cannot be changed.'))
        if old and (old.state in ['approved', 'published', 'withdrawn'] or old.administrations.exists() or old.clinicalgoal_set.exists()):
            for f in self._meta.concrete_fields:
                if f.name != 'state' and getattr(old, f.attname) != getattr(self, f.attname):
                    raise ValidationError(_('Create a new protocol version to change frozen content.'))
        if old and old.state in ['published', 'withdrawn'] and self.state not in [old.state, 'withdrawn']:
            raise ValidationError(_('A published protocol cannot return to draft.'))
        if self.state == 'published' and (not old or old.state != 'published'):
            from .services import readiness_reasons
            reasons = readiness_reasons(self)
            if reasons:
                raise ValidationError(reasons)


class ProbeReview(CheckedModel):
    definition = models.ForeignKey(ProbeDefinition, on_delete=models.CASCADE, related_name='reviews')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=[('clinical', _('Clinical review')), ('linguistic', _('Linguistic review'))])
    approved = models.BooleanField(default=False)
    note = models.TextField(max_length=2000)
    competence = models.TextField(max_length=2000)
    content_digest = models.CharField(max_length=64, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def clean(self):
        if ProbeReview.objects.filter(pk=self.pk).exists():
            raise ValidationError(_('Review decisions are append-only.'))
        if self.definition.state not in ['review', 'approved']:
            raise ValidationError(_('Review a submitted protocol version.'))
        if not self.competence.strip():
            raise ValidationError(_('Declare the scope of competence for this spoken variety.'))
        from catalog.services import allowed
        if not allowed(self.author, self.definition.variety, self.kind + '_review'):
            raise ValidationError(_('Review permission for this discipline and variety is required.'))
        if self.approved:
            from qualification.services import has_competence
            from .services import content_reasons
            if not has_competence(self.author, self.definition.variety, self.kind):
                raise ValidationError(_('A current competence declaration for this variety is required.'))
            reasons = content_reasons(self.definition)
            if reasons:
                raise ValidationError(reasons)

    def save(self, *args, **kwargs):
        self.content_digest = self.definition.fingerprint()
        return super().save(*args, **kwargs)


class ProbeAdministration(CheckedModel):
    organization = models.ForeignKey('core.Organization', on_delete=models.PROTECT)
    child = models.ForeignKey('care.Child', on_delete=models.PROTECT, related_name='probe_administrations')
    goal = models.ForeignKey(ClinicalGoal, on_delete=models.PROTECT, related_name='administrations')
    definition = models.ForeignKey(ProbeDefinition, on_delete=models.PROTECT, related_name='administrations')
    professional = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='probe_administrations')
    idempotency_key = models.UUIDField(default=uuid.uuid4)
    payload_digest = models.CharField(max_length=64)
    status = models.CharField(max_length=12, default='draft', choices=[('draft', _('Draft')), ('finalized', _('Finalized'))])
    observation_scope = models.CharField(max_length=20, default='legacy', choices=[('legacy', _('Legacy scope not recorded')), ('goal', _('Goal context')), ('alternate_context', _('Separate context observation'))])
    alternate_context_label = models.CharField(max_length=160, blank=True)
    alternate_context_reason = models.TextField(max_length=2000, blank=True)
    conditions = models.JSONField(default=dict)
    familiarity = models.JSONField(default=dict)
    snapshot = models.JSONField(default=dict)
    summary_snapshot = models.JSONField(default=list, blank=True)
    started_at = models.DateTimeField(default=timezone.now, editable=False)
    finalized_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='finalized_probes')
    shared_text = models.TextField(blank=True, max_length=3000)
    shared_at = models.DateTimeField(null=True, blank=True)
    shared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='shared_probe_summaries')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['professional', 'idempotency_key'], name='unique_probe_submission')]
        indexes = [models.Index(fields=['organization', 'started_at'])]

    def clean(self):
        validate_conditions(self.conditions)
        if self.goal_id and (self.goal.child_id != self.child_id or self.goal.organization_id != self.organization_id or self.goal.variety_id != self.definition.variety_id):
            raise ValidationError(_('The administration must match its goal, child, practice and variety.'))
        old = ProbeAdministration.objects.filter(pk=self.pk).first()
        if not old and self.goal_id and self.definition_id:
            validate_observation_target(self.goal, self.definition, self.observation_scope, self.alternate_context_label, self.alternate_context_reason)
        fixed = ['organization_id', 'child_id', 'goal_id', 'definition_id', 'professional_id', 'idempotency_key', 'payload_digest', 'conditions', 'familiarity', 'snapshot', 'started_at', 'observation_scope', 'alternate_context_label', 'alternate_context_reason']
        if old and any(getattr(old, k) != getattr(self, k) for k in fixed):
            raise ValidationError(_('Administration conditions and version snapshots are immutable.'))
        if (self.status == 'finalized') != (self.finalized_at is not None and self.finalized_by_id is not None):
            raise ValidationError(_('Finalization requires a professional and date.'))
        if old and old.status == 'finalized' and any(getattr(old, k) != getattr(self, k) for k in ['status', 'finalized_at', 'finalized_by_id', 'summary_snapshot']):
            raise ValidationError(_('Finalized observations cannot be rewritten.'))
        if self.shared_text and self.status != 'finalized':
            raise ValidationError(_('Only a finalized observation can be expressly shared.'))


class ProbeRating(CheckedModel):
    administration = models.ForeignKey(ProbeAdministration, on_delete=models.CASCADE, related_name='ratings')
    item_key = models.CharField(max_length=100)
    occurrence_index = models.PositiveSmallIntegerField()
    attempt_index = models.PositiveSmallIntegerField(default=1)
    elicitation = models.CharField(max_length=20, choices=[('naming', _('Picture naming')), ('semantic_cue', _('Semantic cue')), ('lexical_choice', _('Lexical choice')), ('imitation', _('Imitation'))])
    assistance = models.TextField(blank=True, max_length=2000)
    transcription = models.CharField(max_length=500, blank=True)
    code = models.CharField(max_length=24, choices=[('TARGET_ACCEPTABLE', _('Target acceptable')), ('VARIANT_ACCEPTABLE', _('Documented variant acceptable')), ('TARGET_INCORRECT', _('Target incorrect in an audible attempt')), ('NOT_SCORABLE', _('Not scorable')), ('NOT_PRESENTED', _('Not presented'))])
    variant_id = models.CharField(max_length=100, blank=True)
    exclusion_reason = models.TextField(blank=True, max_length=2000)
    error_type = models.CharField(max_length=20, blank=True, choices=[('substitution', _('Substitution')), ('omission', _('Audible target omission')), ('distortion', _('Distortion')), ('other', _('Other scorable error'))])
    attempted_expected_word = models.BooleanField(default=False)
    target_identifiable = models.BooleanField(default=False)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['administration', 'item_key', 'occurrence_index'], name='unique_probe_occurrence')]

    def clean(self):
        if ProbeRating.objects.filter(pk=self.pk).exists():
            raise ValidationError(_('Ratings are immutable; append a reasoned correction.'))
        if self.administration.status != 'draft':
            raise ValidationError(_('A finalized observation cannot acquire new occurrences.'))
        item = next((i for i in self.administration.snapshot.get('items', []) if i['id'] == self.item_key), None)
        if not item or self.occurrence_index != item['target_occurrence_index']:
            raise ValidationError(_('The occurrence must belong to the frozen protocol.'))
        validate_rating(self.data(), item, self.administration.snapshot['goal']['accepted_variants'])

    def data(self):
        return {k: getattr(self, k) for k in RATING_FIELDS}

    def current_data(self):
        revision = max(self.revisions.all(), key=lambda r: (r.created_at, str(r.pk)), default=None)
        return revision.data if revision else self.data()


RATING_FIELDS = ['attempt_index', 'elicitation', 'assistance', 'transcription', 'code', 'variant_id', 'exclusion_reason', 'error_type', 'attempted_expected_word', 'target_identifiable']


class ProbeRatingRevision(CheckedModel):
    rating = models.ForeignKey(ProbeRating, on_delete=models.CASCADE, related_name='revisions')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.TextField(max_length=2000)
    data = models.JSONField()
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def clean(self):
        if ProbeRatingRevision.objects.filter(pk=self.pk).exists():
            raise ValidationError(_('Corrections are append-only.'))
        if not self.reason.strip() or set(self.data) != set(RATING_FIELDS):
            raise ValidationError(_('A correction needs a reason and a complete human rating.'))
        admin = self.rating.administration
        item = next(i for i in admin.snapshot['items'] if i['id'] == self.rating.item_key)
        validate_rating(self.data, item, admin.snapshot['goal']['accepted_variants'])


class ProbeExposure(CheckedModel):
    child = models.ForeignKey('care.Child', on_delete=models.CASCADE, related_name='probe_exposures')
    variety = models.ForeignKey('catalog.Variety', on_delete=models.PROTECT)
    word = models.CharField(max_length=100)
    normalized_word = models.CharField(max_length=100, editable=False)
    status = models.CharField(max_length=12, choices=[('trained', _('Trained')), ('untrained', _('Untrained')), ('uncertain', _('Exposure uncertain'))])
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    source_session = models.ForeignKey('care.PracticeSession', on_delete=models.SET_NULL, null=True, blank=True)
    note = models.TextField(max_length=2000)
    occurred_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['source_session', 'normalized_word'], condition=models.Q(source_session__isnull=False), name='unique_practice_word_exposure')]
        indexes = [models.Index(fields=['child', 'variety', 'normalized_word', 'occurred_at'])]

    def save(self, *args, **kwargs):
        from .validation import word_key
        self.normalized_word = word_key(self.word)
        return super().save(*args, **kwargs)

    def clean(self):
        from .validation import word_key
        if ProbeExposure.objects.filter(pk=self.pk).exists():
            raise ValidationError(_('Exposure history is append-only.'))
        self.normalized_word = word_key(self.word)
        if self.source_session_id and self.source_session.item.program.child_id != self.child_id:
            raise ValidationError(_('The exposure must match its source child.'))
        if self.occurred_at > timezone.now():
            raise ValidationError(_('An exposure cannot occur in the future.'))


class ParentCoaching(CheckedModel):
    organization = models.ForeignKey('core.Organization', on_delete=models.PROTECT)
    child = models.ForeignKey('care.Child', on_delete=models.CASCADE, related_name='parent_coaching')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    variety = models.ForeignKey('catalog.Variety', on_delete=models.PROTECT)
    instruction_language = models.CharField(max_length=2, blank=True, default='', choices=[('fr', _('French')), ('en', _('English')), ('ar', _('Arabic'))])
    instructions = models.TextField(max_length=3000)
    example = models.TextField(blank=True, max_length=3000)
    accompanied_trial = models.TextField(blank=True, max_length=3000)
    understanding_checked = models.BooleanField(default=False)
    clinician_note = models.TextField(blank=True, max_length=2000)
    next_review = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def clean(self):
        if self._state.adding and self.instruction_language not in ['fr', 'en', 'ar']:
            raise ValidationError(_('Choose the caregiver instruction language explicitly.'))
        if self.child_id and self.child.organization_id != self.organization_id:
            raise ValidationError(_('Coaching must belong to the child practice.'))
        if self.child_id and self.variety_id and not self.child.varieties.filter(pk=self.variety_id).exists():
            raise ValidationError(_('Use a spoken variety recorded for this child.'))
        if ParentCoaching.objects.filter(pk=self.pk).exists():
            raise ValidationError(_('Publish a new coaching instruction to retain the previous version.'))


class HomePracticeFeedback(CheckedModel):
    coaching = models.ForeignKey(ParentCoaching, on_delete=models.CASCADE, related_name='home_feedback')
    organization = models.ForeignKey('core.Organization', on_delete=models.PROTECT)
    child = models.ForeignKey('care.Child', on_delete=models.CASCADE, related_name='home_practice_feedback')
    variety = models.ForeignKey('catalog.Variety', on_delete=models.PROTECT)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    participation = models.CharField(max_length=12, choices=[('completed', _('Completed')), ('partial', _('Partial')), ('stopped', _('Stopped'))])
    support_used = models.TextField(blank=True, max_length=1000)
    difficulty = models.CharField(max_length=12, choices=[('easy', _('Comfortable')), ('help', _('Needed support')), ('difficult', _('Difficult'))])
    stop_reason = models.TextField(blank=True, max_length=1000)
    comment = models.TextField(blank=True, max_length=2000)
    occurred_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    idempotency_key = models.UUIDField(default=uuid.uuid4)
    payload_digest = models.CharField(max_length=64)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['author', 'idempotency_key'], name='unique_home_practice_return')]

    def clean(self):
        if HomePracticeFeedback.objects.filter(pk=self.pk).exists():
            raise ValidationError(_('Home-practice declarations are append-only.'))
        if self.coaching_id and (self.coaching.child_id != self.child_id or self.coaching.organization_id != self.organization_id or self.coaching.variety_id != self.variety_id):
            raise ValidationError(_('The return must match its shared coaching instruction.'))
        if self.participation == 'stopped' and not self.stop_reason.strip():
            raise ValidationError(_('Explain a stopped practice so the professional can respond.'))
        if self.occurred_at > timezone.now():
            raise ValidationError(_('A practice declaration cannot be dated in the future.'))
