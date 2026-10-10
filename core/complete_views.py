from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from care.models import Child, Program, PracticeSession, ProgramItem, Observation, FamilyLink
from catalog.models import Activity
from .access import clinician_child, professional_children, manager, visible_children, membership
from .forms import ChildForm, ProgramForm, ReassignForm, PrivacyDecisionForm
from .models import Organization, PrivacyRequest, Invitation, Entitlement, Invoice, NoticeAcknowledgement
from .services import audit, check_entitlement, create_program, lock_clinical_child

@login_required
def child_edit(request, pk):
    child = clinician_child(request.user, pk)
    form = ChildForm(request.POST or None, instance=child)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                locked = lock_clinical_child(request.user, child)
                chosen = form.cleaned_data['varieties']
                active_varieties = locked.programs.filter(state='active').values_list('variety_id', flat=True)
                if any(pk not in chosen.values_list('pk', flat=True) for pk in active_varieties):
                    raise ValidationError(_('Keep the varieties of active programs or complete those programs first.'))
                locked.code = form.cleaned_data['code']
                locked.age_years = form.cleaned_data['age_years']
                locked.save()
                locked.varieties.set(chosen)
                audit(request.user, 'child.updated', locked, locked.organization)
            return redirect('child_detail', pk=pk)
        except ValidationError as error:
            form.add_error(None, error)
    return render(request, 'form.html', {'title': _('Edit child profile'), 'form': form, 'submit': _('Save')})

@login_required
@require_POST
def restore_child(request, pk):
    child = clinician_child(request.user, pk)
    try:
        with transaction.atomic():
            org = Organization.objects.select_for_update().get(pk=child.organization_id)
            child = lock_clinical_child(request.user, child)
            if not child.active:
                check_entitlement(org, creating_child=True)
                child.active = True
                child.save()
                audit(request.user, 'child.restored', child, org)
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    return redirect('child_detail', pk=pk)

@login_required
def reassign(request, pk):
    child = clinician_child(request.user, pk)
    form = ReassignForm(request.POST or None, organization=child.organization)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                child = lock_clinical_child(request.user, child)
                child.responsible = form.cleaned_data['responsible']
                child.save()
                audit(request.user, 'child.reassigned', child, child.organization)
            return redirect('children')
        except ValidationError as error:
            form.add_error(None, error)
    return render(request, 'form.html', {'title': _('Transfer professional responsibility'), 'form': form, 'submit': _('Transfer')})

@login_required
def program_replace(request, pk):
    program = get_object_or_404(Program, pk=pk, child__in=professional_children(request.user))
    form = ProgramForm(request.POST or None, child=program.child, initial={'title': program.title, 'variety': program.variety, 'activities': list(program.items.values_list('activity_id', flat=True)), 'guidance': program.guidance, 'schedule': program.schedule, 'goal': program.goal, 'activity_order': ','.join(str(pk) for pk in program.items.values_list('activity_id', flat=True))})
    preview = None
    if request.method == 'POST' and form.is_valid():
        if request.POST.get('action') == 'preview':
            preview = form.cleaned_data
        else:
            try:
                with transaction.atomic():
                    lock_clinical_child(request.user, program.child)
                    program = Program.objects.select_for_update().get(pk=pk)
                    if program.state != 'active':
                        raise ValidationError(_('This activity is no longer available. Contact your clinician.'))
                    new = create_program(request.user, program.child, form.cleaned_data)
                    program.state = 'completed'
                    program.save()
                    audit(request.user, 'program.replaced', program, program.organization)
                return redirect('program_detail', pk=new.pk)
            except ValidationError as error:
                form.add_error(None, error)
    return render(request, 'program_builder.html', {'title': _('Adjust program with a new version'), 'form': form, 'preview': preview, 'child': program.child, 'activities': form.fields['activities'].queryset, 'selected_activities': [str(pk) for pk in (form['activities'].value() or [])], 'submit': _('Assign updated program')})


def privacy_scope(request):
    from .models import Membership
    orgs = Membership.objects.filter(user=request.user, active=True, role='owner').values_list('organization_id', flat=True)
    return PrivacyRequest.objects.filter(Q(organization_id__in=orgs) | Q(child__in=professional_children(request.user))).distinct()

def retention_anchor(child):
    from care.models import PracticeRun, ProgramFeedback
    latest = PracticeSession.objects.filter(item__program__child=child).order_by('-created_at').first()
    latest_program = child.programs.order_by('-created_at').first()
    dates = [child.created_at]
    if latest: dates.append(latest.created_at)
    if latest_program: dates.append(latest_program.created_at)
    latest_run = PracticeRun.objects.filter(program__child=child).order_by('-started_at').first()
    last_finish = PracticeRun.objects.filter(program__child=child, finished_at__isnull=False).order_by('-finished_at').first()
    if latest_run: dates.append(latest_run.started_at)
    if last_finish: dates.append(last_finish.finished_at)
    feedback = ProgramFeedback.objects.filter(program__child=child).order_by('-created_at').first()
    if feedback: dates.append(feedback.created_at)
    return max(dates)

