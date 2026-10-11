import mimetypes
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.db.models import Q
from django.http import FileResponse, Http404
from django.db import transaction
import uuid
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from care.models import ProgramItem
from core.access import visible_programs
from .models import Activity, EditorialGrant, Variety, MediaAsset, Review
from .forms import ActivityForm, ReviewForm, MediaForm
from .services import allowed, transition, clone_version, review_version

def editorial_activities(user):
    if user.is_superuser:
        return Activity.objects.all()
    return Activity.objects.filter(variety__editorialgrant__user=user).distinct()

def editor(user):
    if not user.is_superuser and not EditorialGrant.objects.filter(user=user).exists():
        raise Http404

@login_required
def index(request):
    editor(request.user)
    qs = editorial_activities(request.user).select_related('variety')
    state = request.GET.get('state', '')
    if state:
        qs = qs.filter(state=state)
    variety = request.GET.get('variety', '')
    if variety:
        qs = qs.filter(variety__code=variety)
    from django.core.paginator import Paginator
    from .models import DraftWorkingCopy
    from .working import authorize_copy, recover_url
    recoverable, set_aside = [], []
    for copy in DraftWorkingCopy.objects.filter(owner=request.user, committed=False).select_related('activity__variety').order_by('-updated_at'):
        try:
            authorize_copy(request.user, copy)
        except (PermissionDenied, Http404):
            continue
        if copy.dismissed and len(set_aside) >= 20:
            continue
        (set_aside if copy.dismissed else recoverable).append({'id':copy.pk,'title':copy.data.get('title') or _('Untitled working copy'), 'url':recover_url(copy), 'updated_at':copy.updated_at})
    return render(request, 'editorial/index.html', {'recoverable': recoverable, 'set_aside':set_aside, 'page': Paginator(qs.order_by('variety__label', 'title', '-version'), 20).get_page(request.GET.get('page')), 'states': Activity._meta.get_field('state').choices, 'varieties': Variety.objects.all(), 'selected_state': state, 'selected': variety, 'can_create': request.user.is_superuser or EditorialGrant.objects.filter(user=request.user, edit=True).exists()})

@login_required
def detail(request, pk):
    activity = get_object_or_404(editorial_activities(request.user).select_related('variety'), pk=pk)
    review_kinds = [kind for kind, capability in [('clinical', 'clinical_review'), ('linguistic', 'linguistic_review')]
                    if allowed(request.user, activity.variety, capability)]
    can_review = bool(review_kinds) and activity.state in ['review', 'approved']
    if request.method == 'POST' and (not can_review or request.POST.get('kind') not in review_kinds):
        raise PermissionDenied
    form = ReviewForm(request.POST or None, instance=Review(activity=activity, reviewer=request.user), allowed_kinds=review_kinds)
    if request.method == 'POST' and form.is_valid():
        try:
            review_version(request.user, activity, form.cleaned_data['kind'], form.cleaned_data['approved'], form.cleaned_data['note'])
            return redirect('editorial_detail', pk=pk)
        except ValidationError as error:
            form.add_error(None, error)
    from .readiness import activity_readiness
    readiness = activity_readiness(activity, require_availability=True) if not activity.is_demo else {'ready': True, 'reasons': []}
    checklist_labels = {'rights': _('Usage rights'), 'population': _('Intended population'), 'image_a': _('First illustration reference'), 'image_b': _('Second illustration reference'), 'audio_a': _('First audio URL'), 'audio_b': _('Second audio URL'), 'transcription_a': _('First word transcription'), 'transcription_b': _('Second word transcription')}
    issues = []
    for field in ['rights', 'population', 'image_a', 'image_b', 'audio_a', 'audio_b', 'transcription_a', 'transcription_b']:
        if not getattr(activity, field):
            issues.append(checklist_labels[field])
    return render(request, 'editorial/detail.html', {'activity': activity, 'form': form, 'issues': issues, 'can_edit': allowed(request.user, activity.variety, 'edit'), 'can_publish': allowed(request.user, activity.variety, 'publish'), 'can_review': can_review, 'reviews': activity.reviews.select_related('reviewer'), 'affected': ProgramItem.objects.filter(activity=activity).count(), 'readiness': readiness, 'content_digest': activity.fingerprint()})

