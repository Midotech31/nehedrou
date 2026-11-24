"""Operator-only changes to exact-variety editorial publishing access."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django_otp.plugins.otp_totp.models import TOTPDevice

from catalog.integrity import invalidate_integrity
from catalog.models import EditorialGrant, Variety
from core.models import User
from core.services import audit
from qualification.models import digest_value


LIMITED_CAPABILITIES = ('edit', 'clinical_review', 'linguistic_review')


@transaction.atomic
def change_publishing_access(*, actor_username, account_username, variety_code, operation, expected_plan=None):
    """Preview or apply a publishing decision from the trusted operator process."""
    if operation not in ('grant', 'revoke'):
        raise ValidationError('Choose whether to grant or revoke publishing access.')
    applying = expected_plan is not None
    if not User.objects.filter(username=actor_username, is_active=True, is_superuser=True).exists():
        raise PermissionDenied('An existing active superuser must be named as the responsible operator.')

    varieties, accounts, grants = Variety.objects.all(), User.objects.all(), EditorialGrant.objects.all()
    if applying:
        # Match invitation acceptance: variety, then account, then scoped grant.
        varieties = varieties.select_for_update()
        accounts = accounts.select_for_update(no_key=True)
        grants = grants.select_for_update()
    variety = varieties.filter(code=variety_code).first()
    if not variety:
        raise ValidationError('Choose an existing spoken variety.')
    users = {user.username: user for user in accounts.filter(
        username__in=(actor_username, account_username)).order_by('pk')}
    actor = users.get(actor_username)
    account = users.get(account_username)
    if not actor or not actor.is_active or not actor.is_superuser:
        raise PermissionDenied('An existing active superuser must be named as the responsible operator.')
    if not account or account.is_superuser:
        raise ValidationError('Choose an existing account without global administrative authority.')
    if operation == 'grant':
        if not account.is_active:
            raise ValidationError('The publishing account must be active.')
        if not TOTPDevice.objects.filter(user=account, confirmed=True).exists():
            raise ValidationError('The publishing account must have a confirmed authenticator.')

    grant = grants.filter(user=account, variety=variety).first()
    limited = [key for key in LIMITED_CAPABILITIES if grant and getattr(grant, key)]
    enabled = bool(grant and grant.publish)
    requested = operation == 'grant'
    plan = {
        'operation': operation,
        'actor_id': str(actor.pk),
        'account_id': str(account.pk),
        'variety_id': str(variety.pk),
        'variety_code': variety.code,
        'publishing_enabled': enabled,
        'grant_id': str(grant.pk) if grant else None,
        'limited_capabilities': limited,
    }
    plan_sha = digest_value(plan)
    result = {'plan': plan, 'plan_sha256': plan_sha, 'changed': False}
    if not applying:
        return result
    if expected_plan != plan_sha:
        raise ValidationError('The publishing access plan changed. Preview it again before applying.')
    if enabled == requested:
        return result

    if grant is None:
        grant = EditorialGrant.objects.create(user=account, variety=variety, publish=True)
    elif requested or limited:
        grant.publish = requested
        grant.save(update_fields=['publish'])
    else:
        # A grant with every flag off would still expose the editorial workspace.
        grant.delete()
    action = 'catalog.publishing_access_granted' if requested else 'catalog.publishing_access_revoked'
    # Use the stable subject and scope rather than the transient grant row.
    scope_reference = f'{account.pk}:{variety.pk}'
    audit(actor, action, None, object_ref=scope_reference)
    invalidate_integrity()
    return {**result, 'changed': True, 'publishing_enabled': requested, 'audit_scope_ref': scope_reference}
