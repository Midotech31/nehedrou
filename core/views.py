import hashlib
import secrets
import uuid
from datetime import timedelta
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction, IntegrityError
from django.db.models import Count, Q, Prefetch
from django.db.models.functions import TruncDate
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from care.models import Child, FamilyLink, Program, ProgramItem, PracticeSession, Observation, PracticeRun, PracticeRunTask, ProgramFeedback
from catalog.models import Activity, Variety
from .access import membership, manager, visible_children, visible_programs, clinician_child, professional_children
from .forms import SignupForm, InviteSignupForm, ChildForm, ProgramForm, InvitationForm, PracticeForm, ObservationForm, PreferencesForm, DemoPracticeForm, FamilyFeedbackForm, HistoryFilterForm
from .models import Organization, Membership, Entitlement, Invitation, PrivacyRequest
from .services import audit, check_entitlement, create_program, accept_invitation, record_practice, issue_and_deliver_invitation, lock_clinical_child, publish_feedback
from .reserves import activity_is_reserved, reserved_activity_ids, family_catalog_exclusions

def home(request):
    return render(request, 'home.html')


def demo_activity(request):
    """Static public preview, unavailable outside demonstration mode.

    No catalogue version, child, clinical record or session is read or written.
    The examples are interface illustrations, not therapeutic content.
    """
    if not settings.DEMO_MODE:
        raise Http404
    if request.method not in ['GET', 'HEAD', 'POST']:
        from django.http import HttpResponseNotAllowed
        return HttpResponseNotAllowed(['GET', 'HEAD', 'POST'])
    from django.utils.translation import get_language
    examples = {
        'fr': ('chat', 'rat', 'cat', 'rat', _('French · illustrative contrast')),
        'en': ('coat', 'goat', 'coat', 'goat', _('English · illustrative contrast')),
        'ar': ('دار', 'نار', 'house', 'fire', _('Algerian Darja · local proposal awaiting review')),
    }
    word_a, word_b, image_a, image_b, example_variety = examples.get(get_language(), examples['fr'])
    form = DemoPracticeForm(request.POST if request.method == 'POST' else None)
    summary = None
    if request.method == 'POST' and form.is_valid():
        summary = {
            'completion': dict(form.fields['completion'].choices)[form.cleaned_data['completion']],
            'parent_report': dict(form.fields['parent_report'].choices)[form.cleaned_data['parent_report']],
            'answer': _('Stopped · no answer counted') if form.cleaned_data['completion'] == 'stopped' else _('Matching picture selected') if form.cleaned_data['answer'] == 'a' else _('A different picture selected'),
        }
    from catalog.content_catalog import public_example
    example = public_example(get_language()) or {}
    guide = example.get('practice_guide', {}).get(get_language(), {})
    response = render(request, 'demo_activity.html', {'form': form, 'summary': summary, 'word_a': word_a, 'word_b': word_b, 'image_a': f'editorial/{image_a}.svg', 'image_b': f'editorial/{image_b}.svg', 'example_variety': example_variety, 'sample_guide': guide, 'sample_sources': example.get('evidence_sources', [])})
    from django.utils.cache import patch_cache_control
    patch_cache_control(response, no_store=True)
    return response


def signup(request):
    from django.utils.translation import get_language
    form = SignupForm(request.POST or None, initial={'instruction_language': get_language()})
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = form.save()
            org = Organization.objects.create(name=form.cleaned_data['practice_name'])
            Membership.objects.create(user=user, organization=org, role='owner')
            Entitlement.objects.create(organization=org, status='active' if settings.DEMO_MODE else 'expired', expires_at=timezone.now() + timedelta(days=30) if settings.DEMO_MODE else timezone.now())
            audit(user, 'practice.created', org, org)
        login(request, user)
        return redirect('dashboard')
    return render(request, 'form.html', {'form': form, 'title': _('Create your practice'), 'submit': _('Create account')})

