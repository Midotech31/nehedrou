"""An actor-bound receipt for the first normal draft save, never an approval.

Committed historical working copies without this server marker remain history.
No browser data can set the marker through the working-copy autosave allowlist.
"""
import hashlib
import json
import uuid
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils.translation import gettext_lazy as _
from core.models import User
from core.services import audit
from .models import Activity, DraftWorkingCopy, EditorialGrant, Variety

RECEIPT_KEY = '_server_new_draft_receipt'
CONFLICT_MESSAGE = _('This save request already created a draft with different content. Open the saved draft or start a new creation page.')


def new_draft_receipt(copy):
    data = copy.data if isinstance(copy.data, dict) else {}
    receipt = data.get(RECEIPT_KEY)
    return (receipt if copy.committed and copy.activity_id and isinstance(receipt, dict)
            and receipt.get('schema') == 1 and receipt.get('operation') == 'create_activity'
            and receipt.get('result') == str(copy.activity_id)
            and isinstance(receipt.get('digest'), str) and len(receipt['digest']) == 64 else None)


def submission(form, data):
    # Preserve presence and repeated values: omission can mean "keep" in older
    # forms, while an explicit empty value can mean "clear". Never hash CSRF,
    # unknown fields or a client-supplied receipt.
    fields = {name: data.getlist(name) for name, field in form.fields.items()
              if not field.disabled and name in data}
    body = {'operation': 'create_activity', 'form': type(form).__name__, 'fields': fields}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return digest


def require_edit(actor, variety_id):
    # Hold the current exact edit grant through saving OR disclosing its result;
    # a request's earlier permission cache cannot authorize a replay.
    if not actor.is_superuser and not EditorialGrant.objects.select_for_update().filter(
            user=actor, variety_id=variety_id, edit=True).exists():
        raise PermissionDenied


def check_copy(copy, actor):
    if copy.owner_id != actor.pk or copy.dismissed:
        raise Http404
    if not copy.committed and copy.activity_id:
        raise Http404


def replay(copy, actor, digest):
    receipt = new_draft_receipt(copy)
    if receipt is None:
        raise Http404
    activity = Activity.objects.select_for_update().filter(pk=copy.activity_id).first()
    if activity is None:
        raise Http404
    require_edit(actor, activity.variety_id)
    if receipt['digest'] != digest:
        return None, 409, activity
    return activity, 200, None


@transaction.atomic
def save_new_draft(request, form, identifier):
    # Activity's deferred Variety FK must not wait at COMMIT behind access
    # management, whose order is Variety then User. Autosave has no Variety FK.
    reserved_variety = None
    try:
        variety_id = uuid.UUID(request.POST.get('variety', ''))
    except (ValueError, TypeError, AttributeError):
        pass
    else:
        choices = Variety.objects.select_for_update(of=('self',)).filter(pk=variety_id)
        if not request.user.is_superuser:
            choices = choices.filter(editorialgrant__user=request.user, editorialgrant__edit=True)
        reserved_variety = choices.first()
    actor = User.objects.select_for_update(no_key=True).filter(pk=request.user.pk, is_active=True).first()
    if actor is None:
        raise PermissionDenied
    digest = submission(form, request.POST)
    copy = DraftWorkingCopy.objects.select_for_update().filter(pk=identifier).first()
    if copy:
        check_copy(copy, actor)
        if copy.committed:
            return replay(copy, actor, digest)
    if not form.is_valid():
        return None, 200, None
    if reserved_variety is None or form.cleaned_data['variety'].pk != reserved_variety.pk:
        form.add_error('variety', _('Reload the creation page and choose the spoken variety again.'))
        return None, 409, None
    if copy is None:
        try:
            # CheckedModel can detect a UUID collision in full_clean before its
            # INSERT, so handle both that validation and the unique constraint.
            with transaction.atomic():
                copy = DraftWorkingCopy.objects.create(pk=identifier, owner=actor)
        except (IntegrityError, ValidationError):
            copy = DraftWorkingCopy.objects.select_for_update().filter(pk=identifier).first()
            if copy is None:
                raise
            check_copy(copy, actor)
            if copy.committed:
                return replay(copy, actor, digest)
    require_edit(actor, form.cleaned_data['variety'].pk)
    activity = form.save()
    # Keep only work already retained by autosave. A new receipt does not
    # duplicate the authored POST or extend retention of its raw field values.
    snapshot = dict(copy.data) if isinstance(copy.data, dict) else {}
    snapshot[RECEIPT_KEY] = {'schema': 1, 'operation': 'create_activity',
                             'digest': digest, 'result': str(activity.pk)}
    copy.activity = activity
    copy.data = snapshot
    copy.committed = True
    copy.save(update_fields=['activity', 'data', 'committed', 'updated_at'])
    audit(actor, 'catalog.draft_saved', activity)
    return activity, 200, None
