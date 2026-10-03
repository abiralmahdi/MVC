from django.urls import path
from . import views


urlpatterns = [
    path('', views.scada, name='scada'),
    path('saveMotor', views.save_motor, name='saveMotor'),
    path('status', views.scadaStatus, name='scadaStatus'),
    path('deleteMotor/<int:motorID>', views.delete_motor, name='deleteMotor'),
    path('building/<str:buildingID>', views.scadaBuilding, name='scadaBuilding'),
    path('fetchMotorAndTankData/<int:motorID>', views.fetchMotorAndTankData, name='fetchMotorAndTankData'),
    path("controlMotor/", views.control_motor, name="control_motor"),
]
