"""Human declarations and exact-version evidence. No record is a clinical certification."""
import hashlib
import json
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _
from core.models import CheckedModel
from core.storage_health import file_exists, STORAGE_ERRORS
from .validity import VALIDITY_CHOICES

DISCIPLINES = [('clinical', _('Clinical')), ('linguistic', _('Linguistic'))]
MODULES = [('practice', _('Guided family practice')), ('production_followup', _('Descriptive production follow-up'))]
RIGHTS_STATES = [('original_documented', _('Documented original rights')), ('open_commercial_compatible', _('Compatible commercial licence')), ('permission_required', _('Permission required')), ('unknown', _('Unknown')), ('excluded', _('Excluded'))]

def digest_value(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()

def digest_file(file):
    from catalog.integrity import request_value
    return request_value('file_digests', (id(file.storage), file.name), lambda: _digest_file(file))

def _digest_file(file):
    if not file_exists(file):
        return ''
    result = hashlib.sha256()
    count = 0
    try:
        with file.storage.open(file.name, 'rb') as stream:
            for chunk in iter(lambda: stream.read(65536), b''):
                count += len(chunk)
                if count > 15 * 1024 * 1024:
                    return ''
                result.update(chunk)
    except STORAGE_ERRORS:
        return ''
    return result.hexdigest()

class EvidenceDocument(CheckedModel):
    variety = models.ForeignKey('catalog.Variety', on_delete=models.PROTECT)
    title = models.CharField(max_length=180, verbose_name=_('Evidence title'))
    category = models.CharField(max_length=20, choices=[('rights', _('Usage rights')), ('familiarity', _('Word and image familiarity')), ('clinical_content', _('Clinical content review')), ('linguistic', _('Linguistic')), ('governance', _('Authorised purpose and data governance')), ('pilot', _('Supervised usability and procedure pilot')), ('operations', _('Storage, support and restoration'))])
    file = models.FileField(upload_to='private_evidence/%Y/%m/')
    sha256 = models.CharField(max_length=64, editable=False)
    source_url = models.URLField(blank=True, verbose_name=_('Source URL'))
    provenance = models.TextField(verbose_name=_('Author, date and document scope'))
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    # Unknown on legacy rows: no contract dates or permissions are fabricated.
    validity = models.CharField(max_length=12, default='unknown', choices=VALIDITY_CHOICES, verbose_name=_('Evidence validity'))
    valid_from = models.DateField(null=True, blank=True, verbose_name=_('Valid from (inclusive)'))
    valid_until = models.DateField(null=True, blank=True, verbose_name=_('Valid until (inclusive)'))
    revoked = models.BooleanField(default=False)
    revocation_reason = models.TextField(blank=True)

    def __str__(self):
        return self.title

    @property
    def intact(self):
        return not self.revoked and bool(self.sha256) and digest_file(self.file) == self.sha256

    @property
    def usable(self):
        from .validity import currently_valid
        return currently_valid(self.validity, self.valid_from, self.valid_until, self.revoked) and self.intact

    def clean(self):
        from .validity import validate_validity
        validate_validity(self.validity, self.valid_from, self.valid_until)
        old = EvidenceDocument.objects.filter(pk=self.pk).first()
        if old:
            for field in self._meta.concrete_fields:
                if field.name not in ['revoked', 'revocation_reason'] and getattr(self, field.attname) != getattr(old, field.attname):
                    raise ValidationError(_('Evidence is immutable. Upload a new document.'))
            if not self.file._committed or (old.revoked and not self.revoked):
                raise ValidationError(_('Evidence cannot be replaced or silently reinstated.'))
        if self.revoked and not self.revocation_reason.strip():
            raise ValidationError(_('A revocation reason is required.'))

    def save(self, *args, **kwargs):
        if self._state.adding and self.file:
            if self.file.size > 15 * 1024 * 1024:
                raise ValidationError(_('The file must be smaller than 15 MB.'))
            self.file.seek(0)
            self.sha256 = hashlib.sha256(self.file.read(15 * 1024 * 1024 + 1)).hexdigest()
            self.file.seek(0)
        return super().save(*args, **kwargs)

class ReviewerCompetence(CheckedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    variety = models.ForeignKey('catalog.Variety', on_delete=models.PROTECT)
    discipline = models.CharField(max_length=12, choices=DISCIPLINES)
    professional_role = models.CharField(max_length=160, verbose_name=_('Declared professional role'))
    experience = models.TextField(verbose_name=_('Experience in this spoken variety'))
    credential_reference = models.CharField(max_length=180, blank=True, verbose_name=_('Professional reference, if applicable'))
    evidence = models.ForeignKey(EvidenceDocument, on_delete=models.PROTECT, null=True, blank=True)
    declared_at = models.DateTimeField(auto_now=True)
    active = models.BooleanField(default=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'variety', 'discipline'], name='unique_reviewer_competence')]

    def clean(self):
        if self.evidence_id and self.evidence.variety_id != self.variety_id:
            raise ValidationError(_('Evidence must concern the same spoken variety.'))

