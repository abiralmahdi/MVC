from django.urls import path
from . import views

urlpatterns = [
    path('login', views.login_, name='login'),
    path('loginHistory', views.loginHistory, name='loginHistory'),
    
]
