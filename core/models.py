import hashlib
import secrets
import uuid
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

class User(AbstractUser):
    email = models.EmailField(unique=True)
    instruction_language = models.CharField(max_length=2, choices=settings.LANGUAGES, default='fr', verbose_name=_('Parent instruction language'))
    def clean(self):
        super().clean()
        self.email = self.email.lower().strip()
    class Meta:
        constraints = [models.UniqueConstraint(models.functions.Lower('email'), name='unique_email_casefold')]

class CheckedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    class Meta:
        abstract = True
    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

class Organization(CheckedModel):
    name = models.CharField(max_length=120, verbose_name=_('Practice name'))
    country = models.CharField(max_length=2, default='DZ')
    created_at = models.DateTimeField(auto_now_add=True)
    retention_days = models.PositiveIntegerField(null=True, blank=True)
    def __str__(self):
        return self.name

class Membership(CheckedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=12, choices=[('owner', _('Practice manager')), ('clinician', _('Clinician'))])
    active = models.BooleanField(default=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'user'], name='unique_member')]

class Entitlement(CheckedModel):
    organization = models.OneToOneField(Organization, on_delete=models.CASCADE)
    plan = models.CharField(max_length=60, default='Manual pilot')
    child_quota = models.PositiveIntegerField(default=15)
    practitioner_quota = models.PositiveIntegerField(default=2)
    expires_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=12, choices=[('active', _('Active')), ('expired', _('Expired')), ('cancelled', _('Cancelled'))], default='active')
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default='EUR')
    billing_reference = models.CharField(max_length=100, blank=True)
    class Meta:
        permissions = [('manage_entitlements', 'Can manage manual billing and access')]
    @property
    def usable(self):
        return self.status == 'active' and self.expires_at > timezone.now()

class Invitation(CheckedModel):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    child = models.ForeignKey('care.Child', on_delete=models.CASCADE, null=True, blank=True)
    kind = models.CharField(max_length=12, choices=[('family', _('Family')), ('clinician', _('Clinician'))], default='family')
    email = models.EmailField()
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    expires_at = models.DateTimeField()
    revoked = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    delivery = models.CharField(max_length=12, default='pending', choices=[('pending', _('Pending delivery')), ('sent', _('Sent to mail service')), ('failed', _('Delivery failed')), ('console', _('Local console only'))])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    def clean(self):
        if self.kind == 'family' and not self.child_id:
            raise ValidationError(_('A family invitation requires a child profile.'))
        if self.kind == 'clinician' and self.child_id:
            raise ValidationError(_('A practitioner invitation must not include a child profile.'))
        if self.child_id and self.child.organization_id != self.organization_id:
            raise ValidationError(_('The child must belong to this practice.'))
    @classmethod
    def issue(cls, organization, child, email, actor, kind='family'):
        token = secrets.token_urlsafe(32)
        obj = cls.objects.create(organization=organization, child=child, kind=kind, email=email.lower(), created_by=actor, token_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=timezone.now() + timedelta(days=3))
        return obj, token
    @property
    def available(self):
        return not self.revoked and self.used_at is None and self.expires_at > timezone.now()

class AuditEvent(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, null=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=60)
    object_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at']

class PrivacyRequest(CheckedModel):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    child = models.ForeignKey('care.Child', on_delete=models.SET_NULL, null=True, blank=True)
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=12, choices=[('export', _('Export')), ('erasure', _('Erasure'))])
    status = models.CharField(max_length=12, default='pending', choices=[('pending', _('Pending')), ('resolved', _('Resolved'))])
    created_at = models.DateTimeField(auto_now_add=True)
    decision_reason = models.CharField(max_length=500, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    def clean(self):
        if self.child_id and self.child.organization_id != self.organization_id:
            raise ValidationError(_('The child must belong to this practice.'))

class RateWindow(models.Model):
    key = models.CharField(max_length=64, unique=True)
    count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

class RecoveryCode(CheckedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    digest = models.CharField(max_length=64, unique=True)

class Invoice(CheckedModel):
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    number = models.CharField(max_length=60, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='EUR')
    status = models.CharField(max_length=12, choices=[('issued', _('Issued')), ('paid', _('Paid')), ('cancelled', _('Cancelled'))], default='issued')
    issued_at = models.DateTimeField(auto_now_add=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    reference = models.CharField(max_length=100, blank=True)
    def clean(self):
        if self.amount is not None and self.amount < 0:
            raise ValidationError(_('The amount cannot be negative.'))

class NoticeAcknowledgement(CheckedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    version = models.CharField(max_length=30)
    language = models.CharField(max_length=2, choices=settings.LANGUAGES)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'organization', 'version'], name='unique_notice_ack')]
