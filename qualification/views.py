import hashlib
from io import BytesIO
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from catalog.models import Variety, EditorialGrant, MediaAsset
from catalog.services import allowed
from core.services import audit
from core.storage_health import STORAGE_ERRORS
from core.storage_io import read_bounded
from .models import EvidenceDocument, ReviewerCompetence, AvailabilityDecision, LexicalPack, LexicalCandidate, FamiliarityStudy, PackReview
from .forms import EvidenceForm, CompetenceForm, AvailabilityForm, PackForm, CandidateForm, FamiliarityForm, PackReviewForm, OpeningTargetForm, AvailabilityRevocationForm
from .services import change_pack_state, clone_pack, pack_readiness_reasons

def varieties(user, capability=None):
    if user.is_superuser:
        return Variety.objects.all()
    filters = {'editorialgrant__user':user}
    if capability:
        filters['editorialgrant__'+capability] = True
    return Variety.objects.filter(**filters).distinct()

def require_workspace(user):
    if not varieties(user).exists():
        raise PermissionDenied

def private_documents(user):
    return EvidenceDocument.objects.filter(variety__in=varieties(user)).select_related('variety')

def form_page(request,form,title):
    return render(request,'form.html',{'form':form,'title':title,'submit':_('Save')})

@login_required
def index(request):
    require_workspace(request.user)
    visible = varieties(request.user)
    return render(request,'qualification/index.html',{'packs':LexicalPack.objects.filter(variety__in=visible).select_related('variety'), 'competences':ReviewerCompetence.objects.filter(user=request.user).select_related('variety'), 'documents':private_documents(request.user).order_by('-created_at')[:30], 'can_edit':varieties(request.user,'edit').exists(), 'can_publish':varieties(request.user,'publish').exists()})

@login_required
def evidence_upload(request):
    if not varieties(request.user,'edit').exists():
        raise PermissionDenied
    form = EvidenceForm(request.POST or None, request.FILES or None, instance=EvidenceDocument(uploaded_by=request.user))
    form.fields['variety'].queryset = varieties(request.user,'edit')
    if request.method=='POST' and form.is_valid():
        document = form.save()
        audit(request.user,'qualification.evidence_uploaded',document)
        return redirect('qualification:index')
    return form_page(request,form,_('Upload private evidence'))

@login_required
def evidence_file(request,pk):
    document = get_object_or_404(private_documents(request.user),pk=pk)
    if document.revoked or not document.file or not document.sha256:
        raise Http404
    # Verify the exact bounded bytes that will be served; a request-cached digest
    # or a second storage open cannot stand in for this delivery check.
    limit = 15 * 1024 * 1024
    try:
        data = read_bounded(document.file.storage, document.file.name, limit)
    except STORAGE_ERRORS:
        raise Http404 from None
    if len(data) > limit or hashlib.sha256(data).hexdigest() != document.sha256:
        raise Http404
    response = FileResponse(BytesIO(data),as_attachment=True,filename='evidence-'+str(document.pk)+'.'+document.file.name.rsplit('.',1)[-1],content_type='application/octet-stream')
    if request.method == 'HEAD':
        response.streaming_content = ()
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response

@login_required
@require_POST
def revoke_evidence(request,pk):
    document = get_object_or_404(private_documents(request.user),pk=pk)
    if not allowed(request.user,document.variety,'publish') and document.uploaded_by_id != request.user.pk:
        raise PermissionDenied
    document.revoked = True
    document.revocation_reason = request.POST.get('reason','').strip()
    try:
        document.save()
        audit(request.user,'qualification.evidence_revoked',document)
    except ValidationError as exc:
        from django.contrib import messages
        messages.error(request,' '.join(exc.messages))
    return redirect('qualification:index')

