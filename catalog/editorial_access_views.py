import hashlib
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import patch_cache_control
from django.utils.translation import gettext as _
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_POST, require_http_methods
from catalog.editorial_access import (
    accept_editorial_access_invitation, accept_editorial_access_invitation_digest, issue_editorial_access_invitation,
    issue_manual_editorial_access_invitation,
    revoke_editorial_capability, revoke_editorial_invitation,
)
from catalog.editorial_access_forms import EditorialAccessInvitationForm
from catalog.models import EditorialAccessInvitation, EditorialGrant
from core.forms import InviteSignupForm
from core.invitation_delivery import invitation_delivery_status
from core.invitation_mfa import SESSION_KEY as MFA_INVITATION_KEY, invitation_digest
from core.models import User

@login_required
@permission_required('core.manage_entitlements', raise_exception=True)
def manage_editorial_access(request):
    delivery = invitation_delivery_status()
    initial = {'delivery_method': 'manual'} if request.method == 'GET' and delivery['known_unavailable'] else None
    form = EditorialAccessInvitationForm(request.POST or None, initial=initial)
    manual_invitation, manual_link, manual_already_created = None, '', False
    if request.method == 'POST' and form.is_valid():
        try:
            data = form.cleaned_data.copy()
            delivery_method = data.pop('delivery_method')
            creation_id = data.pop('creation_id', None)
            if delivery_method == 'manual':
                manual_invitation, token = issue_manual_editorial_access_invitation(
                    request.user, **data, creation_id=creation_id)
                manual_already_created = token is None
                if token:
                    manual_link = settings.PUBLIC_ORIGIN.rstrip('/') + reverse('accept_editorial_invite', args=[token])
                # This blank form makes another creation a separate, explicit act.
                form = EditorialAccessInvitationForm(initial={'delivery_method': 'manual'})
            else:
                invitation = issue_editorial_access_invitation(request.user, **data)
                if invitation.revoked:
                    messages.warning(request, _('The editorial invitation was revoked.'))
                elif invitation.delivery == 'failed':
                    messages.warning(request, _('The invitation was recorded, but email delivery failed. Configure email or try again; no account was granted access.'))
                elif invitation.delivery == 'console':
                    messages.info(request, _('Development only: the invitation link was written to the local mail console.'))
                else:
                    messages.success(request, _('The invitation was handed to the mail service. Receipt has not been confirmed.'))
                return redirect('editorial_access_management')
        except ValidationError as error:
            form.add_error(None, error)
    grants = EditorialGrant.objects.filter(Q(edit=True) | Q(clinical_review=True) | Q(linguistic_review=True) | Q(publish=True)).select_related('user', 'variety').order_by('variety__code', 'user__username')
    invitations = EditorialAccessInvitation.objects.filter(revoked=False).select_related('variety', 'created_by', 'accepted_by').order_by('-expires_at')[:100]
    response = render(request, 'editorial_access_management.html', {
        'form': form, 'grants': grants, 'invitations': invitations,
        'invitation_delivery': delivery,
        'manual_invitation': manual_invitation, 'manual_link': manual_link,
        'manual_already_created': manual_already_created,
    })
    if request.method == 'POST' and request.POST.get('delivery_method') == 'manual':
        patch_cache_control(response, private=True, no_store=True)
        response.headers['Referrer-Policy'] = 'no-referrer'
    return response

@login_required
@permission_required('core.manage_entitlements', raise_exception=True)
@require_POST
def revoke_editorial_invitation_view(request, pk):
    try:
        revoke_editorial_invitation(request.user, pk)
        messages.success(request, _('The editorial invitation was revoked.'))
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    return redirect('editorial_access_management')

@login_required
@permission_required('core.manage_entitlements', raise_exception=True)
@require_POST
def revoke_editorial_capability_view(request, pk, capability):
    try:
        revoke_editorial_capability(request.user, pk, capability)
        messages.success(request, _('The selected editorial permission was revoked.'))
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    return redirect('editorial_access_management')

def _editorial_invitation_unavailable(request):
    return render(request, 'notice.html', {
        'title': _('Editorial invitation unavailable'),
        'body': _('This invitation may have expired, been revoked or already used. Ask the platform manager for a new invitation.'),
    }, status=410)


def _accept_signed_in_editorial_invitation(request, invitation):
    try:
        accept_editorial_access_invitation_digest(request.user, invitation.token_hash)
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
        return None
    messages.success(request, _('Editorial access was activated for the invited spoken variety.'))
    return redirect('editorial_index')


@never_cache
@login_required
@require_http_methods(['GET', 'HEAD', 'POST'])
def resume_editorial_invitation(request):
    if not request.user.is_verified():
        raise Http404
    digest = invitation_digest(request, kind='editorial')
    invitation = EditorialAccessInvitation.objects.filter(
        token_hash=digest,
    ).select_related('variety').first() if digest else None
    if (not invitation or not invitation.available
            or request.user.email.strip().lower() != invitation.email.strip().lower()):
        if digest:
            request.session.pop(MFA_INVITATION_KEY, None)
        return _editorial_invitation_unavailable(request)
    if request.method == 'POST':
        response = _accept_signed_in_editorial_invitation(request, invitation)
        if response is not None:
            request.session.pop(MFA_INVITATION_KEY, None)
            return response
    return render(request, 'editorial_invite_accept.html', {
        'invitation': invitation, 'existing_account': True, 'email_matches': True,
    })


@sensitive_variables('token')
def accept_editorial_invite(request, token):
    token_digest = hashlib.sha256(token.encode()).hexdigest()
    invitation = EditorialAccessInvitation.objects.filter(token_hash=token_digest).select_related('variety').first()
    if not invitation or not invitation.available:
        return _editorial_invitation_unavailable(request)
    existing_account = User.objects.filter(email__iexact=invitation.email).exists()
    form = InviteSignupForm(request.POST or None) if not request.user.is_authenticated and not existing_account else None
    if request.method == 'POST':
        if request.user.is_authenticated:
            response = _accept_signed_in_editorial_invitation(request, invitation)
            if response is not None:
                return response
        elif form and form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save(commit=False)
                    user.email = invitation.email.lower()
                    user.save()
                    accept_editorial_access_invitation(user, token)
                login(request, user)
                messages.success(request, _('Editorial access was activated for the invited spoken variety.'))
                return redirect('editorial_index')
            except ValidationError as error:
                form.add_error(None, error)
            except IntegrityError:
                form.add_error(None, _('An account already exists for this email. Sign in with the invited address to accept the invitation.'))
    return render(request, 'editorial_invite_accept.html', {
        'form': form, 'invitation': invitation, 'existing_account': existing_account,
        'email_matches': request.user.is_authenticated and request.user.email.strip().lower() == invitation.email.strip().lower(),
    })
