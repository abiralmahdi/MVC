from django.conf import settings
from django.db import models


class TrainingRun(models.Model):
    """One training of the predictive-maintenance models, with live progress for the ML page."""

    QUEUED, RUNNING, COMPLETED, FAILED = 'queued', 'running', 'completed', 'failed'
    STATUS_CHOICES = [(QUEUED, 'Queued'), (RUNNING, 'Running'), (COMPLETED, 'Completed'), (FAILED, 'Failed')]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=QUEUED)
    progress = models.FloatField(default=0)            # 0..100
    stage = models.CharField(max_length=100, default='Queued')
    message = models.CharField(max_length=500, blank=True, default='')
    log = models.TextField(blank=True, default='')
    metrics = models.JSONField(default=dict, blank=True)   # metrics, curves, importances, dataset stats
    artifact_dir = models.CharField(max_length=500, blank=True, default='')
    error = models.TextField(blank=True, default='')
    pid = models.IntegerField(null=True, blank=True)
    triggered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Training run #{self.pk} ({self.status})"

    @property
    def duration_seconds(self):
        if not self.started_at:
            return None
        from django.utils import timezone
        end = self.finished_at or timezone.now()
        return (end - self.started_at).total_seconds()


class MotorReading(models.Model):
    """History of motor values read from the PLC (the SCADA page only shows live values)."""

    motor = models.ForeignKey('scada.Motor', related_name='readings', on_delete=models.CASCADE)
    timestamp = models.DateTimeField(db_index=True)
    data = models.JSONField()

    class Meta:
        indexes = [models.Index(fields=['motor', 'timestamp'])]

    def __str__(self):
        return f"{self.motor} @ {self.timestamp}"


class DeviceHealth(models.Model):
    """Latest predictive-maintenance assessment of one meter or motor."""

    OK, LEARNING, NO_SIGNALS, NO_MODEL = 'ok', 'learning', 'no_signals', 'no_model'
    STATUS_CHOICES = [(OK, 'Scored'), (LEARNING, 'Learning baseline'), (NO_SIGNALS, 'No usable signals'), (NO_MODEL, 'No trained model')]
    RISK_CHOICES = [('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('unknown', 'Unknown')]

    meter = models.OneToOneField('dynamic.Meters', null=True, blank=True, related_name='health', on_delete=models.CASCADE)
    motor = models.OneToOneField('scada.Motor', null=True, blank=True, related_name='health', on_delete=models.CASCADE)
    run = models.ForeignKey(TrainingRun, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=NO_MODEL)
    channels = models.JSONField(default=dict, blank=True)       # channel -> measurement name
    hours_of_data = models.IntegerField(default=0)
    last_data_at = models.DateTimeField(null=True, blank=True)
    failure_probability = models.FloatField(null=True, blank=True)   # probability of failure within 7 days
    days_to_maintenance = models.FloatField(null=True, blank=True)
    health_score = models.IntegerField(null=True, blank=True)        # 0..100
    risk = models.CharField(max_length=10, choices=RISK_CHOICES, default='unknown')
    failure_mode = models.CharField(max_length=100, blank=True, default='')
    failure_mode_probability = models.FloatField(null=True, blank=True)
    drivers = models.JSONField(default=list, blank=True)             # [{channel, measurement, direction, contribution}]
    computed_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Health of {self.meter or self.motor}: {self.risk}"
