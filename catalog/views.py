import mimetypes
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from care.models import ProgramItem
from core.access import visible_programs
from .models import Activity, EditorialGrant, Variety, MediaAsset
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
    return render(request, 'editorial/index.html', {'page': Paginator(qs.order_by('variety__label', 'title', '-version'), 20).get_page(request.GET.get('page')), 'states': Activity._meta.get_field('state').choices, 'varieties': Variety.objects.all(), 'selected_state': state, 'selected': variety, 'can_create': request.user.is_superuser or EditorialGrant.objects.filter(user=request.user, edit=True).exists()})

@login_required
def detail(request, pk):
    activity = get_object_or_404(editorial_activities(request.user).select_related('variety'), pk=pk)
    review_kinds = [kind for kind, capability in [('clinical', 'clinical_review'), ('linguistic', 'linguistic_review')]
                    if allowed(request.user, activity.variety, capability)]
    can_review = bool(review_kinds) and activity.state in ['review', 'approved']
    if request.method == 'POST' and (not can_review or request.POST.get('kind') not in review_kinds):
        raise PermissionDenied
    form = ReviewForm(request.POST or None, instance=None, allowed_kinds=review_kinds)
    if request.method == 'POST' and form.is_valid():
        try:
            review_version(request.user, activity, form.cleaned_data['kind'], form.cleaned_data['approved'], form.cleaned_data['note'])
            return redirect('editorial_detail', pk=pk)
        except ValidationError as error:
            form.add_error(None, error)
    checklist_labels = {'rights': _('Usage rights'), 'population': _('Intended population'), 'image_a': _('First illustration reference'), 'image_b': _('Second illustration reference'), 'audio_a': _('First audio URL'), 'audio_b': _('Second audio URL'), 'transcription_a': _('First word transcription'), 'transcription_b': _('Second word transcription')}
    issues = []
    for field in ['rights', 'population', 'image_a', 'image_b', 'audio_a', 'audio_b', 'transcription_a', 'transcription_b']:
        if not getattr(activity, field):
            issues.append(checklist_labels[field])
    return render(request, 'editorial/detail.html', {'activity': activity, 'form': form, 'issues': issues, 'can_edit': allowed(request.user, activity.variety, 'edit'), 'can_publish': allowed(request.user, activity.variety, 'publish'), 'can_review': can_review, 'reviews': activity.reviews.select_related('reviewer'), 'affected': ProgramItem.objects.filter(activity=activity).count()})

@login_required
def edit(request, pk=None):
    editor(request.user)
    activity = get_object_or_404(editorial_activities(request.user), pk=pk) if pk else Activity()
    if pk and (activity.state != 'draft' or not allowed(request.user, activity.variety, 'edit')):
        raise PermissionDenied
    form = ActivityForm(request.POST or None, instance=activity)
    form.fields['variety'].queryset = Variety.objects.all() if request.user.is_superuser else Variety.objects.filter(editorialgrant__user=request.user, editorialgrant__edit=True)
    if request.method == 'POST' and form.is_valid():
        if not allowed(request.user, form.cleaned_data['variety'], 'edit'):
            raise PermissionDenied
        activity = form.save()
        from core.services import audit
        audit(request.user, 'catalog.draft_saved', activity)
        return redirect('editorial_detail', pk=activity.pk)
    return render(request, 'form.html', {'title': _('Edit content draft'), 'form': form, 'submit': _('Save')})

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
    form = MediaForm(request.POST or None, request.FILES or None, instance=MediaAsset(uploaded_by=request.user))
    if request.method == 'POST' and form.is_valid():
        asset = form.save()
        from core.services import audit
        audit(request.user, 'catalog.media_uploaded', asset)
        return render(request, 'editorial/media.html', {'asset': asset})
    return render(request, 'editorial/upload.html', {'form': form})

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
    public_catalog = available.exists()
    assigned = ProgramItem.objects.filter(activity__in=available, program__in=visible_programs(request.user)).exists()
    if not editorial and not public_catalog and not assigned:
        raise Http404
    if not asset.file.storage.exists(asset.file.name):
        raise Http404
    return FileResponse(asset.file.open('rb'), content_type=mimetypes.guess_type(asset.file.name)[0] or 'application/octet-stream')
