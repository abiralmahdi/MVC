from rest_framework import serializers
from home.models import GlobalConfiguration
from accounts.models import UserModel


class GlobalConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = GlobalConfiguration
        fields = '__all__'


class UserModelSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True, default='')
    is_superuser = serializers.BooleanField(source='user.is_superuser', read_only=True, default=False)
    last_login = serializers.DateTimeField(source='user.last_login', read_only=True, default=None)
    site = serializers.CharField(source='site.name', read_only=True, default=None)

    class Meta:
        model = UserModel
        # Never expose credentials (UserModel.password holds the raw password).
        fields = ['id', 'name', 'email', 'role', 'site', 'username', 'is_superuser', 'last_login', 'last_activity']


class RegisterUserSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, min_length=8)
    role = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    superuser = serializers.BooleanField(required=False, default=False)
    name = serializers.CharField(max_length=100, required=False, allow_blank=True, default='')
    site = serializers.IntegerField(required=False, allow_null=True, default=None)


class SubscriptionUpdateSerializer(serializers.Serializer):
    subscribed = serializers.BooleanField()
