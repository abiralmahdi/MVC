from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('newDashboard', views.newDashboard, name='newDashboard'),
    path('centralCommand/industryOverview', views.indivCentralDashboard, name='indivCentralDashboard'),
    path("centralCommand/industryOverview/<int:site_id>/<str:measurement>/<str:period_type>/", views.grouped_chart_data_for_site, name='grouped_chart_data_for_site'),
    path('siteDashboard/<str:siteID>', views.siteDashbaord, name='siteDashbaord'),
    path('<str:dashboardID>', views.indivDashboard, name='indivDashboard'),
    path('<int:dashboardID>/newGadget', views.newGadget, name='newGadget'),
    path('<int:dashboard_id>/weather/', views.weather, name='dashboardWeather'),
    path('<int:dashboardID>/fetchLatestReadings/<int:gadget_id>/', views.fetchLatestReadings, name='fetchLatestReadings'),
    path('<int:dashboard_id>/fetchDateTimeWindow/<int:gadget_id>/<str:datetime_str>/', views.fetchDateTimeWindow, name='fetchDateTimeWindow'),
    path('<int:dashboard_id>/data/<int:gadget_id>/<str:measurement>/<str:date>/<str:period>', views.getData, name='getPieData'),
    path('<int:dashboard_id>/fetchLatestToolData/<int:gadget_id>/', views.fetchLatestToolData, name='fetchLatestToolData'),
    path('<int:dashboard_id>/fetchLatestMultipleMeterTableData/<int:gadget_id>/', views.fetchLatestMultipleMeterTableData, name='fetchLatestMultipleMeterTableData'),
    path('<int:dashboard_id>/machineHealth/<int:gadget_id>/', views.machineHealthData, name='machineHealthData'),
    path('<int:dashboard_id>/multiYearBarData/<int:gadget_id>/<str:measurement>/<str:date>/<str:period>', views.getMultiYearBarData, name='bar_compare_data'),
    path('<int:dashboard_id>/fetchValueCardData/<int:site_id>/<int:measurement_id>', views.fetchValueCardData, name='fetchValueCardData'),
    path('<int:dashboard_id>/fetchTableData/<int:gadget_id>', views.fetchTableData, name='fetchTableData'),
    path("<int:dashboard_id>/hierarchyy/<int:site_id>/<str:measurement>/<str:period_type>/<str:start_date>/", views.hierarchyAggView, name="hierarchyAggView"),
    path("<int:dashboard_id>/heatmap/<int:meter_id>/<str:start_date>/<str:end_date>/<path:measurement>/", views.heatmap_data, name="heatmap_data"),
    path("<int:dashboard_id>/building_heatmap/<int:buildingID>/<str:measurement>/", views.building_heatmap, name="building_heatmap"),
    path('<int:dashboardID>/deleteGadget/<int:gadgetID>/', views.deleteGadget, name='deleteGadget'),
    path('<int:dashboardID>/editGadget/<int:gadgetID>/', views.editGadget, name='editGadget'),
]
