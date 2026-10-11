import csv
import io
import uuid
import mimetypes
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404, HttpResponse, FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext_lazy as _, get_language
from django.views.decorators.http import require_POST
from care.models import Child, FamilyLink
from catalog.services import allowed
from catalog.models import EditorialGrant, MediaAsset
from core.access import professional_children, visible_children, clinician_child
from core.models import Membership
from . import services
from .models import ClinicalGoal, ProbeDefinition, ProbeAdministration, ParentCoaching
from .forms import GoalForm, DefinitionForm, ItemFormSet, ReviewForm, ConditionsForm, FamiliarityForm, RatingForm, FinalizeForm, ShareForm, CoachingForm, HomeFeedbackForm, ExposureForm, CODE_CHOICES, ELICITATION_CHOICES


STATE_LABELS = {'draft': _('Draft'), 'review': _('In review'), 'approved': _('Internally reviewed'), 'published': _('Published'), 'withdrawn': _('Withdrawn'), 'finalized': _('Finalized')}
EXPOSURE_LABELS = {'trained': _('Trained words'), 'untrained': _('Untrained words'), 'reserved': _('Reserved words'), 'uncertain': _('Exposure uncertain')}
CODE_LABELS = dict(CODE_CHOICES)
ELICITATION_LABELS = dict(ELICITATION_CHOICES)
CONDITION_LABELS = {'place': _('Setting'), 'task': _('Planned task'), 'fatigue': _('Fatigue and wellbeing'), 'noise': _('Noise and listening conditions'), 'interruption': _('Interruption or stopping conditions'), 'instructions': _('Instructions given at the start'), 'audio_equipment': _('Audio equipment, if used'), 'attempt_rule': _('Attempt retained, decided before presentation')}
INSTRUCTION_LANGUAGES = {'fr': 'Français', 'en': 'English', 'ar': 'العربية'}


def professional_goal(user, pk):
    return get_object_or_404(ClinicalGoal.objects.select_related('child', 'variety'), pk=pk, child__in=professional_children(user))


def professional_admin(user, pk):
    return get_object_or_404(services.professional_administrations(user).select_related('child', 'goal', 'definition', 'professional'), pk=pk)


def protocol_user(user):
    if not Membership.objects.filter(user=user, active=True).exists() and not EditorialGrant.objects.filter(user=user).exists():
        raise Http404


def service_error(form, error):
    form.add_error(None, ValidationError(error.messages))


def render_form(request, form, title, *, intro='', back=None, **context):
    return render(request, 'followup/form.html', {'form': form, 'title': title, 'intro': intro, 'back': back, **context})


@login_required
def index(request):
    children = professional_children(request.user).select_related('organization')
    professional = Membership.objects.filter(user=request.user, active=True).exists()
    if professional:
        goals = ClinicalGoal.objects.filter(child__in=children).select_related('child', 'variety').order_by('-created_at')
        return render(request, 'followup/index.html', {'professional': True, 'children': children, 'goals': goals, 'administrations': services.professional_administrations(request.user).select_related('child', 'definition').order_by('-started_at')[:20]})
    if EditorialGrant.objects.filter(user=request.user).exists():
        return redirect('followup:definition_list')
    linked = visible_children(request.user)
    shares = ProbeAdministration.objects.filter(child__in=linked, status='finalized', shared_at__isnull=False).exclude(shared_text='').select_related('child', 'definition').order_by('-shared_at')
    coaching = list(ParentCoaching.objects.filter(child__in=linked).select_related('child', 'variety').order_by('-created_at'))
    for guide in coaching:
        guide.instruction_language_label = INSTRUCTION_LANGUAGES.get(guide.instruction_language, _('Instruction language not recorded'))
    coaching.sort(key=lambda guide: guide.instruction_language != get_language())
    return render(request, 'followup/index.html', {'professional': False, 'shares': shares, 'coaching': coaching})


@login_required
def goal_create(request, child_id):
    child = clinician_child(request.user, child_id)
    form = GoalForm(request.POST or None, child=child, definitions=services.definition_queryset(request.user).filter(variety__in=child.varieties.all()).exclude(state='withdrawn'))
    if request.method == 'POST' and form.is_valid():
        try:
            goal = services.create_goal(request.user, child, form.cleaned_data)
            return redirect('followup:goal_detail', pk=goal.pk)
        except ValidationError as error:
            service_error(form, error)
    return render_form(request, form, _('Create a clinical follow-up goal'), intro=_('Choose the target after the external assessment. Interface language does not change the treatment variety.'), child=child, back=('followup:index', None))


