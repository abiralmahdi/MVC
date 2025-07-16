from django.db import models
from django.contrib.auth.models import User
from dashboard.models import *
from dynamic.models import *

class ReportFormat(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)

class ReportDiagram(models.Model):
    report_format = models.ForeignKey(
        ReportFormat,
        related_name='diagrams',
        on_delete=models.CASCADE
    )

    site = models.ForeignKey(Site, on_delete=models.PROTECT, default=7)
    diagram_type = models.CharField(max_length=50)

    # Meters can be empty for Sankey, single for Table
    meters = models.ManyToManyField(Meters, blank=True)

    # Measurements → Many-to-many to support multiple for Table
    measurements = models.ManyToManyField(Measurements, blank=True)

    # Date range fields → flexible for single/range
    date_range_start = models.DateTimeField(null=True, blank=True)
    date_range_end = models.DateTimeField(null=True, blank=True)

    # Period type → optional
    period_type = models.CharField(max_length=20, blank=True, null=True)

    description = models.CharField(max_length=1000, default='')

    image = models.ImageField(upload_to='media/reportImages/')

    def __str__(self):
        return f"{self.diagram_type} for {self.report_format.title} and ID: {self.id}"