@login_required
def dashboard(request):
    member = membership(request)
    if not member:
        from catalog.models import EditorialGrant
        if EditorialGrant.objects.filter(user=request.user).exists():
            return redirect('editorial_index')
        if request.user.has_perm('core.manage_entitlements'):
            return redirect('billing_index')
    programs = visible_programs(request.user)
    children = visible_children(request.user)
    if member:
        programs = programs.filter(organization=member.organization)
        children = children.filter(organization=member.organization)
    sessions = PracticeSession.objects.filter(item__program__in=programs).select_related('item__program__child', 'user')
    sessions = sessions.exclude(item__activity_id__in=family_catalog_exclusions(request.user, Activity.objects.all()))
    today = timezone.localdate()
    start = today - timedelta(days=6)
    daily = dict(sessions.filter(created_at__date__gte=start).annotate(day=TruncDate('created_at')).values('day').annotate(total=Count('pk')).values_list('day', 'total'))
    peak = max(daily.values(), default=1) or 1
    week = [{'day': start + timedelta(days=i), 'total': daily.get(start + timedelta(days=i), 0), 'height': round(daily.get(start + timedelta(days=i), 0) / peak * 100)} for i in range(7)]
    active = programs.filter(state='active', child__active=True).annotate(activity_count=Count('items', distinct=True), report_count=Count('items__sessions', distinct=True))
    waiting = active.filter(report_count=0).count()
    cards = list(active.order_by('-created_at')[:6])
    for program in cards:
        available = program.items.filter(activity__state='published').select_related('activity')
        if not settings.DEMO_MODE:
            available = available.filter(activity__is_demo=False)
        reserved = reserved_activity_ids(program.child, [i.activity for i in available])
        program.first_available = next((item for item in available if item.activity.usable and item.activity_id not in reserved and item.activity.instructions.get(request.user.instruction_language)), None)
        program.last_report = sessions.filter(item__program=program).order_by('-created_at').first()
        program.latest_feedback = program.family_feedback.select_related('author').first()
        program.current_run = program.practice_runs.filter(user=request.user, state='active').first()
        program.run_available = not reserved and all(i.activity.usable and i.activity.instructions.get(request.user.instruction_language) for i in program.items.select_related('activity')) and program.items.exists()
    weekly = sessions.filter(created_at__date__gte=start)
    attention = list(active.annotate(help_count=Count('items__sessions', filter=Q(items__sessions__created_at__date__gte=start) & ~Q(items__sessions__parent_report='easy'), distinct=True), stopped_count=Count('items__sessions', filter=Q(items__sessions__created_at__date__gte=start, items__sessions__completion='stopped'), distinct=True)).filter(Q(help_count__gt=0) | Q(stopped_count__gt=0)).order_by('-help_count')[:6]) if member else []
    return render(request, 'dashboard.html', {'first_child': children.filter(active=True).order_by('created_at').first(), 'children_count': children.filter(active=True).count(), 'program_count': active.count(), 'sessions_count': sessions.count(), 'programs': cards, 'recent_sessions': sessions.order_by('-created_at')[:6], 'week': week, 'week_total': sum(daily.values()), 'weekly_help': weekly.exclude(parent_report='easy').count(), 'weekly_stopped': weekly.filter(completion='stopped').count(), 'attention_programs': attention, 'waiting_count': waiting, 'today': today})

@login_required
@require_POST
def switch_practice(request):
    member = get_object_or_404(Membership, pk=request.POST.get('membership'), user=request.user, active=True)
    request.session['organization'] = str(member.organization_id)
    return redirect('dashboard')

@login_required
def children(request):
    member = membership(request)
    qs = visible_children(request.user).prefetch_related('varieties')
    if member:
        qs = qs.filter(organization=member.organization)
    from django.core.paginator import Paginator
    query = request.GET.get('q', '').strip()[:100]
    status = request.GET.get('status', 'active')
    if query:
        qs = qs.filter(code__icontains=query)
    if status in ['active', 'archived']:
        qs = qs.filter(active=status == 'active')
    qs = qs.annotate(program_count=Count('programs', filter=Q(programs__state='active'), distinct=True))
    return render(request, 'children.html', {'page': Paginator(qs.order_by('code'), 20).get_page(request.GET.get('page')), 'query': query, 'selected_status': status, 'result_count': qs.count()})

