from core.storage_health import file_exists
import hashlib
import json
import secrets
from datetime import timedelta
from pathlib import Path
from django.core.exceptions import ValidationError
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from core.models import CheckedModel
from qualification.validity import VALIDITY_CHOICES

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
        from .integrity import activity_reviews
        reviews = activity_reviews(self)
        digest = self.fingerprint()
        decisions = []
        for kind in ['clinical', 'linguistic']:
            decision = next((review for review in reviews if review.content_digest == digest and review.kind == kind), None)
            capability = 'clinical_review' if kind == 'clinical' else 'linguistic_review'
            if not decision or not decision.approved or not allowed(decision.reviewer, self.variety, capability) or not has_competence(decision.reviewer, self.variety, kind):
                return False
            decisions.append(decision)
        return decisions[0].reviewer_id != decisions[1].reviewer_id

    @property
    def device_voice_allowed(self):
        # Device synthesis is an explicitly unreviewed lexical aid, never Darja.
        return bool(settings.DEMO_MODE and self.is_demo and self.variety.code in ['fr-fr-pilot', 'en-us-general-pilot', 'ar-msa-pilot']
                    and self.kind not in ['word_pair', 'phonological_contrast'])

    @property
    def device_voice_language(self):
        return {'fr-fr-pilot': 'fr-FR', 'en-us-general-pilot': 'en-US', 'ar-msa-pilot': 'ar-SA'}.get(self.variety.code, '')

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
        return bool(asset and asset.technical_metadata.get('format') in ['WAV', 'MP3'] and asset.rights.strip() and file_exists(asset.file))
    def image_available(self, reference):
        if reference.startswith('editorial/asset-'):
            try:
                asset = MediaAsset.objects.filter(pk=reference[len('editorial/asset-'):], kind='image').first()
            except ValidationError:
                return False
            return bool(asset and asset.technical_metadata.get('format') in ['PNG', 'JPEG', 'WEBP'] and asset.rights.strip() and file_exists(asset.file))
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
                raise ValidationError(_('Approval requires independently verified competence for this discipline and variety.'))
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

class EditorialAccessInvitation(CheckedModel):
    CAPABILITIES = [
        ('edit', _('Edit draft content')),
        ('clinical_review', _('Review clinical content')),
        ('linguistic_review', _('Review language and spoken variety')),
    ]
    email = models.EmailField()
    variety = models.ForeignKey(Variety, on_delete=models.PROTECT)
    capability = models.CharField(max_length=20, choices=CAPABILITIES)
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField()
    revoked = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='accepted_editorial_invitations')
    delivery = models.CharField(max_length=12, default='pending', choices=[('pending', _('Pending delivery')), ('sent', _('Sent to mail service')), ('failed', _('Delivery failed')), ('console', _('Local console only')), ('manual', _('Link created for manual handoff'))])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='created_editorial_invitations')

    class Meta:
        indexes = [models.Index(fields=['email', 'variety', 'capability', 'used_at'])]

    @classmethod
    def issue(cls, email, variety, capability, actor, *, invitation_id=None, delivery='pending'):
        token = secrets.token_urlsafe(32)
        identity = {'id': invitation_id} if invitation_id is not None else {}
        obj = cls.objects.create(email=email.strip().lower(), variety=variety, capability=capability,
            created_by=actor, token_hash=hashlib.sha256(token.encode()).hexdigest(), delivery=delivery,
            expires_at=timezone.now() + timedelta(days=7), **identity)
        return obj, token

    @property
    def available(self):
        return not self.revoked and self.used_at is None and self.expires_at > timezone.now()


