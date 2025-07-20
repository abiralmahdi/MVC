from django.urls import path
from . import views


urlpatterns = [
    path('', views.location, name='location'),   
    path('triggerAlarm/<str:siteID>', views.triggerAlarm, name='triggerLarams'),   

]

