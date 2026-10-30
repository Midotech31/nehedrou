"""Private runtime diagnostics for the existing platform-management role."""
import json
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_http_methods
from core.ops_readiness import operations_report

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

@login_required
@permission_required('core.manage_entitlements', raise_exception=True)
@require_http_methods(['GET', 'HEAD', 'POST'])
def diagnostics(request):
    # No arbitrary storage keys, recipients, URLs, commands or destinations accepted.
    probe = request.method == 'POST'
    if probe and request.POST.get('action') != 'database':
        return HttpResponseBadRequest()
    report = operations_report(probe_database=probe)
    report['execution']['delivery'] = 'authenticated_private_web_view'
    if request.GET.get('format') == 'json':
        response = HttpResponse(json.dumps(report, ensure_ascii=True, indent=2), content_type='application/json')
        response['Content-Disposition'] = 'attachment; filename="nehedrou-runtime-diagnostics.json"'
    else:
        response = render(request, 'operations.html', {
            'page_title': _('Hosting diagnostics'), 'nav_section': 'operations', 'report': report,
            'configuration_rows': [(CONFIGURATION_LABELS[key], value) for key, value in report['configuration'].items()],
            'smtp_rows': [(SMTP_LABELS[key], value) for key, value in report['smtp']['checks'].items()],
        })
    response['Cache-Control'] = 'private, no-store'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response
