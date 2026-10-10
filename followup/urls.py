from django.urls import path
from . import views

app_name = 'followup'
urlpatterns = [
    path('', views.index, name='index'),
    path('children/<uuid:child_id>/goals/new/', views.goal_create, name='goal_create'),
    path('children/<uuid:child_id>/exposure/new/', views.exposure_create, name='exposure_create'),
    path('goals/<uuid:pk>/', views.goal_detail, name='goal_detail'),
    path('goals/<uuid:pk>/close/', views.goal_close, name='goal_close'),
    path('definitions/', views.definition_list, name='definition_list'),
    path('definitions/new/', views.definition_edit, name='definition_create'),
    path('definitions/<uuid:pk>/', views.definition_detail, name='definition_detail'),
    path('definitions/<uuid:pk>/edit/', views.definition_edit, name='definition_edit'),
    path('definitions/<uuid:pk>/items/<slug:item_key>/media/<str:kind>/', views.definition_media, name='definition_media'),
    path('definitions/<uuid:pk>/clone/', views.definition_clone, name='definition_clone'),
    path('definitions/<uuid:pk>/transition/', views.definition_transition, name='definition_transition'),
    path('goals/<uuid:goal_id>/start/', views.administration_start, name='administration_start'),
    path('administrations/<uuid:pk>/', views.administration_detail, name='administration_detail'),
    path('administrations/<uuid:pk>/items/<slug:item_key>/', views.rating, name='rating'),
    path('administrations/<uuid:pk>/items/<slug:item_key>/media/<str:kind>/', views.administration_media, name='administration_media'),
    path('administrations/<uuid:pk>/finalize/', views.administration_finalize, name='administration_finalize'),
    path('administrations/<uuid:pk>/report/', views.report, name='report'),
    path('administrations/<uuid:pk>/print/', views.report_print, name='report_print'),
    path('administrations/<uuid:pk>/export.csv', views.report_csv, name='report_csv'),
    path('administrations/<uuid:pk>/share/', views.share, name='share'),
    path('administrations/<uuid:pk>/share/revoke/', views.share_revoke, name='share_revoke'),
    path('administrations/<uuid:pk>/family/', views.family_summary, name='family_summary'),
    path('children/<uuid:child_id>/coaching/new/', views.coaching_create, name='coaching_create'),
    path('coaching/<uuid:pk>/', views.coaching_detail, name='coaching_detail'),
    path('coaching/<uuid:pk>/print/', views.coaching_print, name='coaching_print'),
    path('coaching/<uuid:pk>/feedback/', views.home_feedback, name='home_feedback'),
]