@login_required
def goal_detail(request, pk):
    goal = professional_goal(request.user, pk)
    status = {'confirmed': _('Already assessed by the responsible professional'), 'pending': _('Pending'), 'not_recorded': _('Not recorded')}
    return render(request, 'followup/goal.html', {'goal': goal, 'assessment_status_label': status[goal.external_assessment_status], 'administrations': goal.administrations.order_by('-started_at'), 'coaching': ParentCoaching.objects.filter(child=goal.child, variety=goal.variety).order_by('-created_at')})


@login_required
@require_POST
def goal_close(request, pk):
    goal = professional_goal(request.user, pk)
    try:
        services.close_goal(request.user, goal)
        messages.success(request, _('The goal has been closed. Its observations and history remain available.'))
    except ValidationError as error:
        for text in error.messages:
            messages.error(request, text)
    return redirect('followup:goal_detail', pk=pk)


@login_required
def exposure_create(request, child_id):
    child = clinician_child(request.user, child_id)
    form = ExposureForm(request.POST or None, child=child)
    if request.method == 'POST' and form.is_valid():
        try:
            services.record_exposure(request.user, child, **form.cleaned_data)
            messages.success(request, _('The external exposure record has been saved. Previous observation exposure remains unchanged.'))
            return redirect('followup:index')
        except ValidationError as error:
            service_error(form, error)
    return render_form(request, form, _('Record external word exposure'), intro=_('Document practice outside the application, its source and its date. An untrained or uncertain declaration does not erase known training. Reserved-word practice is shown in the observation history.'), child=child, back=('followup:index', None))


@login_required
def definition_list(request):
    protocol_user(request.user)
    definitions = services.definition_queryset(request.user).select_related('variety', 'organization').order_by('variety__label', 'title', '-version')
    state = request.GET.get('state', '')
    if state in STATE_LABELS:
        definitions = definitions.filter(state=state)
    return render(request, 'followup/definitions.html', {'definitions': definitions, 'can_create': Membership.objects.filter(user=request.user, active=True).exists() or EditorialGrant.objects.filter(user=request.user, edit=True).exists(), 'states': list(STATE_LABELS.items())[:5], 'selected_state': state})


def item_rows(formset, original_items=None):
    rows = []
    originals = {row['id']: row for row in original_items or []}
    for form in formset:
        if not form.cleaned_data or form.cleaned_data.get('DELETE'):
            continue
        original_id = form.cleaned_data.get('original_id') or form.cleaned_data['id']
        row = {**originals.get(original_id, {}), **{key: value for key, value in form.cleaned_data.items() if key not in ['DELETE', 'original_id']}}
        for name in ['image_asset', 'audio_asset']:
            row[name] = str(row[name].pk) if row[name] else None
        rows.append(row)
    return rows


@login_required
def definition_edit(request, pk=None):
    protocol_user(request.user)
    definition = get_object_or_404(services.definition_queryset(request.user), pk=pk) if pk else None
    if definition and (definition.state != 'draft' or definition.administrations.exists() or definition.clinicalgoal_set.exists() or not services.can_edit_definition(request.user, definition)):
        raise PermissionDenied
    if not definition and not (Membership.objects.filter(user=request.user, active=True).exists() or EditorialGrant.objects.filter(user=request.user, edit=True).exists()):
        raise PermissionDenied
    form = DefinitionForm(request.POST or None, definition=definition)
    if not definition and not request.user.is_superuser:
        form.fields['variety'].queryset = form.fields['variety'].queryset.filter(Q(pk__in=professional_children(request.user).filter(active=True).values('varieties')) | Q(pk__in=EditorialGrant.objects.filter(user=request.user, edit=True).values('variety_id'))).distinct()
    references = [item.get(key) for item in definition.items for key in ['image_asset', 'audio_asset'] if item.get(key)] if definition else []
    media = MediaAsset.objects.filter(Q(uploaded_by=request.user) | Q(rights_evidence__variety__in=form.fields['variety'].queryset) | Q(pk__in=references)).distinct().order_by('-created_at')
    initial_items = [{**item, 'original_id': item['id']} for item in definition.items] if definition else None
    rows = ItemFormSet(request.POST or None, prefix='items', initial=initial_items, form_kwargs={'media': media})
    if request.method == 'POST' and form.is_valid() and rows.is_valid():
        data = {**form.cleaned_data, 'items': item_rows(rows, definition.items if definition else None)}
        try:
            definition = services.update_definition(request.user, definition, data) if definition else services.create_definition(request.user, data)
            return redirect('followup:definition_detail', pk=definition.pk)
        except ValidationError as error:
            service_error(form, error)
    return render_form(request, form, _('Design an original probe protocol'), intro=_('Drafts are design material. They do not authorize real clinical administration. Reserve words remain outside family practice.'), item_forms=rows, definition=definition, can_upload_media=request.user.is_superuser or EditorialGrant.objects.filter(user=request.user, edit=True).exists(), back=('followup:definition_list', None))


