"""Private operator evidence metadata. No external actions or acceptance decisions."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.shortcuts import redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods

from .models import OperatorAcceptanceObservation, User
from .operator_acceptance import (
    OperatorAcceptanceCheck, OperatorObservationOutcome, OperatorObservationScope,
    validate_evidence_sha256, validate_observed_on,
)
from .services import audit


class OperatorObservationForm(forms.Form):
    check = forms.ChoiceField(label=_('Operator check'), choices=[('', '—'), *OperatorAcceptanceCheck.choices])
    scope = forms.ChoiceField(label=_('Observed environment'), choices=[('', '—'), *OperatorObservationScope.choices])
    outcome = forms.ChoiceField(label=_('Reported outcome'), choices=[('', '—'), *OperatorObservationOutcome.choices])
    observed_on = forms.DateField(
        label=_('Observation date'), validators=[validate_observed_on], input_formats=['%Y-%m-%d'],
        widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}),
    )
    evidence_sha256 = forms.CharField(
        label=_('Evidence SHA-256'), max_length=64, validators=[validate_evidence_sha256],
        widget=forms.TextInput(attrs={'dir': 'ltr', 'spellcheck': 'false', 'autocomplete': 'off'}),
    )


def latest_operator_observations():
    """Use the latest observation date, with the append time breaking ties."""
    records = OperatorAcceptanceObservation.objects.all()
    latest = records.filter(check_code=OuterRef('check_code'), scope=OuterRef('scope')).values('pk')[:1]
    return records.filter(pk=Subquery(latest)).order_by('check_code', 'scope')


@login_required
@permission_required('core.manage_entitlements', raise_exception=True)
@require_http_methods(['GET', 'HEAD', 'POST'])
def operator_evidence(request):
    form = OperatorObservationForm(request.POST if request.method == 'POST' else None)
    status = 200
    if request.method == 'POST':
        status = 400
        if request.FILES or set(request.POST) - {*form.fields, 'csrfmiddlewaretoken'}:
            form.add_error(None, _('Submit only the listed operator evidence fields.'))
        elif form.is_valid():
            with transaction.atomic():
                actor = User.objects.select_for_update(no_key=True).filter(pk=request.user.pk, is_active=True).first()
                if actor is None or not actor.has_perm('core.manage_entitlements'):
                    raise PermissionDenied
                data = form.cleaned_data.copy()
                data['check_code'] = data.pop('check')
                observation = OperatorAcceptanceObservation.objects.create(recorded_by=actor, **data)
                audit(actor, 'operations.acceptance_observation_recorded', observation, purpose_code='other')
            messages.success(request, _('The operator observation was recorded.'))
            response = redirect('operator_acceptance_evidence')
            response['Cache-Control'] = 'private, no-store'
            response['X-Robots-Tag'] = 'noindex, nofollow'
            return response
    page = Paginator(OperatorAcceptanceObservation.objects.all(), 25).get_page(request.GET.get('page'))
    response = render(request, 'operator_evidence.html', {
        'page_title': _('Operator evidence register'), 'nav_section': 'operations', 'form': form,
        'observations': page.object_list, 'page': page,
    }, status=status)
    response['Cache-Control'] = 'private, no-store'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response
