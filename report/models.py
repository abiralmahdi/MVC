from django.db import models
from django.contrib.auth.models import User
from dashboard.models import *
from dynamic.models import *
from accounts.models import UserModel

class ReportFormat(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(UserModel, on_delete=models.CASCADE)
    logo = models.ImageField(upload_to='media/reportImages')
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True, related_name='reports')

class ReportDiagram(models.Model):
    report_format = models.ForeignKey(
        ReportFormat,
        related_name='diagrams',
        on_delete=models.CASCADE
    )

    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
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

from django.conf import settings
from django.db import models

def get_default_user():
    # Returns the first user as default, or None if no users exist
    return UserModel.objects.first().pk if UserModel.objects.exists() else None

class Billing(models.Model):
    meter = models.ForeignKey(Meters, on_delete=models.DO_NOTHING)
    rate = models.DecimalField(max_digits=10, decimal_places=4)
    fixed_charge = models.DecimalField(max_digits=10, decimal_places=4, default=0.0, null=True, blank=True)
    tax = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)  # Percentage
    date_range_start = models.DateField(null=True, blank=True)
    date_range_end = models.DateField(null=True, blank=True)
    date_due = models.DateField(null=True, blank=True)
    created_at = models.DateField(null=True, blank=True, auto_now_add=True)
    remarks = models.CharField(max_length=1000, default='', null=True, blank=True)
    total_consumption = models.DecimalField(max_digits=10, decimal_places=2, default=0.0) 
    penalty = models.DecimalField(max_digits=10, decimal_places=2, default=0.0) 
    extra_fields = models.JSONField()
    authority = models.CharField(max_length=100, default="")
    generatedBy = models.ForeignKey(
        UserModel, 
        on_delete=models.DO_NOTHING, 
        default=get_default_user,
        null=True,  # Allow null if no user exists
        blank=True
    )
