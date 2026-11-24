"""Permission-limited manual invoice details and status recording."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_POST, require_safe

from .access import manager
from .billing import (
    INVOICE_SHAREABLE_STATUSES, INVOICE_SHARING_ACTIONS, invoice_sharing_snapshot, transition_invoice,
)
from .models import AuditEvent, Invoice, User
from .services import audit


class InvoiceStatusForm(forms.Form):
    status = forms.ChoiceField(label=_('New invoice status'), choices=[
        ('paid', _('Paid')), ('cancelled', _('Cancelled')),
    ])
    reference = forms.CharField(label=_('Payment or cancellation reference'), max_length=100,
        required=False, help_text=_('Use the reference of the payment received or the cancellation record.'))


@login_required
@permission_required('core.manage_entitlements', raise_exception=True)
@require_GET
def invoice_detail(request, pk):
    invoice = get_object_or_404(Invoice.objects.select_related('organization'), pk=pk)
    form = InvoiceStatusForm(initial={'reference': invoice.reference}) if invoice.status == 'issued' else None
    events = AuditEvent.objects.filter(object_id=str(invoice.pk), organization=invoice.organization,
        action__in=('invoice.recorded', 'invoice.paid', 'invoice.cancelled', *INVOICE_SHARING_ACTIONS)
    ).select_related('actor').order_by('created_at', 'pk')
    sharing_snapshot, _valid = invoice_sharing_snapshot(request, invoice)
    response = render(request, 'billing/invoice_detail.html', {
        'invoice': invoice, 'status_form': form, 'events': events,
        'invoice_sharing_snapshot': sharing_snapshot,
        'can_share_invoice': invoice.status in INVOICE_SHAREABLE_STATUSES,
    })
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@permission_required('core.manage_entitlements', raise_exception=True)
@require_POST
def invoice_sharing(request, pk):
    requested = request.POST.getlist('visibility')
    if requested not in (['share'], ['unshare']):
        return HttpResponseBadRequest()
    should_share = requested[0] == 'share'
    with transaction.atomic():
        # Use the same row locks as payment and cancellation.
        invoice = get_object_or_404(Invoice.objects.select_for_update().select_related('organization'), pk=pk)
        actor = User.objects.select_for_update(no_key=True).filter(pk=request.user.pk, is_active=True).first()
        if actor is None or not actor.has_perm('core.manage_entitlements'):
            raise PermissionDenied
        _token, matches = invoice_sharing_snapshot(request, invoice)
        if not matches:
            return render(request, 'notice.html', {
                'title': _('Billing summary sharing'),
                'body': _('Reopen the invoice to review its current status and sharing setting before saving.'),
            }, status=409)
        if should_share and invoice.status not in INVOICE_SHAREABLE_STATUSES:
            return HttpResponseBadRequest()
        if bool(invoice.shared_with_practice_at) != should_share:
            invoice.shared_with_practice_at = timezone.now() if should_share else None
            invoice.save(update_fields=['shared_with_practice_at'])
            action = INVOICE_SHARING_ACTIONS[0] if should_share else INVOICE_SHARING_ACTIONS[1]
            audit(actor, action, invoice, invoice.organization)
    return redirect('invoice_detail', pk=pk)


@login_required
@require_safe
def practice_billing_summary(request):
    member = manager(request)
    if request.practice_selection_required:
        raise Http404
    # Project only the fields intended for the cabinet.
    invoices = Invoice.objects.filter(
        organization_id=member.organization_id, shared_with_practice_at__isnull=False,
        status__in=INVOICE_SHAREABLE_STATUSES,
    ).order_by('-issued_at', '-pk').values('number', 'amount', 'currency', 'status', 'issued_at', 'paid_at')
    page = Paginator(invoices, 25).get_page(request.GET.get('page'))
    labels = dict(Invoice._meta.get_field('status').choices)
    rows = [{**row, 'status_label': labels[row['status']]} for row in page.object_list]
    response = render(request, 'billing/practice_summary.html', {'invoices': rows, 'page': page})
    response['Cache-Control'] = 'private, no-store'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@login_required
@permission_required('core.manage_entitlements', raise_exception=True)
@require_POST
def invoice_status(request, pk):
    get_object_or_404(Invoice, pk=pk)
    form = InvoiceStatusForm(request.POST)
    if form.is_valid():
        try:
            transition_invoice(request.user, pk, form.cleaned_data['status'], form.cleaned_data['reference'])
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
        else:
            messages.success(request, _('The invoice status was recorded.'))
    else:
        messages.error(request, ' '.join(message for errors in form.errors.values() for message in errors))
    return redirect('invoice_detail', pk=pk)