class AvailabilityDecision(CheckedModel):
    module = models.CharField(max_length=24, choices=MODULES)
    variety = models.ForeignKey('catalog.Variety', on_delete=models.PROTECT)
    version = models.CharField(max_length=64, verbose_name=_('Exact content SHA-256'))
    status = models.CharField(max_length=12, choices=[('available', _('Available within the documented scope')), ('blocked', _('Pending requirements')), ('revoked', _('Revoked'))])
    scope = models.TextField(verbose_name=_('Authorised purpose, countries and limits'))
    reason = models.TextField(verbose_name=_('Decision and justification'))
    evidence = models.JSONField(default=dict, blank=True)
    target_snapshot = models.JSONField(default=dict, blank=True, editable=False)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at', '-pk']
        indexes = [models.Index(fields=['module', 'variety', 'version'])]

    def clean(self):
        from .services import decision_evidence_reasons, has_competence
        from catalog.services import allowed
        if AvailabilityDecision.objects.filter(pk=self.pk).exists():
            raise ValidationError(_('Decisions are immutable. Record a new decision or revocation.'))
        if len(self.version) != 64 or any(c not in '0123456789abcdef' for c in self.version):
            raise ValidationError(_('Use the SHA-256 of the exact reviewed content.'))
        if not allowed(self.decided_by, self.variety, 'publish'):
            raise ValidationError(_('Publishing permission for this variety is required.'))
        from .opening import validate_decision_target
        validate_decision_target(self)
        if self.status == 'available':
            if not has_competence(self.decided_by, self.variety, 'clinical'):
                raise ValidationError(_('Availability requires publishing permission and declared clinical competence.'))
            reasons = decision_evidence_reasons(self)
            if reasons:
                raise ValidationError(reasons)

class LexicalPack(CheckedModel):
    variety = models.ForeignKey('catalog.Variety', on_delete=models.PROTECT)
    title = models.CharField(max_length=180, verbose_name=_('Regional pack title'))
    series = models.UUIDField()
    version = models.PositiveIntegerField(default=1)
    region = models.CharField(max_length=180, verbose_name=_('Region and speaker community'))
    scope = models.TextField(verbose_name=_('Spoken variety and scope'))
    population = models.TextField(verbose_name=_('Intended population'))
    indications = models.TextField(verbose_name=_('Assessed profiles and proposed contrasts'))
    limits = models.TextField(verbose_name=_('Limits and precautions'))
    state = models.CharField(max_length=12, default='draft', choices=[('draft', _('Draft')), ('review', _('In review')), ('published', _('Published')), ('withdrawn', _('Withdrawn'))])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['series', 'version'], name='unique_lexical_pack_version')]

    def __str__(self):
        return f'{self.title} · v{self.version}'

    def fingerprint(self):
        values = {f.attname: getattr(self, f.attname) for f in self._meta.concrete_fields if f.name not in ['id', 'state', 'created_at', 'created_by']}
        values['candidates'] = [candidate.content_snapshot() for candidate in self.candidates.order_by('pk')]
        return digest_value(values)

    def clean(self):
        old = LexicalPack.objects.filter(pk=self.pk).first()
        if old and old.state in ['published', 'withdrawn']:
            if any(getattr(old, f.attname) != getattr(self, f.attname) for f in self._meta.concrete_fields if f.name != 'state') or self.state not in [old.state, 'withdrawn']:
                raise ValidationError(_('Create a new version to change published content.'))
        if self.state == 'published' and (not old or old.state != 'published'):
            from .services import pack_readiness_reasons
            reasons = pack_readiness_reasons(self)
            if reasons:
                raise ValidationError(reasons)

