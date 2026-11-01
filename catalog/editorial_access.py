"""Restricted editorial invitations; no practice membership or clinical-record access."""
import hashlib
import uuid
from smtplib import SMTPException
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from catalog.models import EditorialAccessInvitation, EditorialGrant, Variety
from core.invitation_delivery import invitation_delivery_status
from core.models import User
from core.services import audit

ALLOWED_EDITORIAL_CAPABILITIES = {'edit', 'clinical_review', 'linguistic_review'}

def _require_manager(actor):
    if not actor.is_authenticated or not actor.is_active or not actor.has_perm('core.manage_entitlements'):
        raise PermissionDenied

def _validate_editorial_recipient(email, variety, capability):
    """Lock the spoken variety before checking or changing its limited grants."""
    variety = Variety.objects.select_for_update().filter(pk=variety.pk).first()
    if not variety:
        raise ValidationError(_('The spoken variety is unavailable.'))
    email = email.strip().lower()
    existing_user = User.objects.filter(email__iexact=email).first()
    if existing_user and not existing_user.is_active:
        raise ValidationError(_('This email belongs to an inactive account. Contact the platform manager before inviting it.'))
    if existing_user and EditorialGrant.objects.filter(user=existing_user, variety=variety, publish=True).exists():
        raise ValidationError(_('This account already has publishing access for this spoken variety. Review its existing access directly instead of sending a limited-role invitation.'))
    if existing_user and EditorialGrant.objects.filter(user=existing_user, variety=variety, **{capability: True}).exists():
        raise ValidationError(_('This account already has this editorial access.'))
    return variety, email


def _manual_creation_replay(invitation, actor, email, variety, capability):
    if (invitation.created_by_id != actor.pk or invitation.email != email
            or invitation.variety_id != variety.pk or invitation.capability != capability
            or invitation.delivery != 'manual'):
        raise ValidationError(_('This creation request has already been used. Open a new form to create another invitation.'))
    # Tokens cannot be reconstructed; a replay must never rotate or reveal one.
    return invitation, None


def issue_manual_editorial_access_invitation(actor, email, variety, capability, creation_id):
    """Return a raw token only to the first explicit personal-handoff request.

    The invitation UUID identifies this creation act. The insert happens before
    revocations so a concurrent UUID collision rolls the losing transaction back
    without invalidating another invitation. No raw token is stored or audited.
    """
    _require_manager(actor)
    if capability not in ALLOWED_EDITORIAL_CAPABILITIES:
        raise ValidationError(_('Choose a limited editorial role.'))
    try:
        creation_id = uuid.UUID(str(creation_id))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError(_('Open a new form to create a personal handoff link.'))
    email = email.strip().lower()
    try:
        with transaction.atomic():
            # The same variety lock serializes replacement of an exact triplet.
            locked_variety = Variety.objects.select_for_update().filter(pk=variety.pk).first()
            if not locked_variety:
                raise ValidationError(_('The spoken variety is unavailable.'))
            existing = EditorialAccessInvitation.objects.select_for_update().filter(pk=creation_id).first()
            if existing:
                return _manual_creation_replay(existing, actor, email, locked_variety, capability)
            locked_variety, email = _validate_editorial_recipient(email, locked_variety, capability)
            invitation, token = EditorialAccessInvitation.issue(
                email, locked_variety, capability, actor,
                invitation_id=creation_id, delivery='manual')
            prior = EditorialAccessInvitation.objects.select_for_update().filter(
                email__iexact=email, variety=locked_variety, capability=capability,
                revoked=False, used_at__isnull=True, expires_at__gt=timezone.now()).exclude(pk=invitation.pk)
            for previous in prior:
                previous.revoked = True
                previous.save(update_fields=['revoked'])
                audit(actor, 'catalog.editorial_invitation_revoked', previous)
            audit(actor, 'catalog.editorial_invitation_created', invitation)
            audit(actor, 'catalog.editorial_invitation_manual_created', invitation)
            return invitation, token
    except (IntegrityError, ValidationError):
        # CheckedModel.full_clean may also detect the winner's committed UUID.
        # Read only after the failed atomic block has rolled back completely.
        existing = EditorialAccessInvitation.objects.filter(pk=creation_id).first()
        if existing is None:
            raise
        return _manual_creation_replay(existing, actor, email, variety, capability)


