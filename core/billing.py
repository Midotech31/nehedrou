"""Manual billing and access-rights controls."""
import hashlib
import json

from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from .form_scope import MAX_AGE
from .models import AuditEvent, Invoice
from .services import audit


ENTITLEMENT_EDIT_FIELDS = (
    'plan', 'status', 'expires_at', 'child_quota', 'practitioner_quota',
    'amount', 'currency', 'billing_reference',
)
ENTITLEMENT_SCOPE = 'core.billing-entitlement-edit.v1'


def entitlement_form_snapshot(request, organization, entitlement):
    """Bind a form to its actor, practice and the saved rights it represents.

    Validate a POST under the same organization lock used for writes. The audit
    revision also rejects replay after values have been restored to their old state.
    """
    digest = None
    if entitlement is not None:
        revision = AuditEvent.objects.filter(
            organization=organization, object_id=str(entitlement.pk),
            action__in=('entitlement.created', 'entitlement.updated'),
        ).order_by('-pk').values_list('pk', flat=True).first()
        values = [str(entitlement.pk), revision, *(str(getattr(entitlement, name)) for name in ENTITLEMENT_EDIT_FIELDS)]
        digest = hashlib.sha256(json.dumps(values, ensure_ascii=False).encode('utf-8')).hexdigest()
    expected = {'actor': str(request.user.pk), 'practice': str(organization.pk), 'rights': digest}
    if request.method != 'POST':
        return signing.dumps(expected, salt=ENTITLEMENT_SCOPE), True
    submitted = request.POST.getlist('entitlement_snapshot')
    if len(submitted) != 1 or not submitted[0] or len(submitted[0]) > 1024:
        return '', False
    token = submitted[0]
    try:
        state = signing.loads(token, salt=ENTITLEMENT_SCOPE, max_age=MAX_AGE)
    except (signing.BadSignature, ValueError, TypeError):
        return '', False
    return token, state == expected


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