class MediaAsset(CheckedModel):
    file = models.FileField(upload_to='editorial/%Y/%m/')
    kind = models.CharField(max_length=8, choices=[('image', _('Image')), ('audio', _('Audio'))])
    rights = models.TextField()
    rights_status = models.CharField(max_length=28, default='unknown', choices=[('original_documented', _('Documented original rights')), ('open_commercial_compatible', _('Compatible commercial licence')), ('permission_required', _('Permission required')), ('unknown', _('Unknown')), ('excluded', _('Excluded'))])
    provenance = models.JSONField(default=dict, blank=True, verbose_name=_('Rights holder, licence, scope, attribution and adult speaker permission'))
    rights_validity = models.CharField(max_length=12, default='unknown', choices=VALIDITY_CHOICES, verbose_name=_('Permission validity'))
    rights_valid_from = models.DateField(null=True, blank=True, verbose_name=_('Valid from (inclusive)'))
    rights_valid_until = models.DateField(null=True, blank=True, verbose_name=_('Valid until (inclusive)'))
    revoked = models.BooleanField(default=False)
    revocation_reason = models.TextField(blank=True)
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
            **({'rights_validity': self.rights_validity, 'rights_valid_from': self.rights_valid_from, 'rights_valid_until': self.rights_valid_until} if self.rights_validity != 'unknown' or self.rights_valid_from or self.rights_valid_until else {}),
            **({'revoked': True, 'revocation_reason': self.revocation_reason} if self.revoked else {}),
            **({'evidence_validity': evidence.validity, 'evidence_valid_from': evidence.valid_from, 'evidence_valid_until': evidence.valid_until} if evidence and (evidence.validity != 'unknown' or evidence.valid_from or evidence.valid_until) else {}),
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
    def rights_current(self):
        from qualification.validity import currently_valid
        return currently_valid(self.rights_validity, self.rights_valid_from, self.rights_valid_until, self.revoked)

    @property
    def documented(self):
        if not isinstance(self.provenance, dict) or not self.rights_current:
            return False
        required = ['holder','licence','permitted_use','territory','duration','attribution']
        if self.kind == 'audio':
            required += ['adult_speaker_permission']
            if self.technical_metadata.get('signal', {}).get('silent'):
                return False
            from .audio_checks import valid_audio_profile
            if not valid_audio_profile(self.provenance.get('audio')):
                return False
        return bool(self.intact and self.rights.strip() and self.rights_status in ['original_documented','open_commercial_compatible'] and self.rights_evidence_id and self.rights_evidence.category == 'rights' and self.rights_evidence.usable and isinstance(self.provenance,dict) and all(isinstance(self.provenance.get(key),str) and self.provenance[key].strip() for key in required))

    def clean(self):
        from qualification.validity import validate_validity
        validate_validity(self.rights_validity, self.rights_valid_from, self.rights_valid_until)
        if self.revoked and not self.revocation_reason.strip():
            raise ValidationError(_('A revocation reason is required.'))
        if not isinstance(self.provenance, dict):
            raise ValidationError(_('Media provenance must be an object.'))
        profile = self.provenance.get('audio')
        if profile is not None and profile != {}:
            valid = (isinstance(profile, dict) and self.kind == 'audio'
                     and profile.get('source') in ['human', 'synthetic', 'unspecified']
                     and isinstance(profile.get('text'), str) and 0 < len(profile['text'].strip()) <= 160
                     and isinstance(profile.get('variety'), str) and 0 < len(profile['variety']) <= 64
                     and isinstance(profile.get('region', ''), str) and len(profile.get('region', '')) <= 300)
            if not valid:
                raise ValidationError(_('Audio provenance must specify a valid voice source, exact text and spoken variety.'))
        old = MediaAsset.objects.filter(pk=self.pk).first()
        if old:
            if old.revoked and not self.revoked:
                raise ValidationError(_('Revoked media cannot be silently reinstated. Upload a new version.'))
            if not self.file._committed or old.file.name != self.file.name or old.kind != self.kind or old.technical_metadata != self.technical_metadata:
                raise ValidationError(_('Uploaded media cannot be replaced. Upload a new file.'))
        elif self.file and self.kind:
            from .media_validation import validate_media
            self.technical_metadata = validate_media(self.file, self.kind)


class DraftWorkingCopy(CheckedModel):
    """Personal, incomplete author input. It never enters Activity.usable."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, null=True, blank=True)
    data = models.JSONField(default=dict, blank=True)
    base_digest = models.CharField(max_length=64, blank=True)
    revision = models.PositiveIntegerField(default=0)
    committed = models.BooleanField(default=False)
    dismissed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        indexes = [models.Index(fields=['owner', 'committed', '-updated_at'])]


class GeneratedReviewPackImport(CheckedModel):
    """Immutable technical import receipt, never a clinical or rights decision."""
    pack_id = models.SlugField(max_length=100, unique=True)
    manifest_digest = models.CharField(max_length=64)
    variety = models.ForeignKey(Variety, on_delete=models.PROTECT)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    record = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if GeneratedReviewPackImport.objects.filter(pk=self.pk).exists():
            raise ValidationError('Generated review-pack import receipts are immutable.')
        if not isinstance(self.record, dict) or len(self.manifest_digest) != 64:
            raise ValidationError('A named exact manifest and structured import receipt are required.')
