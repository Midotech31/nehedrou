from django.contrib import admin
from django.core.exceptions import PermissionDenied
from .models import Variety, Activity, Review

@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ['title', 'variety', 'version', 'state', 'is_demo']
    list_filter = ['variety', 'state', 'is_demo']
    search_fields = ['title', 'contrast']
    readonly_fields = ['created_at']
    def save_model(self, request, obj, form, change):
        old = Activity.objects.filter(pk=obj.pk).first()
        if obj.state in ['published', 'withdrawn'] and (not old or old.state != obj.state):
            if not request.user.has_perm('catalog.publish_activity'):
                raise PermissionDenied
        obj.save()
        from core.services import audit
        audit(request.user, 'catalog.' + obj.state, obj)

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['activity', 'reviewer', 'kind', 'approved']
    exclude = ['reviewer']
    readonly_fields = ['created_at']
    def save_model(self, request, obj, form, change):
        if not request.user.has_perm('catalog.review_activity'):
            raise PermissionDenied
        obj.reviewer = request.user
        obj.save()
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs if request.user.is_superuser else qs.filter(reviewer=request.user)

admin.site.register(Variety)
