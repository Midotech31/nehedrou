"""Explicit recovery of saved family-guide fields; never a content decision."""
import hashlib
import json
import uuid

from django import forms
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from core.models import User
from core.services import audit
from .authoring import ActivityAuthoringForm, GUIDE_LABELS, LANGUAGE_LABELS
from .content_validation import STEP_FIELDS
from .finalization import require_edit
from .integrity import invalidate_integrity
from .models import Activity, DraftWorkingCopy, EditorialGrant
from .working import (RECOVERY_RECEIPT_KEY, WORKING_COPY_LIMIT, WORKING_BODY_LIMIT,
                      WORKING_VALUE_LIMIT, recover_url)

SALT = 'catalog.family-guide-recovery.v1'
MAX_AGE = 2 * 60 * 60
CHANGED = _('The working copy or current draft changed. Reload the comparison before choosing fields again.')
CAPACITY = _('You have 30 active working copies. Save an activity or set a copy aside in the editorial workspace.')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def guide_values(activity):
    values = {}
    instructions = activity.instructions if isinstance(activity.instructions, dict) else {}
    guides = activity.practice_guide if isinstance(activity.practice_guide, dict) else {}
    for code in LANGUAGE_LABELS:
        values['instructions_' + code] = instructions.get(code, '')
        guide = guides.get(code, {})
        for key in GUIDE_LABELS:
            value = guide.get(key, '')
            values[f'guide_{code}_{key}'] = '\n'.join(value) if key in STEP_FIELDS and isinstance(value, list) else value
    return values


def differences(source, activity):
    saved = source.data if isinstance(source.data, dict) else {}
    current = guide_values(activity)
    rows = []
    for code, language_label in LANGUAGE_LABELS.items():
        names = [('instructions_' + code, _('Caregiver instructions'))]
        names.extend((f'guide_{code}_{key}', label) for key, label in GUIDE_LABELS.items())
        for name, label in names:
            if name in saved and isinstance(saved[name], str) and saved[name] != current[name]:
                rows.append({'name': name, 'language': code, 'language_label': language_label,
                             'label': label, 'current': current[name], 'saved': saved[name]})
    return rows


