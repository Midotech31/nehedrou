from django.conf import settings
from django.utils.translation import gettext as _
from .access import membership
from .models import Membership

def navigation(request):
    route = request.resolver_match.url_name if request.resolver_match else ''
    titles = {'home': settings.PRODUCT_NAME, 'demo_activity': _('Explore a sample activity'), 'dashboard': _('Overview'), 'children': _('Child profiles'), 'library': _('Activity library'), 'editorial_index': _('Editorial workspace'), 'preferences': _('Preferences'), 'help': _('Help and guidance'), 'login': _('Sign in')}
    namespace = request.resolver_match.namespace if request.resolver_match else ''
    section = namespace if namespace in ['followup', 'qualification'] else 'children' if route and (route.startswith(('child', 'program', 'practice')) or route in ['print_program','report_detail','family_feedback_create']) else 'editorial' if route and route.startswith('editorial') else 'billing' if route and route.startswith('billing') else 'settings' if route and (route.startswith(('mfa','privacy')) or route in ['preferences','data_notice']) else route
    common = {'brand_name': settings.PRODUCT_NAME, 'demo_mode': settings.DEMO_MODE, 'demo_ephemeral': settings.DEMO_EPHEMERAL, 'page_title': titles.get(route, settings.PRODUCT_NAME), 'nav_section': section}
    if not request.user.is_authenticated:
        return common
    from catalog.models import EditorialGrant
    member = membership(request)
    common['space_label'] = _('YOUR SPACE') if member else _('Editorial workspace') if EditorialGrant.objects.filter(user=request.user).exists() else _('Platform management') if request.user.has_perm('core.manage_entitlements') else _('Family space')
    return {**common, 'has_editorial_access': request.user.is_superuser or EditorialGrant.objects.filter(user=request.user).exists(), 'current_membership': member, 'memberships': Membership.objects.filter(user=request.user, active=True).select_related('organization')}
