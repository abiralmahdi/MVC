from django.shortcuts import render
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
import json
from django.contrib.auth.models import User
from accounts.models import UserModel
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from home.models import GlobalConfiguration

class RegisterUser(APIView):
    authentication_classes = []  # Open: no token auth for now
    permission_classes = []      # No permission checks for now

    def post(self, request):
        # DRF auto-parses JSON:
        data = request.data
        role = data.get('role')
        username = data.get('username')
        password1 = data.get('password')
        superuser = data.get('superuser')

        if User.objects.filter(username=username).exists():
            return Response({"status": "user exists"}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.create_user(username=username, email=username, password=password1, first_name='')
        user.is_superuser = superuser
        user.is_staff = superuser
        user.save()
        print('USER CREATED')
        # ⚠️ Never store raw password in a separate model — maybe just omit it?
        usermodel = UserModel.objects.create(
            user=user,
            name='',
            role=role,
            email=username,
            password=password1,   # Consider removing this line!
            profilePic=''
        )
        print('USER MODEL CREATED')

        return Response({"status": "saved"}, status=status.HTTP_201_CREATED)

    def get(self, request):
        return Response({"status": "not allowed"}, status=status.HTTP_405_METHOD_NOT_ALLOWED)



from .serializers import GlobalConfigurationSerializer

class GlobalConfigurationView(APIView):
    def get(self, request):
        config = GlobalConfiguration.objects.first()
        if not config:
            return Response({"error": "No configuration found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = GlobalConfigurationSerializer(config)
        return Response(serializer.data, status=status.HTTP_200_OK)




@csrf_exempt
def updateSubscription(request):
    if request.method == 'POST':
        # Use request.body for JSON payloads:
        data = json.loads(request.body.decode('utf-8'))
        status = data.get('subscribed')
        print('Raw status:', status)

        # Cast safely
        status_bool = str(status).lower() in ['true', '1']

        config = GlobalConfiguration.objects.first()
        config.subscribed = status_bool
        config.report = status_bool
        config.dashboard = status_bool
        config.alarm = status_bool
        config.siteLocations = status_bool
        config.save()

        return JsonResponse({'status': 'done'})

    return JsonResponse({'error': 'Invalid method'}, status=405)



from rest_framework.generics import ListAPIView
from .serializers import UserModelSerializer

class UserModelListView(ListAPIView):
    queryset = UserModel.objects.all()
    serializer_class = UserModelSerializer