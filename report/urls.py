from django.urls import path
from . import views


urlpatterns = [
    path('', views.reports, name='reports'),   
    path('createReportFormat', views.createReportFormat, name='createReportFormat'),    
    path('viewReport/<str:reportID>', views.viewReport, name='viewReport'),    
    path('getDiagramData/<str:diagramID>', views.getDiagramData, name='getDiagramData'),    
    path('getTableData/<str:diagramID>', views.getTableData, name='getTableData'),    
    path('heatmap/<str:diagramID>', views.heatmap_data, name='heatmap_data'),    
]