@login_required
def definition_detail(request, pk):
    protocol_user(request.user)
    definition = get_object_or_404(services.definition_queryset(request.user).select_related('variety'), pk=pk)
    can_edit = services.can_edit_definition(request.user, definition)
    can_clone = can_edit or professional_children(request.user).filter(active=True, varieties=definition.variety).exists()
    can_publish = allowed(request.user, definition.variety, 'publish')
    kinds = [kind for kind, capability in [('clinical', 'clinical_review'), ('linguistic', 'linguistic_review')] if allowed(request.user, definition.variety, capability)]
    can_review = bool(kinds) and definition.state in ['review', 'approved']
    if request.method == 'POST' and (not can_review or request.POST.get('kind') not in kinds):
        raise PermissionDenied
    form = ReviewForm(request.POST or None, kinds=kinds)
    if request.method == 'POST' and form.is_valid():
        try:
            services.review_definition(request.user, definition, **form.cleaned_data)
            return redirect('followup:definition_detail', pk=pk)
        except ValidationError as error:
            service_error(form, error)
    return render(request, 'followup/definition.html', {'definition': definition, 'state_label': STATE_LABELS[definition.state], 'can_edit': can_edit, 'can_clone': can_clone, 'can_edit_content': can_edit and definition.state == 'draft' and not definition.administrations.exists() and not definition.clinicalgoal_set.exists(), 'can_publish': can_publish, 'can_review': can_review, 'review_form': form, 'reviews': definition.reviews.select_related('author').order_by('-created_at'), 'readiness_reasons': services.readiness_reasons(definition)})


def item_media_response(item, kind, frozen_media=None, request=None):
    if kind not in ['image', 'audio'] or not item.get(kind + '_asset'):
        raise Http404
    asset = get_object_or_404(MediaAsset, pk=item[kind + '_asset'], kind=kind)
    if kind != 'audio' and not asset.intact:
        raise Http404
    if frozen_media is not None:
        entry = frozen_media.get(item['id'] + ':' + kind + '_asset', {})
        if str(entry.get('reference')) != str(asset.pk) or entry.get('sha256') != asset.technical_metadata.get('sha256'):
            raise Http404
    if kind == 'audio':
        from catalog.audio_delivery import protected_media_response
        return protected_media_response(request, asset)
    response = FileResponse(asset.file.open('rb'), content_type=mimetypes.guess_type(asset.file.name)[0] or 'application/octet-stream')
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
def definition_media(request, pk, item_key, kind):
    protocol_user(request.user)
    definition = get_object_or_404(services.definition_queryset(request.user), pk=pk)
    item = next((row for row in definition.items if row['id'] == item_key), None)
    if not item:
        raise Http404
    return item_media_response(item, kind, request=request)


@login_required
def administration_media(request, pk, item_key, kind):
    admin = professional_admin(request.user, pk)
    item = next((row for row in admin.snapshot['items'] if row['id'] == item_key), None)
    if not item:
        raise Http404
    return item_media_response(item, kind, admin.snapshot.get('media', {}), request=request)


@login_required
@require_POST
def definition_clone(request, pk):
    definition = get_object_or_404(services.definition_queryset(request.user), pk=pk)
    try:
        new = services.clone_definition(request.user, definition)
        return redirect('followup:definition_edit', pk=new.pk)
    except ValidationError as error:
        for text in error.messages:
            messages.error(request, text)
        return redirect('followup:definition_detail', pk=pk)


@login_required
@require_POST
def definition_transition(request, pk):
    definition = get_object_or_404(services.definition_queryset(request.user), pk=pk)
    try:
        services.transition_definition(request.user, definition, request.POST.get('state', ''))
    except ValidationError as error:
        for text in error.messages:
            messages.error(request, text)
    return redirect('followup:definition_detail', pk=pk)


