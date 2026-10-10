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
        labels = {'fr-fr-pilot': _('French · France (pilot)'), 'en-us-general-pilot': _('English · United States (pilot)'), 'ar-dz-pilot': _('Arabic · Algeria (pilot)')}
        return labels.get(self.code, self.label)
    def __str__(self):
        return str(self.display_label)

class Activity(CheckedModel):
    variety = models.ForeignKey(Variety, on_delete=models.PROTECT)
    series = models.UUIDField()
    version = models.PositiveIntegerField(default=1)
    title = models.CharField(max_length=160)
    contrast = models.CharField(max_length=60)
    word_a = models.CharField(max_length=80)
    word_b = models.CharField(max_length=80)
    transcription_a = models.CharField(max_length=100, blank=True)
    transcription_b = models.CharField(max_length=100, blank=True)
    image_a = models.CharField(max_length=160, blank=True, help_text='Editorial static path')
    image_b = models.CharField(max_length=160, blank=True)
    audio_a = models.URLField(blank=True)
    audio_b = models.URLField(blank=True)
    instructions = models.JSONField(default=dict)
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
        values = {field.attname: getattr(self, field.attname) for field in self._meta.concrete_fields if field.name not in ['id', 'state', 'created_at']}
        return hashlib.sha256(json.dumps(values, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()
    def has_current_reviews(self):
        # The latest decision of each discipline for this exact version prevails.
        reviews = self.reviews.filter(content_digest=self.fingerprint())
        return all((decision := reviews.filter(kind=kind).order_by('-created_at', '-pk').first())
                   and decision.approved for kind in ['clinical', 'linguistic'])
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
        return (all(self.image_available(ref) for ref in [self.image_a, self.image_b])
                and (self.is_demo or all(self.audio_available(ref) for ref in [self.audio_a, self.audio_b])))
    def clean(self):
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
                if field.name != 'state' and getattr(self, field.attname) != getattr(old, field.attname):
                    raise ValidationError(_('Create a new version to change published content.'))
            if self.state not in [old.state, 'withdrawn']:
                raise ValidationError(_('A published version cannot return to draft.'))
        if self.state == 'published' and (not old or old.state != 'published'):
            if not self.rights or not self.population or not all(self.instructions.get(code) for code, _label in settings.LANGUAGES) or not self.image_a or not self.image_b:
                raise ValidationError(_('Publication requires media, rights, population and all instructions.'))
            if not all(self.image_available(media) for media in [self.image_a, self.image_b]):
                raise ValidationError(_('Publication requires available editorial images.'))
            if not self.is_demo:
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
        if self.activity_id and self.activity.state not in ['review', 'approved']:
            raise ValidationError(_('Reviews require a submitted content version.'))
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
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    technical_metadata = models.JSONField(default=dict, blank=True, editable=False)
    def clean(self):
        old = MediaAsset.objects.filter(pk=self.pk).first()
        if old:
            if not self.file._committed or old.file.name != self.file.name or old.kind != self.kind or old.technical_metadata != self.technical_metadata:
                raise ValidationError(_('Uploaded media cannot be replaced. Upload a new file.'))
        elif self.file and self.kind:
            from .media_validation import validate_media
            self.technical_metadata = validate_media(self.file, self.kind)
