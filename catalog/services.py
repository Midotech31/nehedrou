import uuid
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.translation import gettext as _
from core.services import audit
from .models import Activity, EditorialGrant, Review, Variety

def allowed(user, variety, capability):
    if user.is_superuser:
        return True
    from .integrity import request_value
    grant = request_value('grants', (user.pk, variety.pk), lambda: EditorialGrant.objects.filter(user=user, variety=variety).first())
    return bool(grant and getattr(grant, capability, False))


def require_review_snapshot(content, expected_digest):
    """Call after locking the content, before recording a human review."""
    if expected_digest != content.fingerprint():
        raise ValidationError(
            _('This content changed. Reload this page and read the current version before submitting a review.'),
            code='review_snapshot_changed')

@transaction.atomic
def transition(actor, activity_id, target):
    activity = Activity.objects.select_for_update().get(pk=activity_id)
    from .integrity import invalidate_integrity
    invalidate_integrity()
    capability = 'publish' if target in ['published', 'withdrawn', 'approved'] else 'edit'
    if not allowed(actor, activity.variety, capability):
        raise PermissionDenied
    transitions = {'draft': ['review'], 'review': ['draft', 'approved'], 'approved': ['draft', 'published'], 'published': ['withdrawn'], 'withdrawn': []}
    if target not in transitions[activity.state]:
        raise ValidationError(_('This editorial transition is not allowed.'))
    if target == 'approved' and not activity.is_demo:
        if not activity.has_current_reviews():
            raise ValidationError(_('Clinical and linguistic reviews are required.'))
    if target == 'review' and not activity.is_demo:
        from .readiness import snapshot_media
        activity.media_manifest = snapshot_media(activity)
    activity.state = target
    activity.save()
    audit(actor, 'catalog.' + target, activity)
    return activity

@transaction.atomic
def clone_version(actor, source):
    # Lock the stable variety before the series, also when different versions are cloned.
    Variety.objects.select_for_update().get(pk=source.variety_id)
    source = Activity.objects.select_for_update().get(pk=source.pk)
    if not allowed(actor, source.variety, 'edit'):
        raise PermissionDenied
    values = {f.attname: getattr(source, f.attname) for f in source._meta.concrete_fields if f.name not in ['id', 'state', 'created_at', 'version']}
    latest = Activity.objects.filter(series=source.series).order_by('-version').first()
    values.update(version=latest.version + 1, state='draft')
    activity = Activity.objects.create(**values)
    audit(actor, 'catalog.version_created', activity)
    return activity

@transaction.atomic
def review_version(actor, activity, kind, approved, note, *, expected_digest):
    activity = Activity.objects.select_for_update().get(pk=activity.pk)
    from .integrity import invalidate_integrity
    invalidate_integrity()
    if kind not in ['clinical', 'linguistic']:
        raise PermissionDenied
    capability = 'clinical_review' if kind == 'clinical' else 'linguistic_review'
    if not allowed(actor, activity.variety, capability):
        raise PermissionDenied
    require_review_snapshot(activity, expected_digest)
    review = Review.objects.create(activity=activity, reviewer=actor, kind=kind, approved=approved, note=note)
    audit(actor, 'catalog.reviewed', activity)
    return review