@login_required
def competence(request,pk=None):
    require_workspace(request.user)
    obj = get_object_or_404(ReviewerCompetence,user=request.user,pk=pk) if pk else ReviewerCompetence(user=request.user)
    form = CompetenceForm(request.POST or None,instance=obj)
    form.fields['variety'].queryset = varieties(request.user)
    form.fields['evidence'].queryset = private_documents(request.user)
    if request.method=='POST' and form.is_valid():
        obj = form.save()
        audit(request.user,'qualification.competence_declared',obj)
        return redirect('qualification:index')
    return form_page(request,form,_('Declare reviewer experience'))

@login_required
def availability(request):
    if not varieties(request.user).exists():
        if request.method != 'GET':
            raise PermissionDenied
        from catalog.models import Activity
        from followup.models import ProbeDefinition
        from .services import availability_for
        from .models import MODULES
        rows = []
        for variety in Variety.objects.order_by('code'):
            for module,label in MODULES:
                queryset = Activity.objects.filter(variety=variety,is_demo=False) if module=='practice' else ProbeDefinition.objects.filter(variety=variety,is_demo=False,organization__isnull=True)
                available_count = sum(1 for content in queryset.filter(state='published') if availability_for(module,variety,content.fingerprint())['available'] and (content.usable if module=='practice' else content.ready))
                rows.append({'variety':variety,'module_label':label,'draft_count':queryset.exclude(state__in=['published','withdrawn']).count(),'available_count':available_count})
        return render(request,'qualification/status.html',{'rows':rows})
    from .opening import resolve_target, record_decision, ContentChanged, decision_target_display, target_label, decision_queryset
    from django.urls import reverse
    from urllib.parse import urlencode
    can_publish = varieties(request.user, 'publish').exists()
    if request.method == 'POST' and not can_publish:
        raise PermissionDenied
    picker = OpeningTargetForm(request.POST if request.method == 'POST' else request.GET or None, actor=request.user)
    form, target_info = None, None
    status = 200
    if picker.is_bound and picker.is_valid():
        key = picker.cleaned_data['target']
        module, content = resolve_target(request.user, key)
        form = AvailabilityForm(request.POST if request.method == 'POST' else None,
            actor=request.user, content=content, module=module)
        target_info = {'label': target_label(module, content), 'digest': content.fingerprint(),
            'url': reverse('editorial_detail' if module == 'practice' else 'followup:definition_detail', args=[content.pk]),
            'prepare_url': reverse('qualification:availability') + '?' + urlencode({'target': key}),
            'documents': form.fields['documents'].queryset}
        if request.method == 'POST' and form.is_valid():
            try:
                record_decision(request.user, key, form.cleaned_data['expected_version'], form.cleaned_data)
                return redirect('qualification:availability')
            except ContentChanged as error:
                form.add_error(None, error)
                status = 409
            except ValidationError as error:
                form.add_error(None, error)
    decisions = list(decision_queryset(request.user).select_related('variety', 'decided_by')[:60])
    for decision in decisions:
        decision.target_display = decision_target_display(request.user, decision)
        decision.can_revoke = decision.status != 'revoked' and allowed(request.user, decision.variety, 'publish')
    return render(request, 'qualification/availability.html', {'form': form, 'picker': picker,
        'target_info': target_info, 'decisions': decisions, 'can_publish': can_publish}, status=status)


@login_required
@require_POST
def availability_revoke(request, pk):
    from .opening import revoke_decision, decision_queryset
    previous = get_object_or_404(decision_queryset(request.user, publish=True), pk=pk)
    form = AvailabilityRevocationForm(request.POST)
    if form.is_valid():
        try:
            revoke_decision(request.user, previous.pk, form.cleaned_data['reason'])
            return redirect('qualification:availability')
        except ValidationError as error:
            form.add_error(None, error)
    return form_page(request, form, _('Revoke availability decision'))