class LexicalCandidate(CheckedModel):
    pack = models.ForeignKey(LexicalPack, on_delete=models.CASCADE, related_name='candidates')
    word = models.CharField(max_length=100, verbose_name=_('Candidate word'))
    meaning = models.TextField(verbose_name=_('Meaning and intended image'))
    ipa = models.CharField(max_length=160, blank=True, verbose_name=_('Working IPA transcription'))
    segments = models.JSONField(default=list, blank=True, verbose_name=_('Ordered phoneme segments'))
    occurrences = models.JSONField(default=list, blank=True, verbose_name=_('Target occurrences and positions'))
    accepted_variants = models.JSONField(default=list, blank=True, verbose_name=_('Admissible variants and reasons'))
    synonyms = models.JSONField(default=list, blank=True, verbose_name=_('Spontaneous alternative names'))
    role = models.CharField(max_length=12, choices=[('training', _('Training candidate')), ('reserved', _('Untrained reserve'))])
    provenance = models.TextField(verbose_name=_('Lexical source, region and uncertainty'))
    image = models.ForeignKey('catalog.MediaAsset', on_delete=models.PROTECT, related_name='+', null=True, blank=True)
    audio = models.ForeignKey('catalog.MediaAsset', on_delete=models.PROTECT, related_name='+', null=True, blank=True)

    def __str__(self):
        return self.word

    def content_snapshot(self):
        values = {f.attname: getattr(self, f.attname) for f in self._meta.concrete_fields if f.name != 'id'}
        for key in ['image', 'audio']:
            asset = getattr(self, key)
            values[key + '_manifest'] = asset.manifest_fingerprint() if asset else ''
        values['familiarity'] = [study.snapshot() for study in self.familiarity.order_by('pk')]
        return values

    def clean(self):
        from catalog.content_validation import validate_item_definition
        validate_item_definition({'meaning': self.meaning, 'segments': self.segments, 'target_occurrences': self.occurrences, 'accepted_variants': self.accepted_variants}, required=False)
        if self.pack_id and self.pack.state != 'draft':
            raise ValidationError(_('Candidate changes require a draft pack version.'))
        for field, kind in [('image', 'image'), ('audio', 'audio')]:
            if getattr(self, field + '_id') and getattr(self, field).kind != kind:
                raise ValidationError(_('The file type must match the selected media kind.'))

class FamiliarityStudy(CheckedModel):
    candidate = models.ForeignKey(LexicalCandidate, on_delete=models.CASCADE, related_name='familiarity')
    method = models.TextField(verbose_name=_('Exploratory method and exposure context'))
    participants = models.PositiveIntegerField(verbose_name=_('Number of observations'))
    recognized = models.PositiveIntegerField(verbose_name=_('Spontaneous intended names'))
    alternative_names = models.JSONField(default=list, blank=True, verbose_name=_('Alternative names, without identities'))
    evidence = models.ForeignKey(EvidenceDocument, on_delete=models.PROTECT)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    def snapshot(self):
        return {'method': self.method, 'participants': self.participants, 'recognized': self.recognized, 'alternative_names': self.alternative_names, 'evidence': str(self.evidence_id), 'sha256': self.evidence.sha256, 'recorded_by': str(self.recorded_by_id)}
    def clean(self):
        if self.candidate_id and self.candidate.pack.state != 'draft':
            raise ValidationError(_('Familiarity changes require a draft pack version.'))
        if not self.participants or self.recognized > self.participants:
            raise ValidationError(_('Counts must satisfy 0 ≤ recognised ≤ observations, with at least one observation.'))
        if self.evidence_id and (self.evidence.category != 'familiarity' or self.evidence.variety_id != self.candidate.pack.variety_id or not self.evidence.usable):
            raise ValidationError(_('An intact familiarity evidence document for this variety is required.'))
        if not isinstance(self.alternative_names, list) or any(not isinstance(x, str) for x in self.alternative_names):
            raise ValidationError(_('Alternative names must be a text list without participant identities.'))

class PackReview(CheckedModel):
    pack = models.ForeignKey(LexicalPack, on_delete=models.PROTECT, related_name='reviews')
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=DISCIPLINES)
    approved = models.BooleanField(default=False)
    note = models.TextField()
    content_digest = models.CharField(max_length=64, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    def clean(self):
        from .services import has_competence, pack_content_reasons
        from catalog.services import allowed
        if self.pack.state != 'review':
            raise ValidationError(_('Reviews require a submitted content version.'))
        if PackReview.objects.filter(pk=self.pk).exists():
            raise ValidationError(_('Reviews are immutable. Record a new decision.'))
        capability = 'clinical_review' if self.kind == 'clinical' else 'linguistic_review'
        if not allowed(self.reviewer, self.pack.variety, capability):
            raise ValidationError(_('Review permission for this discipline and variety is required.'))
        if self.approved:
            if not has_competence(self.reviewer, self.pack.variety, self.kind):
                raise ValidationError(_('Approval requires a declared competence for this discipline and variety.'))
            reasons = pack_content_reasons(self.pack)
            if reasons:
                raise ValidationError(reasons)
    def save(self, *args, **kwargs):
        self.content_digest = self.pack.fingerprint()
        return super().save(*args, **kwargs)
