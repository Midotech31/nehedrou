from django.conf import settings
from django.utils.translation import gettext as _
from .access import membership, is_family_workspace
from .models import Membership

def navigation(request):
    route = request.resolver_match.url_name if request.resolver_match else ''
    titles = {'home': settings.PRODUCT_NAME, 'demo_activity': _('Explore a sample activity'), 'dashboard': _('Overview'), 'children': _('Child profiles'), 'library': _('Activity library'), 'editorial_index': _('Editorial workspace'), 'editorial_create': _('Create an activity from scratch'), 'editorial_edit': _('Edit content draft'), 'editorial_detail': _('Activity purpose and guidance'), 'editorial_upload': _('Upload editorial media'), 'preferences': _('Preferences'), 'help': _('Help and guidance'), 'login': _('Sign in')}
    titles.update({'program_create': _('Create a program'), 'program_replace': _('Adjust program'), 'program_detail': _('Program and reports'), 'program_history': _('Complete history'), 'print_program': _('Printable support'), 'report_detail': _('Practice report'), 'child_detail': _('Child profile'), 'child_edit': _('Edit profile'), 'activity_detail': _('Activity purpose and guidance')})
    namespace = request.resolver_match.namespace if request.resolver_match else ''
    section = namespace if namespace in ['followup', 'qualification'] else 'children' if route and (route.startswith(('child', 'program', 'practice')) or route in ['print_program','report_detail','family_feedback_create']) else 'editorial' if route and route.startswith('editorial') else 'billing' if route and route.startswith('billing') else 'settings' if route and (route.startswith(('mfa','privacy')) or route in ['preferences','data_notice']) else route
    common = {'brand_name': settings.PRODUCT_NAME, 'demo_mode': settings.DEMO_MODE, 'demo_ephemeral': settings.DEMO_EPHEMERAL, 'page_title': titles.get(route, settings.PRODUCT_NAME), 'nav_section': section}
    if not request.user.is_authenticated:
        return common
    from catalog.models import EditorialGrant
    from care.models import FamilyLink
    member = membership(request)
    family_workspace = is_family_workspace(request)
    memberships = Membership.objects.filter(user=request.user, active=True).select_related('organization')
    has_editorial_access = request.user.is_superuser or EditorialGrant.objects.filter(user=request.user).exists()
    has_family_access = FamilyLink.objects.filter(user=request.user, active=True).exists()
    has_professional_space = memberships.exists() or has_editorial_access or request.user.has_perm('core.manage_entitlements')
    common.update(practice_selection_required=getattr(request, 'practice_selection_required', False),
        family_workspace=family_workspace, has_family_access=has_family_access,
        has_professional_space=has_professional_space,
        show_workspace_switch=has_professional_space and (has_family_access or family_workspace))
    common['space_label'] = _('Family space') if family_workspace else _('YOUR SPACE') if member else _('Editorial workspace') if EditorialGrant.objects.filter(user=request.user).exists() else _('Platform management') if request.user.has_perm('core.manage_entitlements') else _('Family space')
    return {**common, 'has_editorial_access': has_editorial_access, 'current_membership': member, 'memberships': memberships}