@login_required
def requests(request):
    return render(request, 'privacy/index.html', {'requests': privacy_scope(request).select_related('child', 'requester').order_by('-created_at')})

@login_required
def resolve_request(request, pk):
    obj = get_object_or_404(privacy_scope(request).select_related('child'), pk=pk)
    # A manager administers requests, but only the responsible clinician can erase clinical records.
    can_erase = obj.child and professional_children(request.user).filter(pk=obj.child_id).exists()
    form = PrivacyDecisionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            from .services import resolve_privacy
            resolve_privacy(request.user, obj.pk, form.cleaned_data)
            return redirect('privacy_requests')
        except ValidationError as error:
            form.add_error(None, error)
    return render(request, 'privacy/resolve.html', {'form': form, 'privacy_request': obj, 'can_erase': can_erase})

class BillingForm(forms.ModelForm):
    class Meta:
        model = Entitlement
        fields = ['plan', 'status', 'expires_at', 'child_quota', 'practitioner_quota', 'amount', 'currency', 'billing_reference']
        labels = {'plan': _('Plan name'), 'status': _('Status'), 'expires_at': _('Access until'), 'child_quota': _('Child profile quota'), 'practitioner_quota': _('Practitioner quota'), 'amount': _('Amount'), 'currency': _('Currency'), 'billing_reference': _('Billing reference')}

class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        fields = ['number', 'amount', 'currency', 'status', 'reference']
        labels = {'number': _('Invoice number'), 'amount': _('Amount'), 'currency': _('Currency'), 'status': _('Status'), 'reference': _('Payment reference')}

@login_required
@permission_required('core.manage_entitlements', raise_exception=True)
def billing(request, pk=None):
    if pk is None:
        return render(request, 'billing/index.html', {'organizations': Organization.objects.all().order_by('name')})
    org = get_object_or_404(Organization, pk=pk)
    entitlement, _created = Entitlement.objects.get_or_create(organization=org)
    form = BillingForm(request.POST or None, instance=entitlement)
    if request.method == 'POST' and form.is_valid():
        form.save()
        audit(request.user, 'entitlement.updated', entitlement, org)
        return redirect('billing_detail', pk=pk)
    return render(request, 'billing/detail.html', {'organization': org, 'form': form, 'invoices': org.invoice_set.all().order_by('-issued_at')})

@login_required
@permission_required('core.manage_entitlements', raise_exception=True)
def invoice_create(request, pk):
    org = get_object_or_404(Organization, pk=pk)
    form = InvoiceForm(request.POST or None, instance=Invoice(organization=org))
    if request.method == 'POST' and form.is_valid():
        invoice = form.save(commit=False)
        if invoice.status == 'paid':
            invoice.paid_at = timezone.now()
        invoice.save()
        audit(request.user, 'invoice.recorded', invoice, org)
        return redirect('billing_detail', pk=pk)
    return render(request, 'form.html', {'title': _('Record a manual invoice'), 'form': form, 'submit': _('Save')})

@login_required
@require_POST
def revoke_member_invitation(request, pk):
    member = manager(request)
    invite = get_object_or_404(Invitation, pk=pk, organization=member.organization, kind='clinician')
    invite.revoked = True
    invite.save()
    audit(request.user, 'invitation.revoked', invite, member.organization)
    return redirect('members')

@login_required
def notice(request):
    member = membership(request)
    org = member.organization if member else visible_children(request.user).first().organization if visible_children(request.user).exists() else None
    if request.method == 'POST' and org:
        from django.utils.translation import get_language
        obj, _created = NoticeAcknowledgement.objects.get_or_create(user=request.user, organization=org, version='2026-10-09', defaults={'language': get_language()})
        audit(request.user, 'notice.acknowledged', obj, org)
        messages.success(request, _('Information acknowledgement recorded.'))
        return redirect('dashboard')
    return render(request, 'privacy/notice.html', {'organization': org})

class OrganizationForm(forms.ModelForm):
    retention_days = forms.IntegerField(required=False, min_value=0, label=_('Retention period in days'), help_text=_('Choose this policy with your practice adviser before processing erasure.'))
    class Meta:
        model = Organization
        fields = ['name', 'country', 'retention_days']
        labels = {'name': _('Practice name'), 'country': _('Country code')}

@login_required
def organization_settings(request):
    member = manager(request)
    form = OrganizationForm(request.POST or None, instance=member.organization)
    if request.method == 'POST' and form.is_valid():
        org = form.save()
        audit(request.user, 'organization.settings_updated', org, org)
        return redirect('members')
    return render(request, 'form.html', {'title': _('Practice settings'), 'form': form, 'submit': _('Save')})
