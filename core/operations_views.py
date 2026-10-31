"""Private runtime diagnostics for the existing platform-management role."""
import json
from io import StringIO
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.db import transaction
from django.core.management import call_command
from django.core.management.base import CommandError
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods
from core.ops_readiness import operations_report
from core.forms import ProcessingActivityForm
from core.models import ProcessingActivity
from core.technical_storage_probe import PROBE_KEY, PROBE_SHA256

CONFIGURATION_LABELS = {
    'debug_disabled': _('Debug disabled'),
    'postgresql_configured': _('PostgreSQL configured'),
    'ephemeral_database_disabled': _('Temporary database disabled'),
    'durability_declared': _('Media durability declared by the operator'),
    'private_remote_media_configured': _('Private remote media configured'),
    'https_canonical_origin': _('Canonical HTTPS origin configured'),
}
SMTP_LABELS = {
    'smtp_backend': _('SMTP mail backend selected'),
    'host_present': _('Mail server configured'),
    'port_valid': _('Mail port valid'),
    'one_transport_security_mode': _('One encrypted mail transport selected'),
    'bounded_timeout': _('Mail timeout bounded'),
    'credentials_present': _('Mail credentials configured'),
    'sender_address': _('Sender address valid'),
    'sender_not_reserved': _('Sender address uses a non-example domain'),
}

EMAIL_LABELS = {
    **SMTP_LABELS,
    'resend_backend': _('Resend HTTPS mail backend selected'),
    'https_email_enabled': _('HTTPS email explicitly enabled'),
    'api_key_present': _('Email API credential configured'),
    'connect_timeout_bounded': _('HTTPS connection timeout bounded'),
    'read_timeout_bounded': _('HTTPS response timeout bounded'),
    'delivery_backend_selected': _('Supported email delivery backend selected'),
}

@login_required
@permission_required('core.manage_entitlements', raise_exception=True)
@require_http_methods(['GET', 'HEAD', 'POST'])
def diagnostics(request):
    # No arbitrary storage keys, recipients, URLs, commands or destinations accepted.
    action = request.POST.get('action') if request.method == 'POST' else None
    if request.method == 'POST' and action not in ('database', 'storage'):
        return HttpResponseBadRequest()
    if action == 'storage':
        if set(request.POST) - {'action', 'csrfmiddlewaretoken'}:
            return HttpResponseBadRequest()
        # A fixed technical sentinel can never select a patient/evidence object.
        report = operations_report(storage_object=PROBE_KEY, storage_expected_sha256=PROBE_SHA256)
    else:
        report = operations_report(probe_database=action == 'database')
    report['execution']['delivery'] = 'authenticated_private_web_view'
    if request.GET.get('format') == 'json':
        response = HttpResponse(json.dumps(report, ensure_ascii=True, indent=2), content_type='application/json')
        response['Content-Disposition'] = 'attachment; filename="nehedrou-runtime-diagnostics.json"'
    else:
        response = render(request, 'operations.html', {
            'page_title': _('Hosting diagnostics'), 'nav_section': 'operations', 'report': report,
            'configuration_rows': [(CONFIGURATION_LABELS[key], value) for key, value in report['configuration'].items()],
            'smtp_rows': [(SMTP_LABELS[key], value) for key, value in report['smtp']['checks'].items()],
            'email_rows': [(EMAIL_LABELS[key], value) for key, value in report['email']['checks'].items()],
        })
    response['Cache-Control'] = 'private, no-store'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response

@login_required
@permission_required('core.manage_entitlements', raise_exception=True)
@require_http_methods(['GET', 'HEAD'])
def launch_readiness_report(request):
    """Run the same non-clinical launch gates against this deployed database."""
    output = StringIO()
    try:
        call_command('check_readiness', json=True, stdout=output)
        report = json.loads(output.getvalue())
        status = 200
    except CommandError:
        # A malformed or incomplete content-variety configuration must block
        # publication without turning a private diagnostic into a server error.
        report = {
            'report_available': False,
            'technical_gates_passed': False,
            'checks': {},
            'scope': 'Technical report only; this route never certifies clinical release or commercial approval.',
            'configuration_error': 'Readiness report could not run because the offered spoken-variety configuration is invalid or incomplete.',
        }
        status = 503
    response = HttpResponse(json.dumps(report, ensure_ascii=True, indent=2), content_type='application/json', status=status)
    response['Content-Disposition'] = 'attachment; filename="nehdrou-launch-readiness.json"'
    response['Cache-Control'] = 'private, no-store'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response


