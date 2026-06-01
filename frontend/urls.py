from django.urls import path
from . import views

app_name = 'frontend'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('board/', views.board, name='board'),
    path('score/', views.score_idea, name='score'),
    path('ideas/<str:idea_id>/', views.idea_detail, name='idea-detail'),
    path('research/', views.research, name='research'),
    path('ba-explorer/', views.ba_explorer, name='ba-explorer'),
]
