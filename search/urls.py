from django.urls import path
from . import views

app_name = 'search'
urlpatterns = [
     path("amazon-search/", views.amazon_search,name="amazon-search"),
]
