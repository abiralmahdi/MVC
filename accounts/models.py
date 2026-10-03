from django.db import models
from django.contrib.auth.models import User
from dynamic.models import Site


class UserModel(models.Model):
    """Profile attached to a Django auth user.

    ``password`` keeps the raw (plaintext) password as requested by the owner;
    authentication still uses the hashed password in auth.User.
    """
    name = models.CharField(max_length=100, null=True, blank=True)
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True)
    email = models.CharField(max_length=100)
    phone = models.CharField(max_length=32, blank=True, default='')
    role = models.CharField(max_length=100)
    password = models.CharField(max_length=128, blank=True, default='')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='userModel', null=True, blank=True)
    profilePic = models.ImageField(upload_to='media/images', null=True, blank=True)
    last_activity = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.name or self.email or f"UserModel {self.pk}"



class LoginHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='login_history')
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, null=True)  # Raw
    device = models.CharField(max_length=200, blank=True, null=True)  # Combined parsed result

    def __str__(self):
        return f"{self.user.username} logged in at {self.timestamp}"
