"""Private, transient rehearsal of the exact visible editorial version.

This view never calls practice services, creates clinical objects, saves answers,
or turns a preview into a review or availability decision.
"""
import hashlib
import json
from types import SimpleNamespace

from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.utils.translation import gettext_lazy as _
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from core.form_scope import MAX_AGE
from core.forms import PracticeForm
from .audio_checks import audio_binding_errors
from .readiness import referenced_asset, snapshot_media
from .views import editorial_activities


SALT = 'catalog.private-rehearsal.v1'


class GuideLanguageForm(forms.Form):
    guide_language = forms.ChoiceField(label=_('Caregiver instructions'), choices=settings.LANGUAGES)


class RehearsalForm(PracticeForm):
    """Same structured choices as practice; no patient identifiers or free text."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        del self.fields['ticket']
        del self.fields['comment']


def _presentation(activity):
    """Omit unusable media without editing or qualifying the authored content.

    Drafts need not have approved rights. Files still use the existing protected
    endpoint; withdrawn, changed or wrongly bound bytes are not exercise models.
    The normal CMS/media views remain available for inspecting those problems.
    """
    values = {'variety': activity.variety, 'device_voice_allowed': False}
    for side in ('a', 'b'):
        word = values['word_' + side] = getattr(activity, 'word_' + side)
        image = getattr(activity, 'image_' + side)
        asset = referenced_asset(image, 'image')
        values['image_' + side] = image if (
            asset is not None and not asset.revoked and asset.intact
            or not image.startswith('editorial/asset-') and activity.image_available(image)
        ) else ''
        audio = getattr(activity, 'audio_' + side)
        asset = referenced_asset(audio, 'audio')
        values['audio_' + side] = audio if (
            asset is not None and not asset.revoked and asset.intact
            and not audio_binding_errors(asset, word, activity.variety)
        ) else ''
    return SimpleNamespace(**values)


def _snapshot(request, activity, language, target):
    media_digest = hashlib.sha256(json.dumps(snapshot_media(activity), sort_keys=True).encode()).hexdigest()
    expected = {'actor': str(request.user.pk), 'activity': str(activity.pk),
        'content': activity.fingerprint(), 'media': media_digest, 'language': language, 'target': target}
    if request.method == 'GET':
        return signing.dumps(expected, salt=SALT), True
    values = request.POST.getlist('rehearsal_snapshot')
    if len(values) != 1 or not values[0] or len(values[0]) > 1024:
        return '', False
    try:
        actual = signing.loads(values[0], salt=SALT, max_age=MAX_AGE)
    except (signing.BadSignature, ValueError, TypeError):
        return '', False
    return values[0], actual == expected


@never_cache
@login_required
@require_http_methods(['GET', 'POST'])
def rehearse(request, pk):
    activity = get_object_or_404(editorial_activities(request.user).select_related('variety'), pk=pk)
    incoming = request.POST if request.method == 'POST' else request.GET
    fields = {'guide_language'}
    if request.method == 'POST':
        fields.update({'rehearsal_snapshot', 'csrfmiddlewaretoken',
            *RehearsalForm(response_mode=activity.response_mode).fields})
    if set(incoming) - fields or any(len(incoming.getlist(key)) != 1 for key in incoming):
        return HttpResponseBadRequest()
    selection = GuideLanguageForm(incoming or None, initial={'guide_language': request.user.instruction_language})
    if incoming and not selection.is_valid():
        return render(request, 'editorial/rehearsal.html', {
            'activity': activity, 'selection_form': selection, 'selection_invalid': True,
        }, status=400)
    language = selection.cleaned_data['guide_language'] if incoming else request.user.instruction_language
    instruction = activity.instructions.get(language, '')
    target_side = activity.requested_target or 'a'
    token, matches = _snapshot(request, activity, language, target_side)
    form = RehearsalForm(request.POST if request.method == 'POST' else None, response_mode=activity.response_mode)
    summary = None
    if request.method == 'POST' and matches and instruction and form.is_valid():
        data = form.cleaned_data
        summary = {name: dict(form.fields[name].choices).get(data.get(name), '—')
            for name in ('completion', 'parent_report', 'support_used', 'stop_reason')}
        # A picture selection is described; speech and clinical progress are not scored.
        summary['answer'] = getattr(activity, 'word_' + data['answer']) if data.get('answer') else '—'
    presentation = _presentation(activity)
    response = render(request, 'editorial/rehearsal.html', {
        'activity': activity, 'practice_activity': presentation, 'selection_form': selection,
        'instruction_language': language, 'instruction': instruction,
        'form': form, 'summary': summary, 'rehearsal_snapshot': token,
        'snapshot_changed': not matches, 'content_digest': activity.fingerprint(),
        'response_mode': activity.response_mode, 'target_side': target_side,
        'media_omitted': any(getattr(activity, name) and not getattr(presentation, name)
            for name in ('image_a', 'image_b', 'audio_a', 'audio_b')),
        'target': getattr(activity, 'word_' + target_side),
        'audio': getattr(presentation, 'audio_' + target_side),
        'step_two_title': {'matching': _('Listen and choose'), 'free': _('Choose a picture freely'),
            'observation': _('Play together')}[activity.response_mode],
    }, status=200 if matches else 409)
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response
