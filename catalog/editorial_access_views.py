import hashlib
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from catalog.editorial_access import (
    accept_editorial_access_invitation, issue_editorial_access_invitation,
    revoke_editorial_capability, revoke_editorial_invitation,
)
from catalog.editorial_access_forms import EditorialAccessInvitationForm
from catalog.models import EditorialAccessInvitation, EditorialGrant
from core.forms import InviteSignupForm
from core.models import User

@login_required
@permission_required('core.manage_entitlements', raise_exception=True)
def manage_editorial_access(request):
    form = EditorialAccessInvitationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            invitation = issue_editorial_access_invitation(request.user, **form.cleaned_data)
            if invitation.delivery == 'failed':
                messages.warning(request, _('The invitation was recorded, but email delivery failed. Configure email or try again; no account was granted access.'))
            elif invitation.delivery == 'console':
                messages.info(request, _('Development only: the invitation link was written to the local mail console.'))
            else:
                messages.success(request, _('The invitation was handed to the mail service. Receipt has not been confirmed.'))
            return redirect('editorial_access_management')
        except ValidationError as error:
            form.add_error(None, error)
    grants = EditorialGrant.objects.filter(Q(edit=True) | Q(clinical_review=True) | Q(linguistic_review=True)).select_related('user', 'variety').order_by('variety__code', 'user__username')
    invitations = EditorialAccessInvitation.objects.filter(revoked=False).select_related('variety', 'created_by', 'accepted_by').order_by('-expires_at')[:100]
    return render(request, 'editorial_access_management.html', {
        'form': form, 'grants': grants, 'invitations': invitations,
    })

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

def accept_editorial_invite(request, token):
    token_digest = hashlib.sha256(token.encode()).hexdigest()
    invitation = EditorialAccessInvitation.objects.filter(token_hash=token_digest).select_related('variety').first()
    if not invitation or not invitation.available:
        return render(request, 'notice.html', {
            'title': _('Editorial invitation unavailable'),
            'body': _('This invitation may have expired, been revoked or already used. Ask the platform manager for a new invitation.'),
        }, status=410)
    existing_account = User.objects.filter(email__iexact=invitation.email).exists()
    form = InviteSignupForm(request.POST or None) if not request.user.is_authenticated and not existing_account else None
    if request.method == 'POST':
        if request.user.is_authenticated:
            try:
                accept_editorial_access_invitation(request.user, token)
                messages.success(request, _('Editorial access was activated for the invited spoken variety.'))
                return redirect('editorial_index')
            except ValidationError as error:
                messages.error(request, ' '.join(error.messages))
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