@login_required
@permission_required('core.manage_processing_register', raise_exception=True)
@require_http_methods(['GET', 'HEAD', 'POST'])
def processing_register(request, pk=None):
    instance = get_object_or_404(ProcessingActivity, pk=pk) if pk else None
    form = ProcessingActivityForm(request.POST if request.method == 'POST' else None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        if instance is None:
            obj.created_by = request.user
            action = 'privacy.register_activity_created'
        else:
            action = 'privacy.register_activity_updated'
        obj.updated_by = request.user
        with transaction.atomic():
            obj.save()
            from core.models import ProcessingActivityRevision
            from core.services import audit
            snapshot_fields = ('organization_id', 'register_capacity', 'name', 'controller_name', 'controller_contact',
                               'data_protection_contact', 'purposes', 'legal_basis', 'data_subject_categories',
                               'personal_data_categories', 'recipient_categories', 'international_transfers',
                               'retention_periods', 'security_measures', 'operations', 'active')
            snapshot = {field: getattr(obj, field) for field in snapshot_fields}
            revision_number = (ProcessingActivityRevision.objects.filter(activity=obj).order_by('-revision')
                              .values_list('revision', flat=True).first() or 0) + 1
            ProcessingActivityRevision.objects.create(activity=obj, revision=revision_number, snapshot=snapshot,
                                                       changed_by=request.user)
            audit(request.user, action, obj, obj.organization)
        messages.success(request, _('Register entry saved. Have its accuracy and legal basis reviewed by the responsible people.'))
        return redirect('processing_register')
    entries = list(ProcessingActivity.objects.select_related('organization').prefetch_related('revisions__changed_by').order_by('organization__name', 'name'))
    if request.method in ('GET', 'HEAD'):
        from core.services import audit
        consulted = [instance] if instance is not None else entries
        for entry in consulted:
            audit(request.user, 'privacy.register_activity_consulted', entry, entry.organization)
    if request.method == 'GET' and request.GET.get('format') == 'json':
        from django.http import JsonResponse
        from django.utils import timezone
        payload = {
            'schema_version': 1,
            'generated_at': timezone.now().isoformat(),
            'entries': [{
                'id': str(entry.pk), 'organization': entry.organization.name if entry.organization_id else None,
                'register_capacity': entry.register_capacity, 'name': entry.name, 'active': entry.active,
                'controller_name': entry.controller_name, 'controller_contact': entry.controller_contact,
                'data_protection_contact': entry.data_protection_contact, 'purposes': entry.purposes,
                'legal_basis': entry.legal_basis, 'data_subject_categories': entry.data_subject_categories,
                'personal_data_categories': entry.personal_data_categories, 'recipient_categories': entry.recipient_categories,
                'international_transfers': entry.international_transfers, 'retention_periods': entry.retention_periods,
                'security_measures': entry.security_measures, 'operations': entry.operations,
                'created_at': entry.created_at.isoformat(), 'updated_at': entry.updated_at.isoformat(),
                'revisions': [{
                    'revision': revision.revision, 'changed_by_id': revision.changed_by_id,
                    'created_at': revision.created_at.isoformat(), 'snapshot': revision.snapshot,
                } for revision in entry.revisions.select_related('changed_by').all()],
            } for entry in entries],
        }
        response = JsonResponse(payload, json_dumps_params={'ensure_ascii': False, 'indent': 2})
        response['Content-Disposition'] = 'attachment; filename="nehdrou-processing-register.json"'
        response['Cache-Control'] = 'private, no-store'
        response['X-Robots-Tag'] = 'noindex, nofollow'
        return response
    response = render(request, 'processing_register.html', {
        'form': form,
        'entries': entries,
        'editing': instance is not None,
        'title': _('Processing register'),
        'submit': _('Save register entry'),
        'note': _('This operator record helps document processing. It is not legal advice or a compliance certificate; enter verified details and obtain qualified review.'),
    })
    response['Cache-Control'] = 'private, no-store'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response
