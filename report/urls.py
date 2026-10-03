from django.urls import path
from . import views


urlpatterns = [
    path('', views.reports, name='reports'),
    path('createReportFormat', views.createReportFormat, name='createReportFormat'),
    path('viewReport/<int:reportID>', views.viewReport, name='viewReport'),
    path('deleteReport/<int:reportID>', views.deleteReport, name='deleteReport'),
    path('getDiagramData/<int:diagramID>', views.getDiagramData, name='getDiagramData'),
    path('getLineDiagramData/<int:diagramID>', views.getLineDiagramData, name='getLineDiagramData'),
    path('getTableData/<int:diagramID>', views.getTableData, name='getTableData'),
    path('heatmap/<int:diagramID>', views.heatmap_data, name='heatmap_data'),
    path('sankey_data/<int:diagramID>', views.sankey_data, name='sankey_data'),
    path('generate_pdf/<int:reportID>', views.generate_pdf, name='generate_pdf'),
    # Old URL shape (title in the path) kept so existing bookmarks keep working.
    path('generate_pdf/<path:filename>/<int:reportID>', views.generate_pdf, name='generate_pdf_legacy'),
    path('saveDiagramImage/<int:diagramID>', views.saveDiagramImage, name='saveDiagramImage'),
    path('viewSavedReports', views.savedReportsPage, name='savedReportsPage'),
    path('viewSavedReports/<int:reportID>', views.viewSavedReports, name='viewSavedReports'),
    path('viewSavedReport/<int:reportID>/', views.viewSavedReport, name='viewSavedReport'),
]
