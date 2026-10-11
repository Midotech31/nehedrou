import hashlib
import json
from pathlib import Path
from django.core.exceptions import ValidationError
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from core.models import CheckedModel

class Variety(CheckedModel):
    code = models.SlugField(unique=True)
    language = models.CharField(max_length=2, choices=settings.LANGUAGES)
    label = models.CharField(max_length=120)
    scope = models.TextField(blank=True)
    @property
    def display_label(self):
        labels = {'fr-fr-pilot': _('French · France (pilot)'), 'en-us-general-pilot': _('English · United States (pilot)'), 'ar-dz-pilot': _('Algerian Darja · local pilot'), 'ar-msa-pilot': _('Standard Arabic · educational pilot')}
        return labels.get(self.code, self.label)
    def __str__(self):
        return str(self.display_label)

class Activity(CheckedModel):
    variety = models.ForeignKey(Variety, on_delete=models.PROTECT)
    series = models.UUIDField()
    version = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=160)
    contrast = models.CharField(max_length=60)
    KIND_CHOICES = [('word_pair', _('Word exploration')), ('phonological_contrast', _('Phonological contrast')),
                    ('vocabulary', _('Vocabulary and comprehension')), ('requests', _('Requests and choices')),
                    ('categories', _('Categories and associations')), ('actions', _('Actions and verbs')),
                    ('relations', _('Spatial relations')), ('routines', _('Daily routines')),
                    ('storytelling', _('Short stories and conversation'))]
    THEME_CHOICES = [('', _('All themes')), ('home', _('Home')), ('food', _('Food')),
                     ('animals', _('Animals')), ('body', _('Body')), ('clothing', _('Clothing')),
                     ('travel', _('Travel')), ('play', _('Play')), ('daily_life', _('Everyday life')),
                     ('school', _('School')), ('nature', _('Nature')), ('sounds', _('Sounds'))]
    RESPONSE_CHOICES = [('matching', _('Requested picture choice')), ('free', _('Free choice without a correctness score')),
                        ('observation', _('Shared observation without a picture answer'))]
    kind = models.CharField(max_length=24, default='word_pair', choices=KIND_CHOICES)
    theme = models.CharField(max_length=20, blank=True, default='', choices=THEME_CHOICES)
    response_mode = models.CharField(max_length=12, default='matching', choices=RESPONSE_CHOICES)
    requested_target = models.CharField(max_length=1, blank=True, default='', choices=[('', _('Either word as requested')), ('a', _('First word')), ('b', _('Second word'))])
    search_text = models.TextField(blank=True, default='', editable=False)
    word_a = models.CharField(max_length=80)
    word_b = models.CharField(max_length=80)
    transcription_a = models.CharField(max_length=100, blank=True)
    transcription_b = models.CharField(max_length=100, blank=True)
    image_a = models.CharField(max_length=160, blank=True, help_text='Editorial static path')
    image_b = models.CharField(max_length=160, blank=True)
    audio_a = models.URLField(blank=True)
    audio_b = models.URLField(blank=True)
    instructions = models.JSONField(default=dict)
    practice_guide = models.JSONField(default=dict, blank=True)
    evidence_sources = models.JSONField(default=list, blank=True)
    item_metadata = models.JSONField(default=dict, blank=True, verbose_name=_('Word meanings, segments, occurrences, variants and familiarity'))
    media_manifest = models.JSONField(default=dict, blank=True, editable=False)
    rights = models.TextField(blank=True)
    population = models.TextField(blank=True)
    limitations = models.TextField(blank=True)
    is_demo = models.BooleanField(default=True)
    state = models.CharField(max_length=12, default='draft', choices=[('draft', _('Draft')), ('review', _('In review')), ('approved', _('Approved')), ('published', _('Published')), ('withdrawn', _('Withdrawn'))])
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['series', 'version'], name='unique_activity_version')]
        indexes = [models.Index(fields=['variety', 'state'])]
        permissions = [('publish_activity', 'Can publish reviewed activities'), ('review_activity', 'Can review activities')]
    def __str__(self):
        return f'{self.title} · v{self.version}'
    def fingerprint(self):
        values = {field.attname: getattr(self, field.attname) for field in self._meta.concrete_fields if field.name not in ['id', 'state', 'created_at', 'search_text']}
        # Empty additive fields preserve pre-guide digests and historical reviews.
        # Any actual guide/reference change is part of the reviewed content.
        for field in ['practice_guide', 'evidence_sources', 'item_metadata', 'media_manifest']:
            if not values.get(field):
                values.pop(field, None)
        for field, default in [('kind', 'word_pair'), ('theme', ''), ('response_mode', 'matching'), ('requested_target', '')]:
            if values.get(field) == default:
                values.pop(field, None)
        if self.media_manifest:
            from .readiness import snapshot_media
            values['current_media_manifest'] = snapshot_media(self)
        return hashlib.sha256(json.dumps(values, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()
    def has_current_reviews(self):
        # Latest decisions prevail. A single person cannot supply both approvals.
        from qualification.services import has_competence
        from .services import allowed
        from .readiness import media_binding_current
        if not self.is_demo and not media_binding_current(self):
            return False
        decisions = []
        for kind in ['clinical', 'linguistic']:
            decision = self.reviews.filter(content_digest=self.fingerprint(), kind=kind).order_by('-created_at', '-pk').first()
            capability = 'clinical_review' if kind == 'clinical' else 'linguistic_review'
            if not decision or not decision.approved or not allowed(decision.reviewer, self.variety, capability) or not has_competence(decision.reviewer, self.variety, kind):
                return False
            decisions.append(decision)
        return decisions[0].reviewer_id != decisions[1].reviewer_id

    @property
    def device_voice_allowed(self):
        # Unreviewed synthesis is confined to fictional, non-phonological MSA.
        return bool(settings.DEMO_MODE and self.is_demo and self.variety.code == 'ar-msa-pilot'
                    and self.kind not in ['word_pair', 'phonological_contrast'])

    def audio_available(self, reference):
        from urllib.parse import urlsplit
        from uuid import UUID
        source, origin = urlsplit(reference), urlsplit(settings.PUBLIC_ORIGIN)
        parts = source.path.strip('/').split('/')
        if (source.scheme not in ['http', 'https'] or source.netloc != origin.netloc
            or source.scheme != origin.scheme or source.query or source.fragment
            or len(parts) != 3 or parts[0] not in dict(settings.LANGUAGES) or parts[1] != 'media'):
            return False
        try:
            asset = MediaAsset.objects.filter(pk=UUID(parts[2]), kind='audio').first()
        except ValueError:
            return False
        return bool(asset and asset.technical_metadata.get('format') in ['WAV', 'MP3'] and asset.rights.strip() and asset.file.storage.exists(asset.file.name))
    def image_available(self, reference):
        if reference.startswith('editorial/asset-'):
            try:
                asset = MediaAsset.objects.filter(pk=reference[len('editorial/asset-'):], kind='image').first()
            except ValidationError:
                return False
            return bool(asset and asset.technical_metadata.get('format') in ['PNG', 'JPEG'] and asset.rights.strip() and asset.file.storage.exists(asset.file.name))
        return bool(reference.startswith('editorial/') and '..' not in reference and (Path(settings.BASE_DIR) / 'static' / reference).is_file())
    @property
    def usable(self):
        if self.state != 'published' or (self.is_demo and not settings.DEMO_MODE):
            return False
        if not self.is_demo:
            from .readiness import activity_readiness
            return activity_readiness(self, require_availability=True)['ready']
        return (all(self.image_available(ref) for ref in [self.image_a, self.image_b])
                and (self.is_demo or all(self.audio_available(ref) for ref in [self.audio_a, self.audio_b])))
    def save(self, *args, **kwargs):
        from .search import activity_search_text
        self.search_text = activity_search_text(self)
        if kwargs.get('update_fields') is not None:
            kwargs['update_fields'] = set(kwargs['update_fields']) | {'search_text'}
        return super().save(*args, **kwargs)

    def clean(self):
        from .content_validation import validate_content_guide, validate_item_metadata
        validate_content_guide(self.practice_guide, self.evidence_sources)
        validate_item_metadata(self.item_metadata)
        if self.response_mode != 'matching' and self.requested_target:
            raise ValidationError(_('A free choice or observation cannot impose a requested picture.'))
        if self.kind == 'phonological_contrast':
            from .content_validation import validate_minimal_pair
            validate_minimal_pair(self.item_metadata, self.response_mode)
        if Activity.objects.filter(series=self.series).exclude(pk=self.pk).exclude(variety_id=self.variety_id).exists():
            raise ValidationError(_('A content series must keep the same spoken variety.'))
        if not isinstance(self.instructions, dict) or any(k not in dict(settings.LANGUAGES) or not isinstance(v, str) for k, v in self.instructions.items()):
            raise ValidationError(_('Instructions must contain language codes and text.'))
        for path in [self.image_a, self.image_b]:
            if path and (not path.startswith('editorial/') or '..' in path):
                raise ValidationError(_('Invalid editorial media path.'))
        old = Activity.objects.filter(pk=self.pk).first()
        if old and old.state in ['published', 'withdrawn']:
            for field in self._meta.concrete_fields:
                if field.name not in ['state', 'search_text'] and getattr(self, field.attname) != getattr(old, field.attname):
                    raise ValidationError(_('Create a new version to change published content.'))
            if self.state not in [old.state, 'withdrawn']:
                raise ValidationError(_('A published version cannot return to draft.'))
        if self.state == 'published' and (not old or old.state != 'published'):
            if not self.rights or not self.population or not all(self.instructions.get(code) for code, _label in settings.LANGUAGES) or not self.image_a or not self.image_b:
                raise ValidationError(_('Publication requires media, rights, population and all instructions.'))
            if not all(self.image_available(media) for media in [self.image_a, self.image_b]):
                raise ValidationError(_('Publication requires available editorial images.'))
            if not self.is_demo:
                from .readiness import activity_readiness
                readiness = activity_readiness(self, require_availability=False)
                if not readiness['ready']:
                    raise ValidationError(readiness['reasons'])
                if not self.audio_a or not self.audio_b or not self.transcription_a or not self.transcription_b:
                    raise ValidationError(_('Reviewed audio and transcription are required.'))
                if not all(self.audio_available(media) for media in [self.audio_a, self.audio_b]):
                    raise ValidationError(_('Publication requires available protected audio with usage rights.'))
                if not self.has_current_reviews():
                    raise ValidationError(_('Clinical and linguistic reviews are required.'))

class Review(CheckedModel):
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name='reviews')
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=[('clinical', _('Clinical')), ('linguistic', _('Linguistic'))])
    approved = models.BooleanField(default=False)
    note = models.TextField()
    content_digest = models.CharField(max_length=64, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    def clean(self):
        from qualification.services import has_competence
        from .services import allowed
        from .readiness import activity_content_reasons
        if Review.objects.filter(pk=self.pk).exists():
            raise ValidationError(_('Reviews are immutable. Record a new decision.'))
        if not self.reviewer_id or not self.activity_id:
            raise ValidationError(_('Review permission for this discipline and variety is required.'))
        if self.activity.state not in ['review', 'approved']:
            raise ValidationError(_('Reviews require a submitted content version.'))
        capability = 'clinical_review' if self.kind == 'clinical' else 'linguistic_review'
        if not allowed(self.reviewer, self.activity.variety, capability):
            raise ValidationError(_('Review permission for this discipline and variety is required.'))
        if self.approved:
            if not has_competence(self.reviewer, self.activity.variety, self.kind):
                raise ValidationError(_('Approval requires a declared competence for this discipline and variety.'))
            if not self.activity.is_demo:
                reasons = activity_content_reasons(self.activity)
                if reasons:
                    raise ValidationError(reasons)
    def save(self, *args, **kwargs):
        self.content_digest = self.activity.fingerprint()
        return super().save(*args, **kwargs)

class EditorialGrant(CheckedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    variety = models.ForeignKey(Variety, on_delete=models.CASCADE)
    edit = models.BooleanField(default=False)
    clinical_review = models.BooleanField(default=False)
    linguistic_review = models.BooleanField(default=False)
    publish = models.BooleanField(default=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'variety'], name='unique_editorial_grant')]

