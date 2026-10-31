from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Organization, Membership, Entitlement, AuditEvent, PrivacyRequest

@admin.register(User)
class AccountAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (('Preferences', {'fields': ('instruction_language',)}),)

class TechnicalAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_superuser
    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser
    def has_add_permission(self, request):
        return request.user.is_superuser
    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser
    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(Membership)
class MembershipAdmin(TechnicalAdmin):
    list_display = ['user', 'organization', 'role', 'active']
    def save_model(self, request, obj, form, change):
        from django.core.exceptions import ValidationError
        from django.db import transaction
        from .services import audit
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=obj.organization_id)
            entitlement = Entitlement.objects.filter(organization=organization).first()
            old = Membership.objects.filter(pk=obj.pk).first()
            if obj.active and (not old or not old.active):
                if not entitlement or not entitlement.usable or Membership.objects.filter(organization=organization, active=True).count() >= entitlement.practitioner_quota:
                    raise ValidationError('Practitioner quota reached or access expired.')
            obj.save()
            audit(request.user, 'membership.updated', obj, organization)

@admin.register(Entitlement)
class EntitlementAdmin(TechnicalAdmin):
    list_display = ['organization', 'plan', 'status', 'expires_at', 'child_quota']
    def save_model(self, request, obj, form, change):
        from .services import audit
        obj.save()
        audit(request.user, 'entitlement.updated', obj, obj.organization)

@admin.register(AuditEvent)
class AuditAdmin(TechnicalAdmin):
    list_display = ['created_at', 'organization', 'actor', 'actor_ref', 'action', 'purpose_code', 'object_id']
    readonly_fields = ['created_at', 'organization', 'actor', 'actor_ref', 'action', 'purpose_code', 'object_id']
    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False

admin.site.register(Organization, TechnicalAdmin)
admin.site.register(PrivacyRequest, TechnicalAdmin)
# Clinical models are intentionally absent from the technical admin.