@login_required
def child_create(request):
    member = membership(request)
    if not member:
        raise Http404
    instance = Child(organization=member.organization, responsible=request.user)
    form = ChildForm(request.POST or None, instance=instance)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                org = Organization.objects.select_for_update().get(pk=member.organization_id)
                check_entitlement(org, creating_child=True)
                child = form.save()
                audit(request.user, 'child.created', child, org)
            return redirect('child_detail', pk=child.pk)
        except ValidationError as error:
            form.add_error(None, error)
    return render(request, 'form.html', {'form': form, 'title': _('Add a child profile'), 'submit': _('Save profile')})

@login_required
def child_detail(request, pk):
    child = get_object_or_404(visible_children(request.user).prefetch_related('varieties'), pk=pk)
    professional = professional_children(request.user).filter(pk=pk).exists()
    form = InvitationForm(request.POST or None)
    if request.method == 'POST':
        if not professional:
            raise Http404
        if form.is_valid():
            try:
                invitation = issue_and_deliver_invitation(request.user, child.organization, child, form.cleaned_data['email'])
                invitation_message(request, invitation)
                return redirect('child_detail', pk=pk)
            except ValidationError as error:
                form.add_error(None, error)
    return render(request, 'child_detail.html', {'child': child, 'professional': professional, 'form': form, 'programs': child.programs.select_related('variety').order_by('-created_at'), 'links': child.family_links.filter(active=True).select_related('user') if professional else [], 'invitations': child.invitation_set.filter(revoked=False, used_at__isnull=True) if professional else []})

@login_required
@require_POST
def archive_child(request, pk):
    child = clinician_child(request.user, pk)
    try:
        with transaction.atomic():
            child = lock_clinical_child(request.user, child)
            child.active = False
            child.save()
            audit(request.user, 'child.archived', child, child.organization)
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    return redirect('child_detail', pk=pk)

@login_required
@require_POST
def revoke_link(request, pk):
    link = get_object_or_404(FamilyLink, pk=pk, child__in=professional_children(request.user))
    with transaction.atomic():
        lock_clinical_child(request.user, link.child)
        link.active = False
        link.save()
        audit(request.user, 'family.revoked', link, link.child.organization)
    return redirect('child_detail', pk=link.child_id)

@login_required
@require_POST
def revoke_invite(request, pk):
    invite = get_object_or_404(Invitation, pk=pk, child__in=professional_children(request.user))
    invite.revoked = True
    invite.save()
    audit(request.user, 'invitation.revoked', invite, invite.organization)
    return redirect('child_detail', pk=invite.child_id)

def invite(request, token):
    invitation = get_object_or_404(Invitation, token_hash=hashlib.sha256(token.encode()).hexdigest())
    if not invitation.available:
        return render(request, 'notice.html', {'title': _('Invitation unavailable'), 'body': _('Ask your clinician for a new invitation.')}, status=410)
    from .models import User
    existing_account = User.objects.filter(email__iexact=invitation.email).exists()
    form = InviteSignupForm(request.POST or None) if not request.user.is_authenticated and not existing_account else None
    if request.method == 'POST':
        if request.user.is_authenticated:
            try:
                accept_invitation(request.user, token)
                return redirect('dashboard')
            except ValidationError as error:
                messages.error(request, ' '.join(error.messages))
        elif form and form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save(commit=False)
                    user.email = invitation.email
                    user.save()
                    accept_invitation(user, token)
                login(request, user)
                return redirect('dashboard')
            except ValidationError as error:
                form.add_error(None, error)
            except IntegrityError:
                form.add_error(None, _('An account already exists. Sign in to accept your invitation.'))
    return render(request, 'invite.html', {'form': form, 'existing_account': existing_account})

@login_required
def library(request):
    from catalog.content_catalog import current_catalog
    qs = Activity.objects.filter(state='published').select_related('variety')
    if not settings.DEMO_MODE:
        qs = qs.filter(is_demo=False)
    qs = current_catalog(qs)
    qs = qs.exclude(pk__in=family_catalog_exclusions(request.user, qs))
    language = request.GET.get('content_language', '')
    if language in dict(settings.LANGUAGES):
        qs = qs.filter(variety__language=language)
    code = request.GET.get('variety', '')
    if code:
        qs = qs.filter(variety__code=code)
    query = request.GET.get('q', '').strip()[:100]
    if query:
        qs = qs.filter(Q(title__icontains=query) | Q(contrast__icontains=query))
    from django.core.paginator import Paginator
    return render(request, 'library.html', {'page': Paginator(qs.order_by('title'), 12).get_page(request.GET.get('page')), 'varieties': Variety.objects.all(), 'selected': code, 'query': query, 'content_language': language, 'result_count': qs.count()})

