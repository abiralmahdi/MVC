from django.db import models
from django.contrib.auth.models import User
from dashboard.models import *
from dynamic.models import *


class ReportFormat(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class ReportDiagram(models.Model):
    report_format = models.ForeignKey(ReportFormat, related_name='diagrams', on_delete=models.CASCADE)
    diagram_type = models.CharField(max_length=50)
    meters = models.ManyToManyField(Meters)
    measurement = models.ForeignKey(Measurements, on_delete=models.CASCADE)
    date_range_start = models.DateField()
    date_range_end = models.DateField()
    period_type = models.CharField(max_length=20)
