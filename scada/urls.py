from django.urls import path
from . import views


urlpatterns = [
    path('', views.scada, name='scada'),
    path('saveMotor', views.save_motor, name='saveMotor'),
    path('building/<str:buildingID>', views.scadaBuilding, name='scadaBuilding'),
    path('fetchMotorAndTankData/<int:motorID>', views.fetchMotorAndTankData, name='fetchMotorAndTankData'),
    path("controlMotor/", views.control_motor, name="control_motor"),
]