@login_required
def activity_detail(request, pk):
    activity = get_object_or_404(Activity.objects.select_related('variety'), pk=pk, state='published')
    if activity.is_demo and not settings.DEMO_MODE:
        raise Http404
    if activity.pk in family_catalog_exclusions(request.user, [activity]):
        raise Http404
    return render(request, 'activity_detail.html', {'activity': activity, 'instruction': activity.instructions.get(request.user.instruction_language), 'missing_instruction': not activity.instructions.get(request.user.instruction_language)})

@login_required
def program_create(request, pk):
    child = clinician_child(request.user, pk)
    form = ProgramForm(request.POST or None, child=child)
    preview = None
    if request.method == 'POST' and form.is_valid():
        if request.POST.get('action') == 'preview':
            preview = form.cleaned_data
        else:
            try:
                program = create_program(request.user, child, form.cleaned_data)
                return redirect('program_detail', pk=program.pk)
            except ValidationError as error:
                form.add_error(None, error)
    return render(request, 'program_builder.html', {'form': form, 'preview': preview, 'child': child, 'activities': form.fields['activities'].queryset, 'selected_activities': [str(pk) for pk in (form['activities'].value() or [])], 'title': _('Create a program'), 'submit': _('Assign program')})

@login_required
def program_detail(request, pk):
    program = get_object_or_404(visible_programs(request.user), pk=pk)
    professional = professional_children(request.user).filter(pk=program.child_id).exists()
    form = ObservationForm(request.POST or None)
    if request.method == 'POST':
        if not professional:
            raise Http404
        if form.is_valid():
            try:
                with transaction.atomic():
                    lock_clinical_child(request.user, program.child)
                    observation = form.save(commit=False)
                    observation.program = program
                    observation.author = request.user
                    observation.save()
                    audit(request.user, 'observation.created', observation, program.organization)
                return redirect('program_detail', pk=pk)
            except ValidationError as error:
                form.add_error(None, error)
    sessions = PracticeSession.objects.filter(item__program=program).select_related('user', 'item__activity').order_by('-created_at', '-pk')
    stats = sessions.aggregate(attempts=Count('pk'), answered=Count('pk', filter=Q(correct__isnull=False)), correct=Count('pk', filter=Q(correct=True)), stopped=Count('pk', filter=Q(completion='stopped')))
    items = list(program.items.select_related('activity'))
    blocked_ids = reserved_activity_ids(program.child, [i.activity for i in items])
    if not professional:
        items = [i for i in items if i.activity_id not in blocked_ids]
        sessions = sessions.exclude(item__activity_id__in=blocked_ids)
    for item in items:
        item.usable = item.activity.usable and item.activity_id not in blocked_ids
    runs = program.practice_runs.select_related('user').annotate(task_count=Count('tasks', distinct=True), reported_count=Count('tasks__report', distinct=True))
    if not professional:
        runs = runs.filter(user=request.user)
    return render(request, 'program_detail.html', {'program': program, 'items': items, 'sessions': sessions[:6], 'stats': stats, 'professional': professional, 'observations': program.observations.select_related('author') if professional else [], 'form': form,
        'family_feedback': program.family_feedback.select_related('author')[:3], 'practice_runs': runs.order_by('-started_at', '-pk')[:5], 'current_run': program.practice_runs.filter(user=request.user, state='active').first(),
        'run_available': bool(items) and not blocked_ids and program.child.active and program.state == 'active' and all(i.usable and i.activity.instructions.get(request.user.instruction_language) for i in items)})

@login_required
def family_feedback_create(request, pk):
    program = get_object_or_404(Program.objects.select_related('child', 'variety'), pk=pk, child__in=professional_children(request.user))
    source = None
    if request.GET.get('report'):
        try:
            source_id = uuid.UUID(request.GET['report'])
        except ValueError:
            raise Http404
        source = get_object_or_404(PracticeSession.objects.select_related('item__activity'), pk=source_id, item__program=program)
    form = FamilyFeedbackForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            publish_feedback(request.user, program, form.cleaned_data['text'], source)
            messages.success(request, _('Your feedback is now visible to the authorized caregivers.'))
            return redirect('report_detail', pk=source.pk) if source else redirect('program_detail', pk=pk)
        except ValidationError as error:
            form.add_error(None, error)
    return render(request, 'family_feedback.html', {'program': program, 'source_report': source, 'form': form})

