"""Permission-limited manual invoice details and status recording."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET, require_POST

from .billing import transition_invoice
from .models import AuditEvent, Invoice


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
        action__in=['invoice.recorded', 'invoice.paid', 'invoice.cancelled']).select_related('actor').order_by('created_at', 'pk')
    response = render(request, 'billing/invoice_detail.html', {'invoice':invoice, 'status_form':form, 'events':events})
    response['Cache-Control'] = 'private, no-store'
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