class MediaAsset(CheckedModel):
    file = models.FileField(upload_to='editorial/%Y/%m/')
    kind = models.CharField(max_length=8, choices=[('image', _('Image')), ('audio', _('Audio'))])
    rights = models.TextField()
    rights_status = models.CharField(max_length=28, default='unknown', choices=[('original_documented', _('Documented original rights')), ('open_commercial_compatible', _('Compatible commercial licence')), ('permission_required', _('Permission required')), ('unknown', _('Unknown')), ('excluded', _('Excluded'))])
    provenance = models.JSONField(default=dict, blank=True, verbose_name=_('Rights holder, licence, scope, attribution and adult speaker permission'))
    rights_evidence = models.ForeignKey('qualification.EvidenceDocument', on_delete=models.PROTECT, null=True, blank=True, related_name='media_assets')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    technical_metadata = models.JSONField(default=dict, blank=True, editable=False)
    def manifest_fingerprint(self):
        from qualification.models import digest_file, digest_value
        evidence = self.rights_evidence if self.rights_evidence_id else None
        evidence_actual_sha256 = digest_file(evidence.file) if evidence else ''
        return digest_value({
            'asset': str(self.pk), 'kind': self.kind,
            'sha256': self.technical_metadata.get('sha256', ''),
            'actual_file_sha256': digest_file(self.file),
            'rights': self.rights, 'rights_status': self.rights_status,
            'provenance': self.provenance,
            'evidence_id': str(self.rights_evidence_id or ''),
            'evidence_sha256': evidence.sha256 if evidence else '',
            'evidence_actual_sha256': evidence_actual_sha256,
            'evidence_revoked': evidence.revoked if evidence else False,
            'evidence_intact': bool(evidence and not evidence.revoked and evidence.sha256 and evidence.sha256 == evidence_actual_sha256),
        })

    @property
    def intact(self):
        from qualification.models import digest_file
        return bool(self.technical_metadata.get('sha256')) and digest_file(self.file) == self.technical_metadata['sha256']

    @property
    def documented(self):
        required = ['holder','licence','permitted_use','territory','duration','attribution']
        if self.kind == 'audio':
            required += ['adult_speaker_permission']
        return bool(self.intact and self.rights.strip() and self.rights_status in ['original_documented','open_commercial_compatible'] and self.rights_evidence_id and self.rights_evidence.category == 'rights' and self.rights_evidence.intact and isinstance(self.provenance,dict) and all(isinstance(self.provenance.get(key),str) and self.provenance[key].strip() for key in required))

    def clean(self):
        if not isinstance(self.provenance, dict):
            raise ValidationError(_('Media provenance must be an object.'))
        old = MediaAsset.objects.filter(pk=self.pk).first()
        if old:
            if not self.file._committed or old.file.name != self.file.name or old.kind != self.kind or old.technical_metadata != self.technical_metadata:
                raise ValidationError(_('Uploaded media cannot be replaced. Upload a new file.'))
        elif self.file and self.kind:
            from .media_validation import validate_media
            self.technical_metadata = validate_media(self.file, self.kind)
