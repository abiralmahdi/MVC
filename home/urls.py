from django.urls import path
from . import views

urlpatterns = [
    path('', views.plantSummary, name='plantSummary'),
    path('dashboard/energyCostComparison', views.energyCostComparison, name='energyCostComparison'),
    path('dashboard/plantSummary', views.plantSummary, name='plantSummary'),
    path('dashboard/allUtilities', views.allUtilities, name='allUtilities'),
    path('dashboard/plantHeatMaps', views.plantHeatMaps, name='plantHeatMaps'),
    path('dashboard/sankeyDiagram', views.sankeyDiagram, name='sankeyDiagram'),
    path('dashboard/statusTable', views.statusTable, name='statusTable'),
    path('trends', views.trends, name='trends')
    
]