class RecoveryForm(forms.Form):
    state_token = forms.CharField(widget=forms.HiddenInput)
    select_fields = forms.MultipleChoiceField(
        label=_('Choose the family-guide fields to recover'), widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, rows, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['select_fields'].choices = [(row['name'], f"{row['language_label']} · {row['label']}") for row in rows]


def current_form_values(activity, actor):
    # Build only the current ordinary authoring values; selecting saved text
    # never carries old words, media, targets, variety or evidence references.
    form = ActivityAuthoringForm(instance=activity, actor=actor)
    values = {}
    for name in form.fields:
        value = form[name].value()
        values[name] = 'on' if value is True else '' if value is False or value is None else str(value)
    return values


def page(request, source, activity, *, rows=None, form=None, error='', status=200):
    rows = rows or []
    selected = set(request.POST.getlist('select_fields')) if request.method == 'POST' else set()
    for row in rows:
        row['selected'] = row['name'] in selected
    response = render(request, 'editorial/guide_recovery.html', {
        'source': source, 'activity': activity, 'rows': rows, 'form': form, 'recovery_error': error,
        'can_reload': not source.committed and not source.dismissed and activity.state == 'draft',
    }, status=status)
    response['Cache-Control'] = 'private, no-store'
    return response


def destination_result(destination, actor, activity, state_hash, selection_hash):
    if destination.owner_id != actor.pk:
        raise Http404
    receipt = destination.data.get(RECOVERY_RECEIPT_KEY, {}) if isinstance(destination.data, dict) else {}
    if (destination.activity_id != activity.pk or destination.dismissed or
            receipt != {'schema': 1, 'state': state_hash, 'selection': selection_hash}):
        return None
    response = redirect('editorial_detail', pk=activity.pk) if destination.committed else redirect(recover_url(destination))
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
@require_http_methods(['GET', 'POST'])
@csrf_protect
def reconcile(request, pk):
    # Discover the Activity without a row lock, then revalidate the same
    # relationship after acquiring User -> Activity -> ordered copy locks.
    source = get_object_or_404(DraftWorkingCopy.objects.select_related('activity__variety'), pk=pk, owner=request.user)
    if not source.activity_id:
        raise Http404
    activity = source.activity
    if not request.user.is_superuser and not EditorialGrant.objects.filter(
            user=request.user, variety=activity.variety, edit=True).exists():
        raise PermissionDenied
    if request.method == 'GET':
        if source.committed or source.dismissed or activity.state != 'draft':
            raise Http404
        rows = differences(source, activity)
        state = {'schema': 1, 'actor': str(request.user.pk), 'source': str(source.pk),
                 'revision': source.revision, 'source_hash': digest(source.data), 'base': source.base_digest,
                 'activity': str(activity.pk), 'current': activity.fingerprint(), 'destination': str(uuid.uuid4())}
        form = RecoveryForm(rows=rows, initial={'state_token': signing.dumps(state, salt=SALT, compress=True)})
        return page(request, source, activity, rows=rows, form=form)
    try:
        state = signing.loads(request.POST.get('state_token', ''), salt=SALT, max_age=MAX_AGE)
        if (not isinstance(state, dict) or state.get('schema') != 1 or
                state.get('source') != str(pk) or type(state.get('revision')) is not int):
            raise signing.BadSignature
        if state.get('actor') != str(request.user.pk):
            raise PermissionDenied
        activity_id, destination_id = uuid.UUID(state['activity']), uuid.UUID(state['destination'])
        if destination_id == pk:
            raise signing.BadSignature
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return page(request, source, activity, error=_('The comparison link is invalid or expired. Open a new comparison.'), status=400)
    with transaction.atomic():
        actor = User.objects.select_for_update(no_key=True).filter(pk=request.user.pk, is_active=True).first()
        if actor is None:
            raise PermissionDenied
        locked_activity = Activity.objects.select_for_update(of=('self',)).select_related('variety').filter(pk=activity_id).first()
        copies = {copy.pk: copy for copy in DraftWorkingCopy.objects.select_for_update().filter(
            pk__in=[pk, destination_id]).order_by('pk')}
        source = copies.get(pk)
        if not source or source.owner_id != actor.pk:
            raise Http404
        if not locked_activity or source.activity_id != activity_id:
            return page(request, source, activity, error=CHANGED, status=409)
        activity = locked_activity
        require_edit(actor, activity.variety_id)
        invalidate_integrity()
        current_digest = activity.fingerprint()
        if (source.committed or source.dismissed or activity.state != 'draft' or
                source.revision != state['revision'] or digest(source.data) != state.get('source_hash') or
                source.base_digest != state.get('base') or current_digest != state.get('current')):
            return page(request, source, activity, error=CHANGED, status=409)
        rows = differences(source, activity)
        form = RecoveryForm(request.POST, rows=rows)
        if not form.is_valid():
            return page(request, source, activity, rows=rows, form=form, status=400)
        selected = sorted(set(form.cleaned_data['select_fields']))
        state_hash, selection_hash = digest(state), digest(selected)
        destination = copies.get(destination_id)
        if destination:
            result = destination_result(destination, actor, activity, state_hash, selection_hash)
            return result or page(request, source, activity, error=CHANGED, status=409)
        if DraftWorkingCopy.objects.filter(owner=actor, committed=False, dismissed=False).count() >= WORKING_COPY_LIMIT:
            form.add_error(None, CAPACITY)
            return page(request, source, activity, rows=rows, form=form, status=409)
        data = current_form_values(activity, actor)
        for name in selected:
            data[name] = source.data[name]
        if any(len(value) > WORKING_VALUE_LIMIT for value in data.values()) or len(json.dumps(data, ensure_ascii=False).encode()) > WORKING_BODY_LIMIT:
            form.add_error(None, _('The recovered working copy would exceed the existing size limit.'))
            return page(request, source, activity, rows=rows, form=form, status=413)
        data[RECOVERY_RECEIPT_KEY] = {'schema': 1, 'state': state_hash, 'selection': selection_hash}
        try:
            with transaction.atomic():
                destination = DraftWorkingCopy.objects.create(pk=destination_id, owner=actor, activity=activity,
                    base_digest=current_digest, data=data, revision=1)
        except (IntegrityError, ValidationError):
            destination = DraftWorkingCopy.objects.select_for_update().filter(pk=destination_id).first()
            if destination is None:
                raise
            result = destination_result(destination, actor, activity, state_hash, selection_hash)
            return result or page(request, source, activity, error=CHANGED, status=409)
        audit(actor, 'catalog.family_guide_work_recovered', destination)
        response = redirect(recover_url(destination))
        response['Cache-Control'] = 'private, no-store'
        return response
