from django.db.models import Q
from django.http import Http404
from care.models import Child, Program
from .models import Membership

def membership(request):
    qs = Membership.objects.filter(user=request.user, active=True).select_related('organization')
    selected = request.session.get('organization')
    return qs.filter(organization_id=selected).first() if selected else qs.first()

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
