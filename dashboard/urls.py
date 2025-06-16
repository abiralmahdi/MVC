from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('newDashboard', views.newDashboard, name='newDashboard'),
    path('<str:dashboardID>', views.indivDashboard, name='indivDashboard'),
    path('<str:dashboardID>/newGadget', views.newGadget, name='newGadget'),
    
    
]
