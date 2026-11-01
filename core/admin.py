from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User, Organization, Membership, Entitlement, AuditEvent, PrivacyRequest, ProcessingActivity

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
        from django.db import transaction
        from .services import audit
        with transaction.atomic():
            organization = Organization.objects.select_for_update().get(pk=obj.organization_id)
            obj.save()
            audit(request.user, 'entitlement.updated' if change else 'entitlement.created', obj, organization)

@admin.register(ProcessingActivity)
class ProcessingActivityAdmin(admin.ModelAdmin):
    list_display = ['name', 'organization', 'controller_name', 'active', 'updated_at']
    list_filter = ['active', 'organization']
    search_fields = ['name', 'controller_name', 'purposes']
    readonly_fields = ['created_by', 'updated_by', 'created_at', 'updated_at']
    fieldsets = [
        (None, {'fields': ('organization', 'register_capacity', 'name', 'active')}),
        (_('Controller and contact'), {'fields': ('controller_name', 'controller_contact', 'data_protection_contact')}),
        (_('Processing description'), {'fields': ('purposes', 'legal_basis', 'data_subject_categories', 'personal_data_categories', 'operations')}),
        (_('Recipients and safeguards'), {'fields': ('recipient_categories', 'international_transfers', 'retention_periods', 'security_measures')}),
        (_('Record history'), {'fields': ('created_by', 'updated_by', 'created_at', 'updated_at')}),
    ]

    def has_module_permission(self, request):
        return request.user.has_perm('core.manage_processing_register')

    def has_view_permission(self, request, obj=None):
        return request.user.has_perm('core.manage_processing_register')

    def has_add_permission(self, request):
        return request.user.has_perm('core.manage_processing_register')

    def has_change_permission(self, request, obj=None):
        return request.user.has_perm('core.manage_processing_register')

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        from .services import audit
        if not change:
            obj.created_by = request.user
            action = 'privacy.register_activity_created'
        else:
            action = 'privacy.register_activity_updated'
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
        from .models import ProcessingActivityRevision
        snapshot_fields = ('organization_id', 'register_capacity', 'name', 'controller_name', 'controller_contact',
                           'data_protection_contact', 'purposes', 'legal_basis', 'data_subject_categories',
                           'personal_data_categories', 'recipient_categories', 'international_transfers',
                           'retention_periods', 'security_measures', 'operations', 'active')
        snapshot = {field: getattr(obj, field) for field in snapshot_fields}
        revision_number = (ProcessingActivityRevision.objects.filter(activity=obj).order_by('-revision')
                           .values_list('revision', flat=True).first() or 0) + 1
        ProcessingActivityRevision.objects.create(activity=obj, revision=revision_number, snapshot=snapshot,
                                                   changed_by=request.user)
        audit(request.user, action, obj, obj.organization)


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
