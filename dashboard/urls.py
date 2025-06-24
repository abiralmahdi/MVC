from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('newDashboard', views.newDashboard, name='newDashboard'),
    path('<str:dashboardID>', views.indivDashboard, name='indivDashboard'),
    path('<str:dashboardID>/newGadget', views.newGadget, name='newGadget'),
    path('<str:dashboardID>/fetchLatestReadings/<str:gadget_id>/', views.fetchLatestReadings, name='fetchLatestReadings'),
    path('<str:dashboard_id>/fetchDateTimeWindow/<str:gadget_id>/<str:datetime_str>/', views.fetchDateTimeWindow, name='fetchDateTimeWindow'),
    path('<int:dashboard_id>/pieData/<int:gadget_id>/<str:measurement>/<str:date>/', views.getPieData, name='getPieData'),
    path('<int:dashboard_id>/fetchLatestToolData/<int:gadget_id>/', views.fetchLatestToolData, name='fetchLatestToolData'),


    
]
