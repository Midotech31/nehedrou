from uuid import UUID
from django.db.models import Q
from django.http import Http404
from care.models import Child, Program
from .models import Membership

# Bump this value whenever the privacy notice changes materially. Existing
# acknowledgements do not acknowledge a newer version of the notice.
CURRENT_NOTICE_VERSION = '2026-10-09'


def notice_acknowledged(user, organization):
    if not user or not user.is_authenticated or organization is None:
        return False
    from .models import NoticeAcknowledgement
    return NoticeAcknowledgement.objects.filter(
        user=user, organization=organization, version=CURRENT_NOTICE_VERSION,
    ).exists()

def membership(request):
    request.practice_selection_required = False
    if request.session.get('workspace') == 'family':
        return None
    qs = Membership.objects.filter(user=request.user, active=True).select_related('organization')
    if 'organization' in request.session:
        selected = request.session['organization']
        try:
            selected = UUID(str(selected))
        except (ValueError, TypeError, AttributeError):
            selected = None
        if selected:
            current = qs.filter(organization_id=selected).first()
            if current is not None:
                return current
        request.practice_selection_required = True
        # A stale form must never acquire the fallback cabinet's write scope.
        # Reading the fallback does not persist it: only explicit switching does.
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            return None
    # Bind the first displayed cabinet before serving any old-style forms.
    # Never persist a fallback for an existing invalid selection.
    first = qs.first()
    if first is not None and 'organization' not in request.session and request.method in ('GET', 'HEAD', 'OPTIONS'):
        request.session['organization'] = str(first.organization_id)
    return first

def professional_children(user):
    return Child.objects.filter(responsible=user, organization__membership__user=user, organization__membership__active=True).distinct()

def visible_children(user):
    return Child.objects.filter(Q(responsible=user, organization__membership__user=user, organization__membership__active=True) | Q(family_links__user=user, family_links__active=True)).distinct()

def visible_programs(user):
    return Program.objects.filter(child__in=visible_children(user)).select_related('child', 'variety', 'organization')

def clinician_child(user, pk):
    try:
        return professional_children(user).get(pk=pk)
    except Child.DoesNotExist:
        raise Http404

def manager(request):
    member = membership(request)
    if not member or member.role != 'owner':
        raise Http404
    return member


def is_family_workspace(request):
    """A workspace narrows lists; the account's actual permissions stay unchanged."""
    selected = request.session.get('workspace')
    if selected == 'family':
        return True
    # A remembered professional choice cannot outlive the actual role.
    from catalog.models import EditorialGrant
    return not (Membership.objects.filter(user=request.user, active=True).exists()
                or EditorialGrant.objects.filter(user=request.user).exists()
                or request.user.has_perm('core.manage_entitlements')
                or request.user.has_perm('core.manage_processing_register'))


def workspace_children(request):
    if is_family_workspace(request):
        return Child.objects.filter(family_links__user=request.user, family_links__active=True).distinct()
    member = membership(request)
    if member is None:
        return Child.objects.none()
    return professional_children(request.user).filter(organization=member.organization)
