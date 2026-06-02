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
    path('documents/', views.documents, name='documents'),
    path('documents/scoring-guide/', views.scoring_guide, name='scoring-guide'),
    path('documents/amazon-research/', views.doc_amazon_research, name='doc-amazon-research'),
    path('documents/brand-analytics/', views.doc_ba, name='doc-ba'),
    path('documents/api-reference/', views.doc_api, name='doc-api'),
]