@login_required
def program_history(request, pk):
    from django.core.paginator import Paginator
    program = get_object_or_404(visible_programs(request.user), pk=pk)
    professional = professional_children(request.user).filter(pk=program.child_id).exists()
    parameters = request.GET.copy()
    parameters.setdefault('kind', 'reports')
    form = HistoryFilterForm(parameters)
    valid = form.is_valid()
    kind = form.cleaned_data.get('kind', 'reports')
    if kind == 'runs':
        records = program.practice_runs.select_related('user').annotate(task_count=Count('tasks', distinct=True), reported_count=Count('tasks__report', distinct=True))
        if not professional:
            records = records.filter(user=request.user)
        date_field, state_field = 'started_at', 'state'
    elif kind == 'feedback':
        records = program.family_feedback.select_related('author', 'source_report__item__activity')
        date_field, state_field = 'created_at', None
    else:
        records = PracticeSession.objects.filter(item__program=program).select_related('user', 'item__activity')
        if not professional:
            records = records.exclude(item__activity_id__in=reserved_activity_ids(program.child, [i.activity for i in program.items.select_related('activity')]))
        date_field, state_field = 'created_at', 'completion'
    unfiltered_count = records.count()
    if valid:
        data = form.cleaned_data
        if state_field and data.get('status'):
            records = records.filter(**{state_field: data['status']})
        if data.get('start'):
            records = records.filter(**{date_field+'__date__gte': data['start']})
        if data.get('end'):
            records = records.filter(**{date_field+'__date__lte': data['end']})
    else:
        records = records.none()
    page = Paginator(records.order_by('-'+date_field, '-pk'), 20).get_page(request.GET.get('page'))
    parameters.pop('page', None)
    return render(request, 'program_history.html', {'program':program, 'page':page, 'form':form, 'record_kind':kind,
        'unfiltered_count':unfiltered_count, 'filter_query':parameters.urlencode(), 'professional':professional})

@login_required
def report_detail(request, pk):
    report = get_object_or_404(PracticeSession.objects.select_related('item__program__child', 'item__program__variety', 'item__activity', 'user'), pk=pk, item__program__in=visible_programs(request.user))
    professional = professional_children(request.user).filter(pk=report.item.program.child_id).exists()
    if not professional and activity_is_reserved(report.item.program.child, report.item.activity):
        return render(request, 'notice.html', {'title': _('Activity unavailable'), 'body': _('Contact your clinician to adjust the program.')}, status=403)
    return render(request, 'report_detail.html', {'report':report, 'professional':professional,
        'feedback':report.clinician_feedback.select_related('author'), 'own_report':report.user_id == request.user.pk})

@login_required
@require_POST
def practice_run_start(request, pk):
    from .practice_runs import start_run
    program = get_object_or_404(visible_programs(request.user), pk=pk)
    try:
        run = start_run(request.user, program)
        return redirect('practice_run_detail', pk=run.pk)
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
        return redirect('program_detail', pk=pk)

@login_required
def practice_run_detail(request, pk):
    from .practice_runs import run_summary
    run = get_object_or_404(PracticeRun.objects.select_related('program__child', 'program__variety', 'user'), pk=pk, program__in=visible_programs(request.user))
    if run.user_id != request.user.pk and not professional_children(request.user).filter(pk=run.program.child_id).exists():
        raise Http404
    if not professional_children(request.user).filter(pk=run.program.child_id).exists() and reserved_activity_ids(run.program.child, [t.item.activity for t in run.tasks.select_related('item__activity')]):
        return render(request, 'notice.html', {'title': _('Activity unavailable'), 'body': _('Contact your clinician to adjust the program.')}, status=403)
    return render(request, 'practice_run.html', run_summary(run, request.user))

@login_required
@require_POST
def practice_run_stop(request, pk):
    from .practice_runs import stop_run
    run = get_object_or_404(PracticeRun.objects.select_related('program'), pk=pk, user=request.user, program__in=visible_programs(request.user))
    try:
        stop_run(request.user, run)
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    return redirect('practice_run_detail', pk=pk)

