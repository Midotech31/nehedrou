"""Private working copies retain incomplete author input without approving content."""
import json
import uuid
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, IntegrityError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST
from .models import Activity, EditorialGrant, DraftWorkingCopy
from .services import allowed


def authorize_copy(user, copy):
    if copy.activity_id:
        activity = copy.activity
        if activity.state != 'draft' or not allowed(user, activity.variety, 'edit'):
            raise PermissionDenied
    elif copy.data.get('variety'):
        from .models import Variety
        variety = get_object_or_404(Variety, pk=copy.data['variety'])
        if not allowed(user, variety, 'edit'):
            raise PermissionDenied


def resume_copy(request, activity):
    value = request.GET.get('resume') or request.POST.get('working_copy')
    if not value:
        return None
    try:
        identifier = uuid.UUID(value)
    except (ValueError, AttributeError):
        raise Http404
    copy = DraftWorkingCopy.objects.filter(pk=identifier, owner=request.user, committed=False, dismissed=False).select_related('activity__variety').first()
    if not copy:
        # An unsaved first page submits its preallocated UUID before autosave starts.
        if request.method == 'POST' and not DraftWorkingCopy.objects.filter(pk=identifier).exists():
            return None
        raise Http404
    if copy.activity_id != (activity.pk if not activity._state.adding else None):
        raise Http404
    authorize_copy(request.user, copy)
    return copy


def recover_url(copy):
    route = reverse('editorial_edit', args=[copy.activity_id]) if copy.activity_id else reverse('editorial_create')
    return route + '?resume=' + str(copy.pk)


@login_required
@require_POST
def autosave(request, pk):
    if not request.user.is_superuser and not EditorialGrant.objects.filter(user=request.user, edit=True).exists():
        raise PermissionDenied
    if len(request.body) > 180000:
        return JsonResponse({'error': 'too_large'}, status=413)
    try:
        payload = json.loads(request.body)
        data, revision = payload['fields'], payload['revision']
        if not isinstance(data, dict) or type(revision) is not int or revision < 0:
            raise ValueError
        from .authoring import ActivityAuthoringForm
        permitted = set(ActivityAuthoringForm(actor=request.user).fields)
        if any(key not in permitted or not isinstance(value, str) or len(value) > 16000 for key, value in data.items()):
            raise ValueError
        activity_id = uuid.UUID(payload['activity']) if payload.get('activity') else None
        if data.get('variety'):
            uuid.UUID(data['variety'])
        base_digest = payload.get('base_digest', '')
        if not isinstance(base_digest, str) or len(base_digest) > 64:
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        return JsonResponse({'error': 'invalid_input'}, status=400)
    try:
        with transaction.atomic():
            from core.models import User
            User.objects.select_for_update().get(pk=request.user.pk)
            copy = DraftWorkingCopy.objects.select_for_update(of=('self',)).filter(pk=pk).select_related('activity__variety').first()
            if copy and (copy.committed or copy.dismissed or copy.owner_id != request.user.pk or copy.activity_id != activity_id):
                raise Http404
            if not copy:
                if revision != 0:
                    return JsonResponse({'error': 'expired'}, status=409)
                if DraftWorkingCopy.objects.filter(owner=request.user, committed=False, dismissed=False).count() >= 30:
                    return JsonResponse({'error': 'capacity'}, status=409)
                activity = get_object_or_404(Activity, pk=activity_id) if activity_id else None
                copy = DraftWorkingCopy(id=pk, owner=request.user, activity=activity, base_digest=base_digest)
            if copy.revision != revision:
                return JsonResponse({'error': 'conflict'}, status=409)
            copy.data = data
            authorize_copy(request.user, copy)
            if copy.activity_id and copy.base_digest != copy.activity.fingerprint():
                return JsonResponse({'error': 'source_changed'}, status=409)
            copy.revision += 1
            copy.save()
    except (IntegrityError, ValidationError):
        return JsonResponse({'error': 'conflict'}, status=409)
    response = JsonResponse({'revision': copy.revision, 'resume_url': recover_url(copy)})
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@require_POST
def set_aside(request, pk):
    action = request.POST.get('action')
    if action not in ['dismiss', 'restore']:
        return JsonResponse({'error':'invalid_action'},status=400)
    with transaction.atomic():
        from core.models import User
        User.objects.select_for_update().get(pk=request.user.pk)
        copy = get_object_or_404(DraftWorkingCopy.objects.select_for_update(), pk=pk, owner=request.user, committed=False)
        # Dismissing retains the private data; it does not touch the activity.
        if action == 'restore':
            if not request.user.is_superuser and not EditorialGrant.objects.filter(user=request.user, edit=True).exists():
                raise PermissionDenied
            authorize_copy(request.user,copy)
            if DraftWorkingCopy.objects.filter(owner=request.user,committed=False,dismissed=False).count() >= 30:
                return JsonResponse({'error':'capacity'},status=409)
        copy.dismissed = action == 'dismiss'
        copy.save(update_fields=['dismissed','updated_at'])
    return redirect('editorial_index')
