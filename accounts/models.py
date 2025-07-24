from django.db import models
from django.contrib.auth.models import User
from dynamic.models import Site


class UserModel(models.Model):
    name = models.CharField(max_length=100, null=True, blank=True)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True)
    email = models.CharField(max_length=100)
    password = models.CharField(max_length=100)
    role = models.CharField(max_length=100)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='userModel', null=True, blank=True)
    profilePic = models.ImageField(upload_to='media/images', null=True, blank=True)
    last_activity = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name
    


class LoginHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='login_history')
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, null=True)  # Raw
    device = models.CharField(max_length=200, blank=True, null=True)  # Combined parsed result

    def __str__(self):
        return f"{self.user.username} logged in at {self.timestamp}"