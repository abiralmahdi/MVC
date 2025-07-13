from django.db import models
from django.contrib.auth.models import User


class ReportFormat(models.Model):
    FORMAT_CHOICES = [
        ('pdf', 'PDF'),
        ('xlsx', 'Excel'),
        ('html', 'HTML Preview'),
    ]
    name = models.CharField(max_length=50, unique=True)
    file_type = models.CharField(max_length=10, choices=FORMAT_CHOICES)
    template_file = models.FileField(upload_to='report_templates/', blank=True, null=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.name} ({self.file_type.upper()})"
    

class Report(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    format = models.ForeignKey(ReportFormat, on_delete=models.PROTECT)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    is_standard = models.BooleanField(default=False)
    config = models.JSONField(help_text="Stores report blocks, data sources, gadgets, filters, etc.")

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({'Standard' if self.is_standard else 'Custom'})"
    
# jsonFormat = {
#   "meters": [1, 2, 3],
#   "site": 4,
#   "start_date": "2025-06-01",
#   "end_date": "2025-06-30",
#   "blocks": [
#     {
#       "type": "line_chart",
#       "title": "Total Active Power",
#       "measurement": "Total Active Power",
#       "aggregation": "hourly"
#     },
#     {
#       "type": "heatmap",
#       "title": "Daily Load Profile",
#       "measurement": "Active Power L1"
#     }
#   ]
# }

    

class ReportRun(models.Model):
    report = models.ForeignKey(Report, on_delete=models.CASCADE)
    generated_by = models.ForeignKey(User, on_delete=models.CASCADE)
    generated_at = models.DateTimeField(auto_now_add=True)
    output_file = models.FileField(upload_to='generated_reports/')
    status = models.CharField(max_length=20, default='completed')

    def __str__(self):
        return f"Run of {self.report.name} at {self.generated_at}"