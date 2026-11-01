from django.urls import path
from . import views
app_name = 'qualification'
urlpatterns = [
    path('', views.index, name='index'),
    path('availability/', views.availability, name='availability'),
    path('availability/<uuid:pk>/revoke/', views.availability_revoke, name='availability_revoke'),
    path('evidence/new/', views.evidence_upload, name='evidence_upload'),
    path('evidence/<uuid:pk>/file/', views.evidence_file, name='evidence_file'),
    path('evidence/<uuid:pk>/revoke/', views.revoke_evidence, name='evidence_revoke'),
    path('competence/new/', views.competence, name='competence'),
    path('competence/<uuid:pk>/', views.competence, name='competence_edit'),
    path('competence-checks/', views.competence_verification_index, name='competence_verification_index'),
    path('competence-checks/<uuid:pk>/', views.competence_verification, name='competence_verification'),
    path('packs/new/', views.pack_edit, name='pack_new'),
    path('packs/<uuid:pk>/', views.pack_detail, name='pack_detail'),
    path('packs/<uuid:pk>/edit/', views.pack_edit, name='pack_edit'),
    path('packs/<uuid:pk>/transition/', views.pack_transition, name='pack_transition'),
    path('packs/<uuid:pk>/clone/', views.pack_clone, name='pack_clone'),
    path('packs/<uuid:pack_id>/candidates/new/', views.candidate_edit, name='candidate_new'),
    path('packs/<uuid:pack_id>/candidates/<uuid:pk>/', views.candidate_edit, name='candidate_edit'),
    path('candidates/<uuid:pk>/familiarity/', views.familiarity, name='familiarity'),
]
