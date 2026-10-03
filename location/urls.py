from django.urls import path
from . import views


urlpatterns = [
    path('', views.location, name='location'),
    path('alarmStatus', views.alarmStatus, name='alarmStatus'),
    path('triggerAlarm/<str:siteID>', views.triggerAlarm, name='triggerLarams'),
]
