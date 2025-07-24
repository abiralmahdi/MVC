from rest_framework import serializers
from home.models import GlobalConfiguration

class GlobalConfigurationSerializer(serializers.ModelSerializer):
    class Meta:
        model = GlobalConfiguration
        fields = '__all__'