@login_required
def administration_start(request, goal_id):
    goal = professional_goal(request.user, goal_id)
    if not goal.active:
        raise PermissionDenied
    definitions = services.definition_queryset(request.user).filter(variety=goal.variety).exclude(state='withdrawn')
    selected_id = request.GET.get('definition')
    selected = definitions.filter(pk=selected_id).first() if selected_id and re_uuid(selected_id) else definitions.filter(pk=goal.probe_definition_id).first() or definitions.first()
    if selected_id and not selected:
        raise Http404
    initial = {'key': uuid.uuid4(), 'definition': selected, 'task': 'naming'}
    form = ConditionsForm(request.POST or None, definitions=definitions, initial=initial)
    form.fields['definition'].disabled = True
    familiarity = FamiliarityForm(request.POST or None, items=selected.items if selected else [], prefix='familiarity')
    if request.method == 'POST' and form.is_valid() and familiarity.is_valid():
        try:
            conditions = {key: value for key, value in form.cleaned_data.items() if key not in ['definition', 'key']}
            admin = services.start_administration(request.user, goal, form.cleaned_data['definition'], conditions=conditions, familiarity=familiarity.result(), key=form.cleaned_data['key'])
            return redirect('followup:administration_detail', pk=admin.pk)
        except ValidationError as error:
            service_error(form, error)
    return render(request, 'followup/start.html', {'goal': goal, 'form': form, 'familiarity_form': familiarity, 'selected_definition': selected, 'definitions': definitions})


def re_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, TypeError):
        return False


@login_required
def administration_detail(request, pk):
    admin = professional_admin(request.user, pk)
    ratings = {rating.item_key: rating for rating in admin.ratings.all()}
    items = [{**item, 'rating': ratings.get(item['id']), 'exposure_label': EXPOSURE_LABELS.get(item.get('exposure_at_start', item.get('exposure_plan')), _('Exposure uncertain'))} for item in admin.snapshot['items']]
    for item in items:
        item['rating_label'] = CODE_LABELS.get(item['rating'].current_data()['code']) if item['rating'] else None
    return render(request, 'followup/administration.html', {'administration': admin, 'items': items, 'rated_count': len(ratings), 'total_count': len(items), 'state_label': STATE_LABELS[admin.status]})


@login_required
def rating(request, pk, item_key):
    admin = professional_admin(request.user, pk)
    item = next((item for item in admin.snapshot['items'] if item['id'] == item_key), None)
    if item is None:
        raise Http404
    existing = admin.ratings.filter(item_key=item_key).first()
    if admin.status != 'draft' and not existing:
        raise PermissionDenied
    variants = {row['id']: row for row in admin.snapshot['goal']['accepted_variants'] + item.get('accepted_variants', [])}
    initial = existing.current_data() if existing else {'attempt_index': item.get('selected_attempt', 1), 'elicitation': admin.conditions.get('task', 'naming')}
    form = RatingForm(request.POST or None, variants=list(variants.values()), existing=bool(existing), initial=initial)
    form.fields['attempt_index'].disabled = True
    if request.method == 'POST' and form.is_valid():
        try:
            data = dict(form.cleaned_data)
            reason = data.pop('reason')
            services.save_rating(request.user, admin, item_key, data, reason=reason)
            return redirect('followup:administration_detail', pk=pk)
        except ValidationError as error:
            service_error(form, error)
    return render_form(request, form, _('Rate the specified target occurrence'), intro=_('An audible target omission is a scorable error. Refusal, another word or an inaudible response is not a phonological omission. No immediate teaching correction is given during a probe.'), item=item, administration=admin, existing=existing, corrections=existing.revisions.select_related('author').order_by('-created_at') if existing else [], back=('followup:administration_detail', pk))


@login_required
def administration_finalize(request, pk):
    admin = professional_admin(request.user, pk)
    if admin.status == 'finalized' and request.method == 'GET':
        return redirect('followup:report', pk=pk)
    form = FinalizeForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            services.finalize_administration(request.user, admin)
            return redirect('followup:report', pk=pk)
        except ValidationError as error:
            service_error(form, error)
    return render_form(request, form, _('Review and finalize this observation'), intro=_('Check every occurrence. Finalization preserves the original summary; later corrections retain their reasons and dates.'), administration=admin, back=('followup:administration_detail', pk))


