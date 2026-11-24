"""Labels and validation shared by the technical checklist and its evidence records."""
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db.models import TextChoices
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class OperatorAcceptanceCheck(TextChoices):
    TRUSTED_PROXY_CHAIN = 'trusted_proxy_chain', _('Verification of the trusted proxy chain')
    PRIVATE_STORAGE = 'private_storage_access_and_restart', _('Test of private storage access and persistence after restart')
    OFFHOST_BACKUP = 'offhost_backup_destination_and_schedule', _('Test of the encrypted off-host backup destination and schedule')
    KEY_CUSTODY = 'key_custody_and_retention', _('Verification of backup key custody and archive retention')
    RESTORE = 'recent_restore_and_dossier_access', _('Recent restore test and access to restored dossiers')
    ALERTS = 'alert_recipients_and_escalation', _('Test of alert recipients and escalation procedure')
    EMAIL = 'live_email_delivery', _('Receipt of invitation and recovery emails and successful use of their links')
    RECOVERY_OBJECTIVES = 'validated_recovery_objectives', _('Validation of recovery time and data-loss objectives')


class OperatorObservationScope(TextChoices):
    LOCAL_FICTIONAL = 'local_fictional', _('Local test with fictional data')
    HOSTED_DEMO = 'hosted_demo', _('Hosted demonstration')
    TARGET_SERVICE = 'target_service', _('Intended live service')


class OperatorObservationOutcome(TextChoices):
    COMPLETED = 'completed', _('Reported successful check')
    GAP_FOUND = 'gap_found', _('Reported issue or incomplete result')


validate_evidence_sha256 = RegexValidator(
    r"\A[0-9a-fA-F]{64}\Z", _('Enter a SHA-256 digest with exactly 64 hexadecimal characters.'),
)


def validate_observed_on(value):
    if value > timezone.localdate():
        raise ValidationError(_('The observation date cannot be in the future.'), code='future_observation')
