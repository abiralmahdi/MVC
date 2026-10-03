from django.urls import path

from . import views

urlpatterns = [
    path('', views.machine_learning, name='machineLearning'),
    path('train', views.start_training, name='mlStartTraining'),
    path('score', views.score_now, name='mlScoreNow'),
    path('status/<int:run_id>', views.training_status, name='mlTrainingStatus'),
]
