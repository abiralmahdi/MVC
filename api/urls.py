from django.urls import path
from . import views

urlpatterns = [
    path('addUser', views.RegisterUser.as_view(), name='addUser'),
    path('cancelSubscription', views.RegisterUser.as_view(), name='addUser'),
    path('global-config/', views.GlobalConfigurationView.as_view(), name='global_config'),
    path('global-config/update', views.updateSubscription, name='update_global_config'),    
]
