"""Manual, practice-scoped access review requests without a mail or payment flow."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from .access import manager
from .form_scope import ERROR as PRACTICE_SCOPE_ERROR, practice_form_scope
from .models import Entitlement, Membership, Organization, PracticeAccessRequest, User
from .services import audit


def _scope(request, practice):
    last_acknowledged = PracticeAccessRequest.objects.filter(
        organization=practice, acknowledged_at__isnull=False,
    ).order_by('-pk').values_list('pk', flat=True).first()
    return practice_form_scope(request, practice, f'practice_access_request:{last_acknowledged or 0}')


def owner_access_request(request, practice, access_usable):
    if settings.DEMO_MODE or request.practice_selection_required:
        return {}
    latest = PracticeAccessRequest.objects.filter(organization=practice).order_by('-pk').first()
    if not access_usable and (latest is None or latest.acknowledged_at):
        scope, _valid = _scope(request, practice)
    else:
        scope = ''
    return {'latest_access_request': latest, 'access_request_scope': scope}


def pending_access_requests():
    if settings.DEMO_MODE:
        return PracticeAccessRequest.objects.none()
    return PracticeAccessRequest.objects.filter(acknowledged_at__isnull=True).select_related('organization').order_by('pk')


def _active_account(user):
    return get_object_or_404(User.objects.select_for_update(no_key=True), pk=user.pk, is_active=True)


@never_cache
@login_required
@require_POST
def request_access(request):
    if settings.DEMO_MODE or not request.session.get('organization'):
        raise Http404
    member = manager(request)
    with transaction.atomic():
        practice = get_object_or_404(Organization.objects.select_for_update(), pk=member.organization_id)
        actor = _active_account(request.user)
        get_object_or_404(Membership, user=actor, organization=practice, role='owner', active=True)
        _token, matches = _scope(request, practice)
        if not matches:
            return render(request, 'notice.html', {
                'title': _('Request an access review'), 'body': PRACTICE_SCOPE_ERROR,
            }, status=409)
        entitlement = Entitlement.objects.filter(organization=practice).first()
        if entitlement is not None and entitlement.usable:
            return redirect('subscription')
        access_request, created = PracticeAccessRequest.objects.get_or_create(
            organization=practice, acknowledged_at=None, defaults={'requested_by': actor},
        )
        if created:
            audit(actor, 'entitlement.review_requested', access_request, practice)
    return redirect('subscription')


@never_cache
@login_required
@permission_required('core.manage_entitlements', raise_exception=True)
@require_POST
def acknowledge_access(request, pk):
    if settings.DEMO_MODE:
        raise Http404
    current = get_object_or_404(PracticeAccessRequest, pk=pk)
    with transaction.atomic():
        practice = get_object_or_404(Organization.objects.select_for_update(), pk=current.organization_id)
        actor = _active_account(request.user)
        if not actor.has_perm('core.manage_entitlements'):
            raise Http404
        current = get_object_or_404(PracticeAccessRequest, pk=pk, organization=practice)
        if current.acknowledged_at is None:
            current.acknowledged_at = timezone.now()
            current.acknowledged_by = actor
            current.save(update_fields=['acknowledged_at', 'acknowledged_by'])
            audit(actor, 'entitlement.review_acknowledged', current, practice)
    messages.success(request, _('The cabinet access request is acknowledged.'))
    return redirect('billing_index')
