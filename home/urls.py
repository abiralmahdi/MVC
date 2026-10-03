from django.urls import path
from . import views

urlpatterns = [
    path('', views.introPage, name='introPage'),
    path('subscription-revoked', views.subscriptionRevoked, name='subscriptionRevoked'),
]
