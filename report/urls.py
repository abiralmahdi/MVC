from django.urls import path
from . import views


urlpatterns = [
    path('', views.reports, name='reports'),   
    path('addFormat', views.addFormat, name='addFormat'),    
]

