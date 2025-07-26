from django.urls import path
from . import views

urlpatterns = [
    path('', views.introPage, name='introPage'),
    path('subscription-revoked', views.subscriptionRevoked, name='subscriptionRevoked'),
    # path('useless/energyCostComparison', views.energyCostComparison, name='energyCostComparison'),
    # path('useless/plantSummary', views.plantSummary, name='plantSummary'),
    # path('useless/allUtilities', views.allUtilities, name='allUtilities'),
    # path('useless/plantHeatMaps', views.plantHeatMaps, name='plantHeatMaps'),
    # path('useless/sankeyDiagram', views.sankeyDiagram, name='sankeyDiagram'),
    # path('useless/statusTable', views.statusTable, name='statusTable'),
    # path('useless/trends', views.trends, name='trends')
    
]
