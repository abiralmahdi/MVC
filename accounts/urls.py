from django.urls import path
from . import views

urlpatterns = [
    path('login', views.login_, name='login'),
    path('logout', views.logout_view, name='logout'),
    path('register', views.register, name='register'),
    path('loginHistory', views.loginHistory, name='loginHistory'),
    path('accountSettings', views.accountSettings, name='accountSettings'),
    path('terminateUser/<str:userID>', views.terminateUser, name='terminateUser'),
    
]