@login_required
@require_POST
def finish_program(request, pk):
    program = get_object_or_404(Program, pk=pk, child__in=professional_children(request.user))
    with transaction.atomic():
        lock_clinical_child(request.user, program.child)
        program = Program.objects.select_for_update().get(pk=pk)
        program.state = 'completed'
        program.save()
        audit(request.user, 'program.completed', program, program.organization)
    return redirect('program_detail', pk=pk)

@login_required
def practice(request, pk):
    from .practice_runs import task_ticket
    item = get_object_or_404(ProgramItem.objects.select_related('activity', 'program__child'), pk=pk, program__in=visible_programs(request.user))
    if activity_is_reserved(item.program.child, item.activity):
        return render(request, 'notice.html', {'title': _('Activity unavailable'), 'body': _('Contact your clinician to adjust the program.')}, status=410)
    if (not item.program.child.active or not item.activity.usable or item.program.state != 'active') and (request.method != 'POST' or not request.POST.get('ticket')):
        return render(request, 'notice.html', {'title': _('Activity unavailable'), 'body': _('Contact your clinician to adjust the program.')}, status=410)
    task = None
    if request.GET.get('task'):
        try:
            task = get_object_or_404(PracticeRunTask.objects.select_related('run', 'report'), pk=request.GET['task'], item=item, run__user=request.user)
        except ValidationError:
            raise Http404
        if request.method == 'GET':
            report = getattr(task, 'report', None)
            if report:
                return redirect('practice_report', pk=report.pk)
            pending = task.run.tasks.filter(report__isnull=True).order_by('position').first()
            if task.run.state != 'active' or not pending or pending.pk != task.pk:
                return redirect('practice_run_detail', pk=task.run_id)
    ticket_data = task_ticket(task) if task else {'user': request.user.pk, 'item': str(item.pk), 'key': str(uuid.uuid4()), 'target': secrets.choice(['a', 'b'])}
    ticket = signing.dumps(ticket_data, salt='practice')
    form = PracticeForm(request.POST or None, initial={'ticket': ticket})
    def read_ticket(raw):
        loaded = signing.loads(raw, salt='practice', max_age=7200)
        if not isinstance(loaded, dict) or loaded.get('user') != request.user.pk or loaded.get('item') != str(item.pk) or loaded.get('run_task') != (str(task.pk) if task else None) or loaded.get('target') not in ['a', 'b']:
            raise signing.BadSignature
        try:
            uuid.UUID(str(loaded['key']))
        except (KeyError, ValueError, TypeError):
            raise signing.BadSignature
        if task and loaded != task_ticket(task):
            raise signing.BadSignature
        return loaded
    if request.method == 'POST' and form.is_valid():
        try:
            ticket_data = read_ticket(form.cleaned_data['ticket'])
            report = record_practice(request.user, item, form.cleaned_data, ticket_data)
            return redirect('practice_report', pk=report.pk)
        except (signing.BadSignature, KeyError):
            form.add_error(None, _('The activity link has expired. Reload the page.'))
        except ValidationError as error:
            form.add_error(None, error)
    elif request.method == 'POST':
        try:
            ticket_data = read_ticket(request.POST.get('ticket', ''))
        except (signing.BadSignature, KeyError):
            return render(request, 'notice.html', {'title': _('Activity unavailable'), 'body': _('The activity link has expired. Reload the page.')}, status=400)
    if not item.program.child.active or not item.activity.usable or item.program.state != 'active':
        return render(request, 'notice.html', {'title': _('Activity unavailable'), 'body': _('Contact your clinician to adjust the program.')}, status=410)
    instruction = item.activity.instructions.get(request.user.instruction_language)
    if not instruction:
        return render(request, 'notice.html', {'title': _('Instructions unavailable'), 'body': _('Choose another instruction language in your preferences or contact your clinician.')}, status=409)
    target = item.activity.word_a if ticket_data['target'] == 'a' else item.activity.word_b
    audio = item.activity.audio_a if ticket_data['target'] == 'a' else item.activity.audio_b
    return render(request, 'practice.html', {'item': item, 'form': form, 'instruction': instruction, 'target': target, 'audio': audio, 'run_task': task, 'run_count': task.run.tasks.count() if task else None})

