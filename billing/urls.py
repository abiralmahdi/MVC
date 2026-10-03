from django.urls import path
from . import views


urlpatterns = [
    path('', views.billing, name='billing'),
    path('create_billing', views.create_billing, name='create_billing'),
    path('<int:billID>', views.viewBills, name='viewBills'),
]
