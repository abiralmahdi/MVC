from django.urls import path
from . import views


urlpatterns = [
    path('', views.reports, name='reports'),   
    path('createReportFormat', views.createReportFormat, name='createReportFormat'),    
    path('viewReport/<str:reportID>', views.viewReport, name='viewReport'),    
    path('getDiagramData/<str:diagramID>', views.getDiagramData, name='getDiagramData'),  
    path('getLineDiagramData/<str:diagramID>', views.getLineDiagramData, name='getLineDiagramData'),    
    path('getTableData/<str:diagramID>', views.getTableData, name='getTableData'),    
    path('heatmap/<str:diagramID>', views.heatmap_data, name='heatmap_data'),   
    path('sankey_data/<str:diagramID>', views.sankey_data, name='sankey_data'), 
    path('generate_pdf/<str:filename>/<str:reportID>', views.generate_pdf, name='generate_pdf'),   
    path('saveDiagramImage/<str:diagramID>', views.saveDiagramImage, name='saveDiagramImage'),
    path('viewSavedReports', views.savedReportsPage, name='savedReportsPage'),      
    path('viewSavedReports/<str:reportID>', views.viewSavedReports, name='viewSavedReports'),  
    path('viewSavedReport/<int:reportID>/', views.viewSavedReport, name='viewSavedReport')

]

