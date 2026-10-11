from core.i18n import switch_language
from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.contrib import admin
from django.contrib.auth import views as auth
from django.urls import path, include
from core import views
from core import security, complete_views
from catalog import views as editorial_views
from catalog import working, quality
from core.health import health

urlpatterns = [path('healthz/', health, name='health'), path('i18n/setlang/', switch_language, name='set_language')]
urlpatterns += i18n_patterns(
    path('', views.home, name='home'),
    path('help/', views.help_page, name='help'),
    path('try/', views.demo_activity, name='demo_activity'),
    path('signup/', views.signup, name='signup'),
    path('login/', auth.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth.LogoutView.as_view(), name='logout'),
    path('password-reset/', auth.PasswordResetView.as_view(template_name='registration/password_reset_form.html'), name='password_reset'),
    path('password-reset/sent/', auth.PasswordResetDoneView.as_view(template_name='registration/password_reset_done.html'), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', auth.PasswordResetConfirmView.as_view(template_name='registration/password_reset_confirm.html'), name='password_reset_confirm'),
    path('reset/done/', auth.PasswordResetCompleteView.as_view(template_name='registration/password_reset_complete.html'), name='password_reset_complete'),
    path('app/', views.dashboard, name='dashboard'),
    path('app/switch/', views.switch_practice, name='switch_practice'),
    path('children/', views.children, name='children'),
    path('children/new/', views.child_create, name='child_create'),
    path('children/<uuid:pk>/', views.child_detail, name='child_detail'),
    path('children/<uuid:pk>/program/', views.program_create, name='program_create'),
    path('children/<uuid:pk>/export/', views.export_child, name='export_child'),
    path('children/<uuid:pk>/archive/', views.archive_child, name='archive_child'),
    path('children/<uuid:pk>/privacy/', views.privacy_request, name='privacy_request'),
    path('links/<uuid:pk>/revoke/', views.revoke_link, name='revoke_link'),
    path('invitations/<uuid:pk>/revoke/', views.revoke_invite, name='revoke_invite'),
    path('invitations/<uuid:pk>/resend/', views.resend_invitation, name='resend_invitation'),
    path('invite/<str:token>/', views.invite, name='invite'),
    path('library/', views.library, name='library'),
    path('library/<uuid:pk>/', views.activity_detail, name='activity_detail'),
    path('programs/<uuid:pk>/', views.program_detail, name='program_detail'),
    path('programs/<uuid:pk>/calendar/', views.program_calendar, name='program_calendar'),
    path('programs/<uuid:pk>/history/', views.program_history, name='program_history'),
    path('programs/<uuid:pk>/feedback/', views.family_feedback_create, name='family_feedback_create'),
    path('history/reports/<uuid:pk>/', views.report_detail, name='report_detail'),
    path('programs/<uuid:pk>/finish/', views.finish_program, name='finish_program'),
    path('programs/<uuid:pk>/print/', views.print_program, name='print_program'),
    path('programs/<uuid:pk>/start/', views.practice_run_start, name='practice_run_start'),
    path('runs/<uuid:pk>/', views.practice_run_detail, name='practice_run_detail'),
    path('runs/<uuid:pk>/stop/', views.practice_run_stop, name='practice_run_stop'),
    path('practice/<uuid:pk>/', views.practice, name='practice'),
    path('reports/<uuid:pk>/', views.practice_report, name='practice_report'),
    path('members/', views.members, name='members'),
    path('members/<uuid:pk>/revoke/', views.revoke_member, name='revoke_member'),
    path('subscription/', views.subscription, name='subscription'),
    path('preferences/', views.preferences, name='preferences'),
    path('security/setup/', security.setup, name='mfa_setup'),
    path('security/qr/', security.qr, name='mfa_qr'),
    path('security/verify/', security.verify, name='mfa_verify'),
    path('security/recovery/', security.recovery_codes, name='mfa_recovery'),
    path('children/<uuid:pk>/edit/', complete_views.child_edit, name='child_edit'),
    path('children/<uuid:pk>/restore/', complete_views.restore_child, name='child_restore'),
    path('children/<uuid:pk>/transfer/', complete_views.reassign, name='child_reassign'),
    path('programs/<uuid:pk>/adjust/', complete_views.program_replace, name='program_replace'),
    path('requests/', complete_views.requests, name='privacy_requests'),
    path('requests/<uuid:pk>/', complete_views.resolve_request, name='privacy_resolve'),
    path('information/', complete_views.notice, name='data_notice'),
    path('practice/settings/', complete_views.organization_settings, name='organization_settings'),
    path('billing/', complete_views.billing, name='billing_index'),
    path('billing/<uuid:pk>/', complete_views.billing, name='billing_detail'),
    path('billing/<uuid:pk>/invoice/', complete_views.invoice_create, name='invoice_create'),
    path('members/invitations/<uuid:pk>/revoke/', complete_views.revoke_member_invitation, name='revoke_member_invitation'),
    path('editorial/', editorial_views.index, name='editorial_index'),
    path('followup/', include('followup.urls')),
    path('qualification/', include('qualification.urls')),
    path('editorial/work/<uuid:pk>/set-aside/', working.set_aside, name='editorial_working_status'),
    path('editorial/work/<uuid:pk>/', working.autosave, name='editorial_autosave'),
    path('editorial/quality/', quality.dashboard, name='editorial_quality'),
    path('editorial/quality/export/', quality.review_pack, name='editorial_review_pack'),
    path('editorial/new/', editorial_views.edit, name='editorial_create'),
    path('editorial/<uuid:pk>/', editorial_views.detail, name='editorial_detail'),
    path('editorial/<uuid:pk>/edit/', editorial_views.edit, name='editorial_edit'),
    path('editorial/<uuid:pk>/transition/', editorial_views.change_state, name='editorial_transition'),
    path('editorial/<uuid:pk>/clone/', editorial_views.clone, name='editorial_clone'),
    path('editorial/upload/', editorial_views.upload, name='editorial_upload'),
    path('media/<uuid:pk>/', editorial_views.media, name='editorial_media'),
)
# Technical admin remains local; operational production views use scoped permissions and MFA.
if settings.LOCAL_ADMIN_ENABLED:
    urlpatterns += [path('admin/', admin.site.urls)]
