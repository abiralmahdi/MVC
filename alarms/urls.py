from django.urls import path
from . import views

urlpatterns = [
    path('allAlarms', views.allAlarms, name='allAlarms'),
    path('setAlarmRange/', views.setAlarmRange, name='setAlarmRange'),
    path('setRange/<int:meterID>/', views.setRange, name='setRange'),
    path('ackAlarm/<int:alarmID>/', views.ackAlarm, name='ackAlarm'),
    path('ackAllAlarms/', views.ackAllAlarms, name='ackAllAlarms'),
    path('changeAlarmDesc/<int:alarmID>/', views.changeAlarmDesc, name='changeAlarmDesc'),
]
