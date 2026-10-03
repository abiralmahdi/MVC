"""Machine-to-machine API used only by the MVC_Master vendor console.

Every endpoint requires the shared secret in the ``X-API-Key`` header
(see ``api.permissions.HasMasterApiKey`` and ``settings.MVC_MASTER_API_KEY``).
"""
import logging

from django.contrib.auth.models import User
from django.db import transaction
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import UserModel
from dynamic.models import Site
from home.models import GlobalConfiguration

from .serializers import (
    GlobalConfigurationSerializer,
    RegisterUserSerializer,
    SubscriptionUpdateSerializer,
    UserModelSerializer,
)

logger = logging.getLogger('api')


class RegisterUser(APIView):
    def post(self, request):
        serializer = RegisterUserSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"status": "invalid", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data

        username = data['username'].strip()
        if User.objects.filter(username=username).exists():
            return Response({"status": "user exists"}, status=status.HTTP_400_BAD_REQUEST)

        site = Site.objects.filter(pk=data['site']).first() if data.get('site') else None

        with transaction.atomic():
            user = User.objects.create_user(
                username=username,
                email=username,
                password=data['password'],
                first_name=data.get('name', ''),
            )
            user.is_superuser = data['superuser']
            user.is_staff = data['superuser']
            user.save(update_fields=['is_superuser', 'is_staff'])
            UserModel.objects.create(
                user=user,
                name=data.get('name', ''),
                role=data.get('role', ''),
                email=username,
                site=site,
                password=data['password'],
            )

        logger.info("User %s created through the master API (superuser=%s)", username, data['superuser'])
        return Response({"status": "saved"}, status=status.HTTP_201_CREATED)


class GlobalConfigurationView(APIView):
    def get(self, request):
        serializer = GlobalConfigurationSerializer(GlobalConfiguration.load())
        return Response(serializer.data, status=status.HTTP_200_OK)


class UpdateSubscription(APIView):
    def post(self, request):
        serializer = SubscriptionUpdateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({"error": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        subscribed = serializer.validated_data['subscribed']
        config = GlobalConfiguration.load()
        config.subscribed = subscribed
        config.report = subscribed
        config.dashboard = subscribed
        config.alarm = subscribed
        config.siteLocations = subscribed
        config.billing = subscribed
        config.save()

        logger.warning("Subscription set to %s by the master console", subscribed)
        return Response({'status': 'done', 'subscribed': subscribed})


class UserModelListView(ListAPIView):
    queryset = UserModel.objects.select_related('user', 'site').order_by('id')
    serializer_class = UserModelSerializer
