"""Manual invoice bookkeeping. Payment collection and access rights are separate."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import Invoice
from .services import audit


@transaction.atomic
def transition_invoice(actor, invoice_id, status, reference=None):
    """Finalise an issued record once, preserving its commercial identity."""
    if not actor.is_active or not actor.has_perm('core.manage_entitlements'):
        raise PermissionDenied
    invoice = Invoice.objects.select_for_update().select_related('organization').get(pk=invoice_id)
    if status not in ('paid', 'cancelled'):
        raise ValidationError(_('Choose paid or cancelled for an issued invoice.'))
    if invoice.status != 'issued':
        raise ValidationError(_('This invoice already has a final status. No new status was recorded.'))
    invoice.status = status
    invoice.paid_at = timezone.now() if status == 'paid' else None
    if reference is not None and reference.strip():
        invoice.reference = reference.strip()
    invoice.save(update_fields=['status', 'paid_at', 'reference'])
    audit(actor, 'invoice.' + status, invoice, invoice.organization)
    return invoice
