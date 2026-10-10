import uuid
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils.translation import gettext as _
from core.services import audit
from .models import Activity, EditorialGrant, Review

def allowed(user, variety, capability):
    return user.is_superuser or EditorialGrant.objects.filter(user=user, variety=variety, **{capability: True}).exists()

@transaction.atomic
def transition(actor, activity_id, target):
    activity = Activity.objects.select_for_update().get(pk=activity_id)
    capability = 'publish' if target in ['published', 'withdrawn', 'approved'] else 'edit'
    if not allowed(actor, activity.variety, capability):
        raise PermissionDenied
    transitions = {'draft': ['review'], 'review': ['draft', 'approved'], 'approved': ['draft', 'published'], 'published': ['withdrawn'], 'withdrawn': []}
    if target not in transitions[activity.state]:
        raise ValidationError(_('This editorial transition is not allowed.'))
    if target == 'approved' and not activity.is_demo:
        if not activity.has_current_reviews():
            raise ValidationError(_('Clinical and linguistic reviews are required.'))
    activity.state = target
    activity.save()
    audit(actor, 'catalog.' + target, activity)
    return activity

@transaction.atomic
def clone_version(actor, source):
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
def review_version(actor, activity, kind, approved, note):
    activity = Activity.objects.select_for_update().get(pk=activity.pk)
    capability = 'clinical_review' if kind == 'clinical' else 'linguistic_review'
    if not allowed(actor, activity.variety, capability):
        raise PermissionDenied
    review = Review.objects.create(activity=activity, reviewer=actor, kind=kind, approved=approved, note=note)
    audit(actor, 'catalog.reviewed', activity)
    return review