def issue_editorial_access_invitation(actor, email, variety, capability):
    _require_manager(actor)
    if capability not in ALLOWED_EDITORIAL_CAPABILITIES:
        raise ValidationError(_('Choose a limited editorial role.'))
    with transaction.atomic():
        variety, email = _validate_editorial_recipient(email, variety, capability)
        # A replacement invalidates every unused link for the same exact invitation.
        prior = EditorialAccessInvitation.objects.select_for_update().filter(email__iexact=email, variety=variety, capability=capability, revoked=False, used_at__isnull=True).exclude(expires_at__lte=timezone.now())
        for previous in prior:
            previous.revoked = True
            previous.save(update_fields=['revoked'])
            audit(actor, 'catalog.editorial_invitation_revoked', previous)
        invitation, token = EditorialAccessInvitation.issue(email, variety, capability, actor)
        audit(actor, 'catalog.editorial_invitation_created', invitation)
    url = settings.PUBLIC_ORIGIN.rstrip('/') + reverse('accept_editorial_invite', args=[token])
    status = invitation_delivery_status()
    delivery = 'failed'
    if status['state'] != 'unavailable':
        try:
            sent = send_mail(_('Nehedrou editorial access invitation'),
                _('You have been invited to a limited Nehedrou editorial role for %(variety)s. This link expires in seven days. It grants only the selected editorial capability and does not add practice-record access; any permissions already on your account remain unchanged:') % {'variety': variety.display_label} + '\n' + url,
                settings.DEFAULT_FROM_EMAIL, [invitation.email])
            if sent:
                delivery = 'console' if status['state'] == 'local_console' else 'sent'
        except (OSError, SMTPException):
            delivery = 'failed'
    with transaction.atomic():
        invitation.delivery = delivery
        invitation.save(update_fields=['delivery'])
        audit(actor, 'catalog.editorial_invitation_delivery_' + delivery, invitation)
    return invitation

@transaction.atomic
def accept_editorial_access_invitation(actor, raw_token):
    if not actor.is_authenticated:
        raise PermissionDenied
    digest = hashlib.sha256(raw_token.encode()).hexdigest()
    invitation = EditorialAccessInvitation.objects.select_for_update().filter(token_hash=digest).first()
    if not invitation or not invitation.available:
        raise ValidationError(_('This editorial invitation has expired or is no longer available.'))
    user = User.objects.select_for_update().filter(pk=actor.pk, is_active=True).first()
    if not user or user.email.strip().lower() != invitation.email.strip().lower():
        raise ValidationError(_('Sign in with the email address to which this invitation was sent.'))
    grant, created = EditorialGrant.objects.select_for_update().get_or_create(user=user, variety=invitation.variety)
    if grant.publish:
        raise ValidationError(_('This account already has publishing access for this spoken variety. Ask the platform manager to review its existing access.'))
    if getattr(grant, invitation.capability):
        raise ValidationError(_('This account already has this editorial access.'))
    setattr(grant, invitation.capability, True)
    grant.save()
    invitation.used_at = timezone.now()
    invitation.accepted_by = user
    invitation.save(update_fields=['used_at', 'accepted_by'])
    audit(user, 'catalog.editorial_invitation_accepted', invitation)
    return grant

@transaction.atomic
def revoke_editorial_invitation(actor, invitation_id):
    _require_manager(actor)
    invitation = EditorialAccessInvitation.objects.select_for_update().filter(pk=invitation_id).first()
    if not invitation:
        raise ValidationError(_('This editorial invitation is unavailable.'))
    if invitation.available:
        invitation.revoked = True
        invitation.save(update_fields=['revoked'])
        audit(actor, 'catalog.editorial_invitation_revoked', invitation)
    return invitation

@transaction.atomic
def revoke_editorial_capability(actor, grant_id, capability):
    _require_manager(actor)
    if capability not in ALLOWED_EDITORIAL_CAPABILITIES:
        raise ValidationError(_('Choose a limited editorial role.'))
    grant = EditorialGrant.objects.select_for_update().filter(pk=grant_id).first()
    if not grant or not getattr(grant, capability):
        raise ValidationError(_('This editorial access is unavailable.'))
    setattr(grant, capability, False)
    if not (grant.edit or grant.clinical_review or grant.linguistic_review or grant.publish):
        audit(actor, 'catalog.editorial_access_revoked', grant)
        grant.delete()
        return grant
    grant.save()
    audit(actor, 'catalog.editorial_access_revoked', grant)
    return grant