def report_context(request, pk):
    admin = professional_admin(request.user, pk)
    data = services.professional_report(request.user, admin)
    for group in data['groups'] + data['original_groups']:
        group['exposure_label'] = EXPOSURE_LABELS.get(group['exposure'], _('Exposure uncertain'))
        group['elicitation_label'] = ELICITATION_LABELS.get(group['elicitation'], group['elicitation'])
    for row in data['ratings']:
        row['code_label'] = CODE_LABELS.get(row['code'], row['code'])
        row['elicitation_label'] = ELICITATION_LABELS.get(row['elicitation'], row['elicitation'])
        item = next((item for item in admin.snapshot['items'] if item['id'] == row['item_key']), {})
        row['word'], row['ipa'] = item.get('word', ''), item.get('ipa', '')
        variants = admin.snapshot['goal'].get('accepted_variants', []) + item.get('accepted_variants', [])
        row['variant_label'] = next((variant['label'] for variant in variants if variant['id'] == row.get('variant_id')), '')
        error_labels = {'substitution': _('Substitution'), 'omission': _('Audible target omission'), 'distortion': _('Distortion'), 'other': _('Other scorable error')}
        row['error_label'] = error_labels.get(row.get('error_type'), '')
    condition_rows = [(CONDITION_LABELS[key], ELICITATION_LABELS.get(value, value) if key == 'task' else value) for key, value in admin.conditions.items()]
    return {**data, 'administration': admin, 'goal': admin.goal, 'clinical_goal_snapshot': data.get('clinical_goal_snapshot', admin.snapshot.get('goal', {})), 'state_label': STATE_LABELS[admin.status], 'condition_rows': condition_rows}


@login_required
def report(request, pk):
    return render(request, 'followup/report.html', report_context(request, pk))


@login_required
def report_print(request, pk):
    return render(request, 'followup/report_print.html', report_context(request, pk))


def csv_cell(value):
    # Quoted CSV alone does not neutralize spreadsheet formula interpretation.
    text = str(value) if value is not None else ''
    return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r')) else text


