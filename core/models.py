import hashlib
import secrets
import uuid
from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from .billing_validation import validate_billing_currency

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
    def clean(self):
        old = Membership.objects.filter(pk=self.pk).first()
        if old and (not self.active or old.organization_id != self.organization_id or old.user_id != self.user_id):
            from care.models import Child
            if Child.objects.filter(organization_id=old.organization_id, responsible_id=old.user_id).exists():
                raise ValidationError(_('Transfer all assigned child profiles, including archived profiles, before revoking this practitioner. The responsible clinician must transfer each profile to an active practice member.'))
    class Meta:
        constraints = [models.UniqueConstraint(fields=['organization', 'user'], name='unique_member')]

class ChildResponsibilityTransfer(CheckedModel):
    """Preserve who transferred a dossier without rewriting clinical authorship."""
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT)
    child = models.ForeignKey('care.Child', on_delete=models.CASCADE, related_name='responsibility_transfers')
    previous_clinician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    new_clinician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

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
    def clean(self):
        super().clean()
        errors = {}
        # Field validation may already have rejected a non-numeric value.
        if isinstance(self.amount, Decimal) and self.amount.is_finite() and self.amount < 0:
            errors['amount'] = _('The amount cannot be negative.')
        try:
            validate_billing_currency(self.currency)
        except ValidationError as error:
            errors['currency'] = error.messages
        if errors:
            raise ValidationError(errors)
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
    PURPOSE_CHOICES = [
        ('care_delivery', _('Care delivery')),
        ('family_practice', _('Family home practice')),
        ('clinical_followup', _('Clinical follow-up')),
        ('data_portability', _('Data portability')),
        ('practice_admin', _('Practice administration')),
        ('account_security', _('Account security')),
        ('content_review', _('Content review')),
        ('billing_admin', _('Billing administration')),
        ('data_rights', _('Data rights')),
        ('other', _('Other documented purpose')),
    ]
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, null=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    actor_ref = models.CharField(max_length=64, blank=True)
    action = models.CharField(max_length=60)
    purpose_code = models.CharField(max_length=32, blank=True, choices=PURPOSE_CHOICES)
    object_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at']

class ProcessingActivity(CheckedModel):
    """Operator-maintained processing register entry; not a legal determination."""
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, null=True, blank=True,
                                    related_name='processing_activities')
    register_capacity = models.CharField(max_length=16, choices=[
        ('controller', _('Controller')), ('processor', _('Processor'))], default='controller')
    name = models.CharField(max_length=120)
    controller_name = models.CharField(max_length=160)
    controller_contact = models.CharField(max_length=254)
    data_protection_contact = models.CharField(max_length=254, blank=True)
    purposes = models.TextField()
    legal_basis = models.TextField()
    data_subject_categories = models.TextField()
    personal_data_categories = models.TextField()
    recipient_categories = models.TextField(help_text=_('Include recipients in other countries or international organisations.'))
    international_transfers = models.TextField(help_text=_('Describe destinations and safeguards, or explicitly record that none are identified.'))
    retention_periods = models.TextField()
    security_measures = models.TextField()
    operations = models.TextField(help_text=_('Describe collection, recording, storage, consultation, sharing, correction, restriction and deletion operations in scope.'))
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='created_processing_activities')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='updated_processing_activities')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['organization__name', 'name', 'pk']
        permissions = [('manage_processing_register', _('Can manage processing register entries'))]

    def __str__(self):
        return self.name


class ProcessingActivityRevision(models.Model):
    """Append-only snapshot of each saved processing-register state."""
    activity = models.ForeignKey(ProcessingActivity, on_delete=models.PROTECT, related_name='revisions')
    revision = models.PositiveIntegerField()
    snapshot = models.JSONField()
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='processing_activity_revisions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['activity_id', 'revision']
        constraints = [models.UniqueConstraint(fields=['activity', 'revision'], name='unique_processing_activity_revision')]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError(_('Register history entries are append-only.'))
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(_('Register history entries cannot be deleted.'))


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
    blocked_until = models.DateTimeField(null=True, blank=True)

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
        old = Invoice.objects.filter(pk=self.pk).first()
        # Retain legacy recorded currencies when finalising an existing invoice.
        if old is None:
            try:
                validate_billing_currency(self.currency)
            except ValidationError as error:
                raise ValidationError({'currency': error.messages})
        if old:
            fixed = ('organization_id', 'number', 'amount', 'currency', 'issued_at')
            if any(getattr(self, field) != getattr(old, field) for field in fixed):
                raise ValidationError(_('The recorded invoice number, practice, amount, currency and issue date cannot be changed.'))
            if old.status in ('paid', 'cancelled') and (self.status != old.status or self.paid_at != old.paid_at or self.reference != old.reference):
                raise ValidationError(_('This invoice already has a final status. No new status was recorded.'))
            if self.status != old.status and (old.status != 'issued' or self.status not in ('paid', 'cancelled')):
                raise ValidationError(_('Choose paid or cancelled for an issued invoice.'))
        if self.status == 'paid' and self.paid_at is None:
            raise ValidationError(_('A paid invoice requires its payment recording date.'))
        if self.status != 'paid' and self.paid_at is not None:
            raise ValidationError(_('Only a paid invoice can have a payment recording date.'))

class NoticeAcknowledgement(CheckedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    version = models.CharField(max_length=30)
    language = models.CharField(max_length=2, choices=settings.LANGUAGES)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'organization', 'version'], name='unique_notice_ack')]
