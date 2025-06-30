from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('newDashboard', views.newDashboard, name='newDashboard'),
    path('<str:dashboardID>', views.indivDashboard, name='indivDashboard'),
    path('<str:dashboardID>/newGadget', views.newGadget, name='newGadget'),
    path('<str:dashboardID>/fetchLatestReadings/<str:gadget_id>/', views.fetchLatestReadings, name='fetchLatestReadings'),
    path('<str:dashboard_id>/fetchDateTimeWindow/<str:gadget_id>/<str:datetime_str>/', views.fetchDateTimeWindow, name='fetchDateTimeWindow'),
    path('<int:dashboard_id>/data/<int:gadget_id>/<str:measurement>/<str:date>/<str:period>', views.getData, name='getPieData'),
    path('<int:dashboard_id>/fetchLatestToolData/<int:gadget_id>/', views.fetchLatestToolData, name='fetchLatestToolData'),
    path('<int:dashboard_id>/multiYearBarData/<int:gadget_id>/<str:measurement>/<str:date>/<str:period>', views.getMultiYearBarData, name='bar_compare_data'),
    path('<int:dashboard_id>/fetchTableData/<int:gadget_id>', views.fetchTableData, name='fetchTableData'),
    path("<int:site_id>/hierarchyy/<str:period_type>/<str:start_date>/", views.hierarchyAggView, name="hierarchyAggView"),


    
]