@login_required
def practice_report(request, pk):
    from .practice_runs import run_summary
    report = get_object_or_404(PracticeSession.objects.select_related('item__activity', 'item__program__child', 'run_task__run__program__child'), pk=pk, user=request.user, item__program__in=visible_programs(request.user))
    if not professional_children(request.user).filter(pk=report.item.program.child_id).exists() and activity_is_reserved(report.item.program.child, report.item.activity):
        return render(request, 'notice.html', {'title': _('Activity unavailable'), 'body': _('Contact your clinician to adjust the program.')}, status=403)
    context = {'report': report, 'next_item': None}
    if report.run_task_id:
        summary = run_summary(report.run_task.run, request.user)
        context.update(run=summary['run'], next_task_url=summary['resume_url'])
    else:
        # Legacy reports keep their history; never skip a withdrawn next assignment.
        candidate = report.item.program.items.filter(position__gt=report.item.position).select_related('activity').order_by('position').first()
        if candidate and candidate.activity.usable and not activity_is_reserved(report.item.program.child, candidate.activity) and report.item.program.state == 'active' and report.item.program.child.active and report.completion == 'completed':
            context['next_item'] = candidate
    return render(request, 'practice_report.html', context)

@login_required
def print_program(request, pk):
    program = get_object_or_404(visible_programs(request.user), pk=pk)
    items = list(program.items.select_related('activity'))
    blocked_ids = reserved_activity_ids(program.child, [i.activity for i in items])
    if not professional_children(request.user).filter(pk=program.child_id).exists():
        items = [i for i in items if i.activity_id not in blocked_ids]
    for item in items:
        item.usable = item.activity.usable and item.activity_id not in blocked_ids
        item.instruction = item.activity.instructions.get(request.user.instruction_language)
    return render(request, 'print.html', {'program': program, 'items': items, 'instruction_language': request.user.instruction_language})

@login_required
def export_child(request, pk):
    child = get_object_or_404(visible_children(request.user), pk=pk)
    professional = professional_children(request.user).filter(pk=pk).exists()
    programs = []
    runs = PracticeRun.objects.prefetch_related(Prefetch('tasks', queryset=PracticeRunTask.objects.select_related('report').order_by('position'))).order_by('-started_at','-pk')
    if not professional:
        runs = runs.filter(user=request.user)
    feedback = ProgramFeedback.objects.select_related('author').order_by('created_at','pk')
    for program in child.programs.select_related('variety').prefetch_related('items__activity', 'items__sessions', 'observations', Prefetch('practice_runs', queryset=runs, to_attr='export_runs'), Prefetch('family_feedback', queryset=feedback, to_attr='export_feedback')):
        blocked_ids = set() if professional else reserved_activity_ids(child, [i.activity for i in program.items.all()])
        hidden_item_ids = {i.pk for i in program.items.all() if i.activity_id in blocked_ids}
        visible_task_ids = {t.pk for run in program.export_runs for t in run.tasks.all()}
        row = {'id': str(program.pk), 'title': program.title, 'goal': program.goal, 'variety': program.variety.code, 'state': program.state, 'schedule': program.schedule, 'guidance': program.guidance, 'items': []}
        for item in program.items.all():
            if item.activity_id in blocked_ids:
                continue
            row['items'].append({'id': str(item.pk), 'position':item.position, 'activity_id': str(item.activity_id), 'version': item.activity.version, 'title': item.activity.title, 'sessions': [{'id':str(s.pk), 'run_task_id':str(s.run_task_id) if s.run_task_id in visible_task_ids else None, 'at': s.created_at.isoformat(), 'completion': s.completion, 'closed_task_correct': s.correct, 'reporter_role': s.reporter_role, 'parent_report': s.parent_report, 'parent_comment': s.comment, 'declared_support': s.support_used, 'declared_stop_reason': s.stop_reason} for s in item.sessions.all()]})
        row['practice_runs'] = [{'id': str(run.pk), 'state': run.state, 'started_at': run.started_at.isoformat(), 'finished_at': run.finished_at.isoformat() if run.finished_at else None,
            'tasks': [{'id':str(t.pk), 'position': t.position, 'item_id': str(t.item_id), 'report_id': str(t.report.pk) if getattr(t, 'report', None) else None} for t in run.tasks.all() if t.item_id not in hidden_item_ids]} for run in program.export_runs]
        row['family_feedback'] = [{'id':str(f.pk), 'source_report_id':str(f.source_report_id) if f.source_report_id else None, 'at':f.created_at.isoformat(), 'text':f.text, 'author':f.author.username} for f in program.export_feedback]
        if professional:
            row['professional_observations'] = [{'text':o.text, 'created_at':o.created_at} for o in program.observations.all()]
        programs.append(row)
    audit(request.user, 'child.exported', child, child.organization)
    response = JsonResponse({'schema_version':2, 'child': {'code': child.code, 'age_years': child.age_years}, 'programs': programs}, json_dumps_params={'ensure_ascii': False, 'indent': 2})
    response['Content-Disposition'] = 'attachment; filename="nehdrou-export.json"'
    return response

