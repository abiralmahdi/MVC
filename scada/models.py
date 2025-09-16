from django.db import models
from dynamic.models import *

# Create your models here.

class MotorMasters(models.Model):
    masterType = models.CharField(max_length=100)
    ip = models.CharField(max_length=100, null=True, blank=True)
    port = models.IntegerField(null=True, blank=True)


class Motor(models.Model):
    motorName = models.CharField(max_length=100)
    motorMaster = models.ForeignKey(MotorMasters, on_delete=models.CASCADE, related_name='motors', null=True, blank=True)
    building = models.ForeignKey(Buildings, on_delete=models.CASCADE, related_name='motorBuilding')
    ip = models.CharField(max_length=100, default=100)
    dbNo = models.IntegerField(default=0)
    fields = models.JSONField()
    isOn = models.BooleanField(default=False)
    rack = models.IntegerField(default=0)
    slot = models.IntegerField(default=0)
    startByte = models.IntegerField(default=0)
    dataSize = models.IntegerField(default=0)
    motorOnOffset = models.JSONField()
    motorOffOffset = models.JSONField()
    runFeedbackOffset = models.JSONField()
    tripOffset = models.JSONField()

class Tank(models.Model):
    motor = models.ForeignKey(Motor, on_delete=models.CASCADE, related_name='tank', null=True, blank=True)
    highByte = models.IntegerField(null=True, blank=True)
    lowByte = models.IntegerField(null=True, blank=True)
    highBit = models.IntegerField(null=True, blank=True)
    lowBit = models.IntegerField(null=True, blank=True)
    valueByte = models.IntegerField(null=True, blank=True)
    valueBit = models.IntegerField(null=True, blank=True)
    tankVolume = models.IntegerField(null=True, blank=True, default=100)