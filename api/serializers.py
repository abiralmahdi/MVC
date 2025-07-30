from rest_framework import serializers
from home.models import GlobalConfiguration

class GlobalConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = GlobalConfiguration
        fields = '__all__'


from accounts.models import UserModel

class UserModelSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserModel
        fields = '__all__'
