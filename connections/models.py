from django.db import models

# Create your models here.
class SystemJob(models.Model):
    name = models.CharField(max_length=100, unique=True)
    last_run = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name