@login_required
def report_csv(request, pk):
    context = report_context(request, pk)
    buffer = io.StringIO(newline='')
    writer = csv.writer(buffer)
    group_header = [_('Target'), _('Spoken variety'), _('Exposure'), _('Actual elicitation'), _('Support'), _('Numerator'), _('Denominator'), _('Excluded'), _('Not presented'), _('Descriptive target ratio'), _('Protocol version'), _('Observer'), _('Observation date'), _('Conditions')]
    writer.writerow(group_header)
    admin = context['administration']
    conditions = ' · '.join(f'{label}: {value}' for label, value in context['condition_rows'])
    def write_groups(groups):
        for group in groups:
            writer.writerow([csv_cell(value) for value in [group['target'], group['variety'], group['exposure_label'], group['elicitation_label'], group.get('assistance', ''), group['numerator'], group['denominator'], group['excluded'], group['not_presented'], group['ratio'] if group['ratio'] is not None else _('Not calculable'), admin.snapshot.get('version', admin.definition.version), admin.professional.username, admin.started_at.isoformat(), conditions]])
    write_groups(context['groups'])
    if context['corrections'] and context['original_groups']:
        writer.writerow([])
        writer.writerow([_('Original finalized summary')])
        writer.writerow(group_header)
        write_groups(context['original_groups'])
    writer.writerow([])
    writer.writerow([_('Item'), _('Word'), _('IPA transcription proposed for review'), _('Occurrence'), _('Retained attempt'), _('Code'), _('Actual elicitation'), _('Support'), _('Production transcription'), _('Variant'), _('Exclusion reason'), _('Error type'), _('The expected word was audibly attempted'), _('The target is identifiable and scorable')])
    for row in context['ratings']:
        data = row.get('data', row)
        writer.writerow([csv_cell(value) for value in [row.get('item_key', ''), row.get('word', ''), row.get('ipa', ''), row.get('occurrence_index', ''), data.get('attempt_index', ''), data.get('code', ''), data.get('elicitation', ''), data.get('assistance', ''), data.get('transcription', ''), data.get('variant_id', ''), data.get('exclusion_reason', ''), data.get('error_type', ''), data.get('attempted_expected_word', False), data.get('target_identifiable', False)]])
    writer.writerow([])
    writer.writerow([_('Correction history'), _('Observer'), _('Correction date'), _('Reason for correction')])
    for row in context['corrections']:
        writer.writerow([csv_cell(value) for value in [row['rating_id'], row['author'], row['created_at'], row['reason']]])
    writer.writerow([])
    writer.writerow([_('Later exposure of reserved words'), _('Original exposure'), _('Date')])
    for row in context['contamination']:
        writer.writerow([csv_cell(value) for value in [row['word'], row['original_exposure'], row['at']]])
    response = HttpResponse('\ufeff' + buffer.getvalue(), content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="production-followup-{admin.pk}.csv"'
    response['Cache-Control'] = 'private, no-store'
    return response


@login_required
def share(request, pk):
    admin = professional_admin(request.user, pk)
    if admin.status != 'finalized':
        raise PermissionDenied
    form = ShareForm(request.POST or None, initial={'text': admin.shared_text})
    if request.method == 'POST' and form.is_valid():
        try:
            services.share_summary(request.user, admin, form.cleaned_data['text'])
            return redirect('followup:report', pk=pk)
        except ValidationError as error:
            service_error(form, error)
    return render_form(request, form, _('Choose exactly what to share with the family'), intro=_('The family receives only the text below. Raw item ratings, reserved words, private observations and detailed exports remain professional.'), administration=admin, back=('followup:report', pk))


@login_required
@require_POST
def share_revoke(request, pk):
    admin = professional_admin(request.user, pk)
    try:
        services.share_summary(request.user, admin, '')
    except ValidationError as error:
        for text in error.messages:
            messages.error(request, text)
    return redirect('followup:report', pk=pk)


@login_required
def family_summary(request, pk):
    admin = get_object_or_404(ProbeAdministration, pk=pk)
    data = services.family_summary(request.user, admin)
    return render(request, 'followup/family_summary.html', {'summary': data})


@login_required
def coaching_create(request, child_id):
    child = clinician_child(request.user, child_id)
    form = CoachingForm(request.POST or None, child=child, initial={'instruction_language': get_language()})
    if request.method == 'POST' and form.is_valid():
        try:
            coaching = services.create_coaching(request.user, child, form.cleaned_data)
            return redirect('followup:coaching_detail', pk=coaching.pk)
        except ValidationError as error:
            service_error(form, error)
    return render_form(request, form, _('Prepare caregiver micro-training'), intro=_('Include an example, an accompanied trial and a clinician check of understanding. Write a new instruction to preserve the previous version.'), child=child, back=('followup:index', None))


def coaching_context(request, pk):
    coaching = get_object_or_404(ParentCoaching.objects.select_related('child', 'variety'), pk=pk)
    data = services.coaching_family_data(request.user, coaching)
    professional = professional_children(request.user).filter(pk=coaching.child_id).exists()
    feedback = coaching.home_feedback.all()
    if not professional:
        feedback = feedback.filter(author=request.user)
    participation_labels = {'completed': _('Completed'), 'partial': _('Partial'), 'stopped': _('Stopped')}
    difficulty_labels = {'easy': _('Comfortable'), 'help': _('Help needed'), 'difficult': _('Difficult')}
    feedback = list(feedback.order_by('-occurred_at')[:20])
    for entry in feedback:
        entry.participation_label = participation_labels[entry.participation]
        entry.difficulty_label = difficulty_labels[entry.difficulty]
    language = data.get('instruction_language', '')
    return {'coaching': data, 'coaching_id': coaching.pk, 'professional': professional, 'private_note': coaching.clinician_note if professional else None, 'feedback': feedback, 'instruction_language_label': INSTRUCTION_LANGUAGES.get(language, _('Instruction language not recorded')), 'instruction_language_mismatch': bool(language and language != get_language())}


@login_required
def coaching_detail(request, pk):
    return render(request, 'followup/coaching.html', coaching_context(request, pk))


@login_required
def coaching_print(request, pk):
    return render(request, 'followup/coaching_print.html', coaching_context(request, pk))


@login_required
def home_feedback(request, pk):
    coaching = get_object_or_404(ParentCoaching, pk=pk)
    services.coaching_family_data(request.user, coaching)
    form = HomeFeedbackForm(request.POST or None, initial={'key': uuid.uuid4()})
    if request.method == 'POST' and form.is_valid():
        try:
            data = dict(form.cleaned_data)
            key = data.pop('key')
            services.record_home_practice(request.user, coaching, data, key=key)
            messages.success(request, _('Your practice declaration has been saved for your clinician. It does not rate pronunciation.'))
            return redirect('followup:coaching_detail', pk=pk)
        except ValidationError as error:
            service_error(form, error)
    return render_form(request, form, _('Tell your clinician about off-screen practice'), intro=_('Describe participation and the support used. A practice declaration is separate from a clinician-rated production observation.'), back=('followup:coaching_detail', pk))
