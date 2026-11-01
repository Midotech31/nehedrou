import hashlib
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
from django.views.decorators.http import require_POST, require_http_methods
from care.models import Child, Program, PracticeSession, ProgramItem, Observation, FamilyLink
from catalog.models import Activity
from .access import clinician_child, professional_children, manager, visible_children, membership
from .form_scope import practice_form_scope, ERROR as PRACTICE_SCOPE_ERROR
from .forms import ChildForm, ProgramForm, ReassignForm, PrivacyDecisionForm
from .models import Organization, PrivacyRequest, Invitation, Entitlement, Invoice, NoticeAcknowledgement
from .access import CURRENT_NOTICE_VERSION, notice_gate
from .services import audit, log_child_access, check_entitlement, create_program, lock_clinical_child, accept_invitation

@login_required
def child_edit(request, pk):
    child = clinician_child(request.user, pk)
    if request.method == 'GET':
        log_child_access(request.user, child, resource='child_profile_edit', purpose_code='care_delivery')
    form = ChildForm(request.POST or None, instance=child)
    if request.method == 'POST' and form.is_valid():
        gated = notice_gate(request, child.organization)
        if gated:
            return gated
        try:
            with transaction.atomic():
                locked = lock_clinical_child(request.user, child)
                chosen = form.cleaned_data['varieties']
                active_varieties = locked.programs.filter(state='active').values_list('variety_id', flat=True)
                if any(pk not in chosen.values_list('pk', flat=True) for pk in active_varieties):
                    raise ValidationError(_('Keep the varieties of active programs or complete those programs first.'))
                from followup.models import ClinicalGoal
                if ClinicalGoal.objects.filter(child=locked, active=True).exclude(variety__in=chosen).exists():
                    raise ValidationError(_('Keep the varieties of active clinical goals or close those goals first.'))
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
    gated = notice_gate(request, child.organization)
    if gated:
        return gated
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
        gated = notice_gate(request, child.organization)
        if gated:
            return gated
    if request.method == 'POST' and form.is_valid():
        try:
            from .services import transfer_child
            transfer_child(request.user, child, form.cleaned_data['responsible'])
            return redirect('children')
        except ValidationError as error:
            form.add_error(None, error)
    return render(request, 'form.html', {'title': _('Transfer professional responsibility'), 'form': form, 'submit': _('Transfer')})

@login_required
def program_replace(request, pk):
    program = get_object_or_404(Program, pk=pk, child__in=professional_children(request.user))
    form = ProgramForm(request.POST or None, child=program.child, initial={'title': program.title, 'variety': program.variety, 'activities': list(program.items.values_list('activity_id', flat=True)), 'guidance': program.guidance, 'schedule': program.schedule, 'goal': program.goal, **{field: getattr(program, field) for field in ['practice_start', 'practice_end', 'practice_days', 'practice_minutes']}, 'activity_order': ','.join(str(pk) for pk in program.items.values_list('activity_id', flat=True))})
    preview = None
    if request.method == 'POST' and form.is_valid():
        if request.POST.get('action') != 'preview':
            gated = notice_gate(request, program.organization)
            if gated:
                return gated
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
    from followup.services import retention_date
    followup_date = retention_date(child)
    if followup_date: dates.append(followup_date)
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

    def clean(self):
        data = super().clean()
        # Creation may already record an externally paid invoice. Bind its date
        # before ModelForm runs the model's status/date consistency validation.
        self.instance.paid_at = timezone.now() if data.get('status') == 'paid' else None
        return data

@login_required
@permission_required('core.manage_entitlements', raise_exception=True)
@require_http_methods(['GET', 'POST'])
def billing(request, pk=None):
    if pk is None:
        return render(request, 'billing/index.html', {'organizations': Organization.objects.all().order_by('name')})
    org = get_object_or_404(Organization, pk=pk)
    if request.method == 'POST':
        # Lock the parent even when no entitlement exists: concurrent first
        # saves must share one lock, not race to create a OneToOne record.
        with transaction.atomic():
            org = get_object_or_404(Organization.objects.select_for_update(), pk=pk)
            entitlement = Entitlement.objects.filter(organization=org).first()
            created = entitlement is None
            form = BillingForm(request.POST, instance=entitlement or Entitlement(organization=org))
            if form.is_valid():
                entitlement = form.save()
                audit(request.user, 'entitlement.created' if created else 'entitlement.updated', entitlement, org)
                return redirect('billing_detail', pk=pk)
    else:
        # Display defaults on an unsaved instance. Visiting this page must not
        # grant access, create billing data, or alter existing rights.
        entitlement = Entitlement.objects.filter(organization=org).first()
        form = BillingForm(instance=entitlement or Entitlement(organization=org))
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

def pending_notice_invitation(request):
    token = request.session.get('pending_notice_invitation_token', '')
    if not token:
        return None
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    invitation = Invitation.objects.filter(token_hash=token_hash, email__iexact=request.user.email).select_related('organization').first()
    if not invitation or not invitation.available:
        request.session.pop('pending_notice_invitation_token', None)
        return None
    return invitation


@login_required
def notice(request):
    pending = pending_notice_invitation(request)
    member = membership(request)
    linked = visible_children(request.user).select_related('organization').first()
    org = pending.organization if pending else member.organization if member else linked.organization if linked else None
    scope, scope_valid = practice_form_scope(request, org, 'notice_acknowledgement')
    if request.method == 'POST' and scope_valid and org:
        try:
            with transaction.atomic():
                from django.utils.translation import get_language
                obj, _created = NoticeAcknowledgement.objects.get_or_create(user=request.user, organization=org, version=CURRENT_NOTICE_VERSION, defaults={'language': get_language()})
                audit(request.user, 'notice.acknowledged', obj, org)
                if pending:
                    accept_invitation(request.user, request.session['pending_notice_invitation_token'])
            if pending:
                request.session.pop('pending_notice_invitation_token', None)
                request.session['workspace'] = 'family' if pending.kind == 'family' else 'professional'
                if pending.kind == 'clinician':
                    request.session['organization'] = str(pending.organization_id)
            messages.success(request, _('Information acknowledgement recorded.'))
            return redirect('dashboard')
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
    return render(request, 'privacy/notice.html', {'organization': org, 'practice_scope': scope, 'scope_error': PRACTICE_SCOPE_ERROR if not scope_valid else ''}, status=200 if scope_valid else 409)

class OrganizationForm(forms.ModelForm):
    retention_days = forms.IntegerField(required=False, min_value=0, label=_('Retention period in days'), help_text=_('Choose this policy with your practice adviser before processing erasure.'))
    class Meta:
        model = Organization
        fields = ['name', 'country', 'retention_days']
        labels = {'name': _('Practice name'), 'country': _('Country code')}

@login_required
def organization_settings(request):
    member = manager(request)
    form = OrganizationForm(request.POST if request.method == 'POST' else None, instance=member.organization)
    scope, scope_valid = practice_form_scope(request, member.organization, 'organization_settings')
    if not scope_valid:
        form.add_error(None, PRACTICE_SCOPE_ERROR)
    if request.method == 'POST' and scope_valid and form.is_valid():
        org = form.save()
        audit(request.user, 'organization.settings_updated', org, org)
        return redirect('members')
    return render(request, 'form.html', {'title': _('Practice settings'), 'form': form, 'submit': _('Save'), 'practice_scope': scope}, status=200 if scope_valid else 409)