@login_required
def members(request):
    member = manager(request)
    form = InvitationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            invitation = issue_and_deliver_invitation(request.user, member.organization, None, form.cleaned_data['email'], kind='clinician')
            invitation_message(request, invitation)
            return redirect('members')
        except ValidationError as error:
            form.add_error(None, error)
    return render(request, 'members.html', {'form': form, 'members': Membership.objects.filter(organization=member.organization).select_related('user'), 'invitations': Invitation.objects.filter(organization=member.organization, kind='clinician', revoked=False, used_at__isnull=True)})

def invitation_message(request, invitation):
    if invitation.delivery == 'failed':
        messages.error(request, _('Invitation saved, but email delivery failed. Retry from pending invitations.'))
    elif invitation.delivery == 'console':
        messages.info(request, _('Local demonstration: the invitation link is in the server console. No email was sent.'))
    else:
        messages.success(request, _('Invitation handed to the mail service. Receipt is not yet confirmed.'))

@login_required
@require_POST
def resend_invitation(request, pk):
    invitation = get_object_or_404(Invitation, pk=pk)
    if invitation.kind == 'family':
        child = clinician_child(request.user, invitation.child_id)
        destination = reverse('child_detail', args=[child.pk])
    else:
        member = manager(request)
        if invitation.organization_id != member.organization_id:
            raise Http404
        child = None
        destination = reverse('members')
    try:
        replacement = issue_and_deliver_invitation(request.user, invitation.organization, child, invitation.email, kind=invitation.kind, replacing=invitation)
        invitation_message(request, replacement)
    except ValidationError as error:
        messages.error(request, ' '.join(error.messages))
    return redirect(destination)

@login_required
@require_POST
def revoke_member(request, pk):
    member = manager(request)
    target = get_object_or_404(Membership, pk=pk, organization=member.organization)
    if target.user_id == request.user.pk or target.role == 'owner':
        messages.error(request, _('A practice manager cannot be removed here.'))
    else:
        with transaction.atomic():
            Organization.objects.select_for_update().get(pk=member.organization_id)
            manager(request)
            target = Membership.objects.select_for_update().get(pk=target.pk)
            target.active = False
            target.save()
            audit(request.user, 'member.revoked', target, member.organization)
    return redirect('members')

@login_required
def subscription(request):
    member = manager(request)
    return render(request, 'subscription.html', {'entitlement': Entitlement.objects.filter(organization=member.organization).first(), 'used_children': Child.objects.filter(organization=member.organization, active=True).count(), 'used_members': Membership.objects.filter(organization=member.organization, active=True).count()})

@login_required
def preferences(request):
    form = PreferencesForm(request.POST or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, _('Preferences saved. Program language is unchanged.'))
        return redirect('preferences')
    return render(request, 'preferences.html', {'form': form})

@login_required
@require_POST
def privacy_request(request, pk):
    child = get_object_or_404(visible_children(request.user), pk=pk)
    obj = PrivacyRequest.objects.create(organization=child.organization, child=child, requester=request.user, kind='erasure')
    audit(request.user, 'privacy.requested', obj, child.organization)
    messages.success(request, _('Your request has been recorded for manual review by the practice.'))
    return redirect('child_detail', pk=pk)


def help_page(request):
    return render(request, 'help.html')