@login_required
def edit(request, pk=None):
    editor(request.user)
    activity = get_object_or_404(editorial_activities(request.user), pk=pk) if pk else Activity()
    if pk and (activity.state != 'draft' or not allowed(request.user, activity.variety, 'edit')):
        raise PermissionDenied
    if not request.user.is_superuser and not EditorialGrant.objects.filter(user=request.user, edit=True).exists():
        raise PermissionDenied
    advanced = request.GET.get('advanced') == '1'
    from .working import resume_copy, recover_url
    working = resume_copy(request, activity)
    base_digest = working.base_digest if working else (activity.fingerprint() if pk else '')
    if advanced:
        form = ActivityForm(request.POST or None, instance=activity)
    else:
        from .authoring import ActivityAuthoringForm
        form = ActivityAuthoringForm(request.POST or None, instance=activity, actor=request.user)
        form.language_sections.sort(key=lambda section: section['code'] != request.LANGUAGE_CODE)
        if working and request.method != 'POST':
            form.initial.update(working.data)
    form.fields['variety'].queryset = Variety.objects.all() if request.user.is_superuser else Variety.objects.filter(editorialgrant__user=request.user, editorialgrant__edit=True)
    if request.method == 'POST' and form.is_valid():
        if not allowed(request.user, form.cleaned_data['variety'], 'edit'):
            raise PermissionDenied
        with transaction.atomic():
            current = Activity.objects.select_for_update().get(pk=pk) if pk else None
            baseline = request.POST.get('content_baseline')
            if current and (current.state != 'draft' or (baseline and baseline != current.fingerprint())):
                form.add_error(None, _('This draft changed in another session. Open the current version before saving your changes.'))
            else:
                if not allowed(request.user, form.cleaned_data['variety'], 'edit'):
                    raise PermissionDenied
                activity = form.save()
                from core.services import audit
                audit(request.user, 'catalog.draft_saved', activity)
                if working:
                    working.committed = True
                    working.save(update_fields=['committed', 'updated_at'])
                return redirect('editorial_detail', pk=activity.pk)
    if not advanced:
        for section in form.language_sections:
            section['has_errors'] = bool(section['instructions'].errors or any(field.errors for field in section['fields']))
        form.source_errors = [index for index, row in enumerate(form.source_rows) if any(field.errors for field in row)]
    from .starters import starting_structures
    from django.urls import reverse
    working_id = working.pk if working else uuid.uuid4()
    config = {
        'fields':list(form.fields), 'autosave_url':reverse('editorial_autosave', args=[working_id]),
        'resume_url':recover_url(working) if working else '', 'revision':working.revision if working else 0, 'activity':str(activity.pk) if pk else '',
        'base_digest':base_digest, 'language':request.LANGUAGE_CODE,
        'images': {str(asset.pk):reverse('editorial_media', args=[asset.pk]) for asset in form.fields['choose_image_a'].queryset} if not advanced else {},
        'starters':starting_structures(request.LANGUAGE_CODE),
        'labels': {'step':_('Step'), 'empty_word':_('Your word or prompt'), 'empty_instruction':_('Your family instruction will appear here.'),
                   'essentials':_('Essentials completed'), 'saving':_('Saving your working copy…'), 'saved':_('Working copy saved. The activity is not published.'),
                   'capacity':_('You have 30 active working copies. Save an activity or set a copy aside in the editorial workspace.'), 'unchanged':_('No unsaved changes.'), 'pending':_('Changes waiting to be saved.'), 'failed':_('Working copy not saved. Keep this page open and retry.'),
                   'conflict':_('Another session or the source changed. Open your saved copy to reconcile changes.')}
    }
    response = render(request, 'form.html' if advanced else 'editorial/author.html', {'title': _('Edit content draft') if pk else _('Create an activity from scratch'), 'form': form, 'submit': _('Save draft'), 'activity': activity, 'activity_add': not pk, 'working_id':working_id, 'base_digest':base_digest, 'author_config':config})
    response['Cache-Control'] = 'private, no-store'
    return response

@login_required
@require_POST
def change_state(request, pk):
    get_object_or_404(editorial_activities(request.user), pk=pk)
    try:
        transition(request.user, pk, request.POST.get('state', ''))
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    return redirect('editorial_detail', pk=pk)

@login_required
@require_POST
def clone(request, pk):
    source = get_object_or_404(editorial_activities(request.user), pk=pk)
    activity = clone_version(request.user, source)
    return redirect('editorial_edit', pk=activity.pk)

@login_required
def upload(request):
    editor(request.user)
    if not request.user.is_superuser and not EditorialGrant.objects.filter(user=request.user, edit=True).exists():
        raise PermissionDenied
    draft = None
    draft_id = request.GET.get('draft') or request.POST.get('draft')
    if draft_id:
        from uuid import UUID
        try: draft_id = UUID(draft_id)
        except ValueError: raise Http404
        draft = get_object_or_404(editorial_activities(request.user), pk=draft_id, state='draft')
        if not allowed(request.user, draft.variety, 'edit'): raise PermissionDenied
    from .media_authoring import MediaAuthoringForm
    media_form = MediaForm if 'provenance' in request.POST or request.GET.get('advanced') == '1' else MediaAuthoringForm
    form = media_form(request.POST or None, request.FILES or None, instance=MediaAsset(uploaded_by=request.user))
    from qualification.models import EvidenceDocument
    form.fields['rights_evidence'].queryset = EvidenceDocument.objects.filter(category='rights', revoked=False) if request.user.is_superuser else EvidenceDocument.objects.filter(category='rights', revoked=False, variety__editorialgrant__user=request.user).distinct()
    if request.method == 'POST' and form.is_valid():
        asset = form.save()
        from core.services import audit
        audit(request.user, 'catalog.media_uploaded', asset)
        return render(request, 'editorial/media.html', {'asset': asset, 'draft': draft})
    return render(request, 'editorial/upload.html', {'form': form, 'draft': draft})

@login_required
def media(request, pk):
    asset = get_object_or_404(MediaAsset, pk=pk)
    reference = 'editorial/asset-' + str(asset.pk)
    audio_suffix = '/media/' + str(asset.pk) + '/'
    activities = Activity.objects.filter(Q(image_a=reference) | Q(image_b=reference) | Q(audio_a__endswith=audio_suffix) | Q(audio_b__endswith=audio_suffix))
    editorial = request.user.is_superuser or EditorialGrant.objects.filter(user=request.user, variety__activity__in=activities).exists() or asset.uploaded_by_id == request.user.pk
    available = activities.filter(state='published')
    if not settings.DEMO_MODE:
        available = available.filter(is_demo=False)
    if not editorial:
        from core.reserves import family_catalog_exclusions
        available = available.exclude(pk__in=family_catalog_exclusions(request.user, available))
    public_catalog = available.exists()
    assigned = ProgramItem.objects.filter(activity__in=available, program__in=visible_programs(request.user)).exists()
    if not editorial and not public_catalog and not assigned:
        raise Http404
    if not asset.intact:
        raise Http404
    if not editorial and not any(activity.usable for activity in available):
        raise Http404
    return FileResponse(asset.file.open('rb'), content_type=mimetypes.guess_type(asset.file.name)[0] or 'application/octet-stream')
