from django.urls import path
from . import views


urlpatterns = [
    path('configureDashboard', views.configureDashboard, name='configureDashboard'),
    path('', views.settings, name='settings'),
    path('hierarchy', views.hierarchy, name='hierarchy'),
    path('hierarchy/addSite', views.addSite, name='addSite'),
    path('hierarchy/addBuilding', views.addBuilding, name='addBuilding'),
    path('hierarchy/addArea', views.addArea, name='addArea'),
    path('hierarchy/addMeter', views.addMeter, name='addMeter'),
    path('hierarchy/addLoadType', views.addLoadType, name='addLoadType'),
    path('hierarchy/deleteSite', views.deleteSite, name='deleteSite'),
    path('hierarchy/deleteArea', views.deleteArea, name='deleteArea'),
    path('hierarchy/deleteBuilding', views.deleteBuilding, name='deleteBuilding'),
    path('hierarchy/deleteMeter', views.deleteMeter, name='deleteMeter'),

    
]





'''


'''