@login_required
def pack_edit(request,pk=None):
    require_workspace(request.user)
    obj = get_object_or_404(LexicalPack,variety__in=varieties(request.user,'edit'),pk=pk) if pk else LexicalPack(created_by=request.user)
    if pk and obj.state!='draft':
        raise PermissionDenied
    form = PackForm(request.POST or None,instance=obj)
    form.fields['variety'].queryset = varieties(request.user,'edit')
    if request.method=='POST' and form.is_valid():
        obj = form.save()
        audit(request.user,'qualification.pack_saved',obj)
        return redirect('qualification:pack_detail',pk=obj.pk)
    return form_page(request,form,_('Define a regional lexical pack'))

@login_required
def pack_detail(request,pk):
    pack = get_object_or_404(LexicalPack,variety__in=varieties(request.user),pk=pk)
    kinds = [kind for kind,cap in [('clinical','clinical_review'),('linguistic','linguistic_review')] if allowed(request.user,pack.variety,cap)]
    form = PackReviewForm(request.POST or None,instance=PackReview(pack=pack,reviewer=request.user))
    form.fields['kind'].choices = [choice for choice in form.fields['kind'].choices if choice[0] in kinds]
    if request.method=='POST':
        if pack.state!='review' or request.POST.get('kind') not in kinds:
            raise PermissionDenied
        if form.is_valid():
            review = form.save()
            audit(request.user,'qualification.pack_reviewed',review)
            return redirect('qualification:pack_detail',pk=pk)
    return render(request,'qualification/pack.html',{'pack':pack,'candidates':pack.candidates.prefetch_related('familiarity'), 'form':form, 'can_edit':allowed(request.user,pack.variety,'edit'), 'can_publish':allowed(request.user,pack.variety,'publish'), 'can_review':bool(kinds) and pack.state=='review', 'issues':pack_readiness_reasons(pack),'digest':pack.fingerprint(),'reviews':pack.reviews.select_related('reviewer')})

@login_required
@require_POST
def pack_transition(request,pk):
    get_object_or_404(LexicalPack,variety__in=varieties(request.user),pk=pk)
    try:
        change_pack_state(request.user,pk,request.POST.get('state',''))
    except ValidationError as exc:
        from django.contrib import messages
        messages.error(request,' '.join(exc.messages))
    return redirect('qualification:pack_detail',pk=pk)

@login_required
@require_POST
def pack_clone(request,pk):
    source = get_object_or_404(LexicalPack,variety__in=varieties(request.user),pk=pk)
    result = clone_pack(request.user,source)
    return redirect('qualification:pack_edit',pk=result.pk)

@login_required
def candidate_edit(request,pack_id,pk=None):
    pack = get_object_or_404(LexicalPack,variety__in=varieties(request.user,'edit'),pk=pack_id,state='draft')
    obj = get_object_or_404(LexicalCandidate,pack=pack,pk=pk) if pk else LexicalCandidate(pack=pack)
    form = CandidateForm(request.POST or None,instance=obj)
    permitted_media = MediaAsset.objects.filter(uploaded_by=request.user) if not request.user.is_superuser else MediaAsset.objects.all()
    form.fields['image'].queryset = permitted_media.filter(kind='image')
    form.fields['audio'].queryset = permitted_media.filter(kind='audio')
    if request.method=='POST' and form.is_valid():
        obj = form.save()
        audit(request.user,'qualification.lexical_candidate_saved',obj)
        return redirect('qualification:pack_detail',pk=pack.pk)
    return form_page(request,form,_('Document a lexical candidate'))

@login_required
def familiarity(request,pk):
    candidate = get_object_or_404(LexicalCandidate,pk=pk,pack__variety__in=varieties(request.user,'edit'),pack__state='draft')
    form = FamiliarityForm(request.POST or None,instance=FamiliarityStudy(candidate=candidate,recorded_by=request.user))
    form.fields['evidence'].queryset = private_documents(request.user).filter(variety=candidate.pack.variety,category='familiarity',revoked=False)
    if request.method=='POST' and form.is_valid():
        obj = form.save()
        audit(request.user,'qualification.familiarity_documented',obj)
        return redirect('qualification:pack_detail',pk=candidate.pack.pk)
    return form_page(request,form,_('Document exploratory word and image familiarity'))
