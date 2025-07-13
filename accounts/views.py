from django.shortcuts import render, redirect, HttpResponse, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from .models import *
from django.contrib.auth.decorators import login_required, user_passes_test

# Create your views here.
import httpagentparser
def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def login_(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)

            # Parse User-Agent for "Browser on OS"
            ua_string = request.META.get('HTTP_USER_AGENT', '')
            parsed = httpagentparser.detect(ua_string)
            browser = parsed.get('browser', {}).get('name', 'Unknown')
            os = parsed.get('os', {}).get('name', 'Unknown')
            device = f"{browser} on {os}"

            # Save login history
            LoginHistory.objects.create(
                user=user,
                ip_address=get_client_ip(request),
                user_agent=ua_string,
                device=device
            )

            # ✅ Use return!
            return redirect('/dashboard')

        else:
            return HttpResponse('Invalid username or password.')

    return render(request, 'login.html')


@login_required
def logout_view(request):
    logout(request)
    return redirect('/accounts/login')  


@login_required
@user_passes_test(lambda u: u.is_superuser)
def register(request):
    if request.method == 'POST':
        name = request.POST['name']
        role = request.POST['role']
        username = request.POST['email']
        email = request.POST['email']
        password1 = request.POST['password1']
        password2 = request.POST['password2']
        profilePic = request.FILES['profilePic']

        if password1 != password2:
            return HttpResponse('Passwords do not match.')

        if User.objects.filter(username=username).exists():
            return HttpResponse('Username already exists.')

        if User.objects.filter(email=email).exists():
            return HttpResponse('Email already registered.')

        user = User.objects.create_user(username=username, email=email, password=password1, first_name=name)
        user.save()
        usermodel = UserModel.objects.create(user=user, name=name, role=role, email=email, password=password1, profilePic=profilePic)
        usermodel.save()

        return redirect('/accounts/accountSettings')
    return render(request, 'register.html')

@login_required
def accountSettings(request):
    if (request.user.userModel.first() and ("Administrator" in request.user.userModel.first().role or "Manager" in request.user.userModel.first().role)) or request.user.is_superuser:
        users = UserModel.objects.all()
        context = {
            'users':users
        }
        return render(request, 'accountSettings.html', context)
    else:
        return HttpResponse("You are not authorized to view this page.")


from datetime import datetime, timedelta
@login_required
def loginHistory(request):
    if (request.user.userModel.first() and ("Administrator" in request.user.userModel.first().role or "Manager" in request.user.userModel.first().role)) or request.user.is_superuser:
        history = LoginHistory.objects.all().order_by('-timestamp')

        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')

        if start_date_str and end_date_str:
            try:
                # Parse dates from strings (YYYY-MM-DD)
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
                
                # Include the whole end day by adding one day and filtering less than that
                end_date_plus_one = end_date + timedelta(days=1)

                history = history.filter(timestamp__gte=start_date, timestamp__lt=end_date_plus_one)
            except ValueError:
                # Invalid date format, ignore filter or handle error as you want
                pass

        return render(request, 'loginHistory.html', {'history': history})
    else:
        return HttpResponse("You are not authorized to view this page")


from django.contrib.sessions.models import Session
from django.utils import timezone

def logout_user(user):
    sessions = Session.objects.filter(expire_date__gte=timezone.now())
    user_id = user.pk
    for session in sessions:
        data = session.get_decoded()
        if data.get('_auth_user_id') == str(user_id):
            session.delete()

@login_required
def terminateUser(request, userID):
    if (request.user.userModel.first() and ("Administrator" in request.user.userModel.first().role or "Manager" in request.user.userModel.first().role)) or request.user.is_superuser:
        user = User.objects.get(id=userID)
        logout_user(user)
        return redirect('/accounts/loginHistory')
    else:
        return HttpResponse("Unauthorized Entry")



@login_required
@user_passes_test(lambda u: u.is_superuser)
def editUser(request, userID):
    usermodel = get_object_or_404(UserModel, id=userID)

    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        role = request.POST.get('role')
        password = request.POST.get('password')
        profilePic = request.FILES.get('profilePic')

        # Update UserModel
        usermodel.name = name
        usermodel.email = email
        usermodel.role = role
        usermodel.password = password  # (Consider hashing if used!)
        if profilePic:
            usermodel.profilePic = profilePic
        usermodel.save()

        # Update linked auth User
        user = usermodel.user
        user.first_name = name
        user.email = email
        user.username = email  # assuming username is same as email
        user.set_password(password)
        user.save()

        return redirect('/accounts/accountSettings')

    return redirect('/accounts/accountSettings')


@login_required
@user_passes_test(lambda u: u.is_superuser)
def deleteUser(request, userID):
    usermodel = get_object_or_404(UserModel, id=userID)
    user = usermodel.user
    usermodel.delete()
    user.delete()
    return redirect('/accounts/accountSettings')