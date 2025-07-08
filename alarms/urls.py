from django.urls import path
from . import views

urlpatterns = [
    path('allAlarms', views.allAlarms, name='allAlarms'),
    path('setAlarmRange/', views.setAlarmRange, name='setAlarmRange'),
    path('setRange/<str:meterID>/', views.setRange, name='setRange'),
    path('ackAlarm/<str:alarmID>/', views.ackAlarm, name='ackAlarm'),
    path('changeAlarmDesc/<str:meterID>/', views.changeAlarmDesc, name='changeAlarmDesc'),


    
]
