from datetime import datetime, timedelta

import httpagentparser
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from dynamic.models import Site
from utils.access import ROLES, manager_required, superuser_required
from utils.decorators import subscription_required

from .models import LoginHistory, UserModel

ACTIVE_WINDOW = timedelta(minutes=5)


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def login_(request):
    if request.user.is_authenticated and request.method == 'GET':
        return redirect('/')

    error = None
    next_url = request.POST.get('next') or request.GET.get('next') or ''
    if request.method == 'POST':
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            ua_string = request.META.get('HTTP_USER_AGENT', '')
            parsed = httpagentparser.detect(ua_string)
            browser = parsed.get('browser', {}).get('name', 'Unknown')
            os_name = parsed.get('os', {}).get('name', 'Unknown')
            LoginHistory.objects.create(
                user=user,
                ip_address=get_client_ip(request),
                user_agent=ua_string[:2000],
                device=f"{browser} on {os_name}"[:200],
            )
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                return redirect(next_url)
            return redirect('/')
        error = 'Invalid username or password.'

    return render(request, 'login.html', {'error': error, 'next': next_url, 'username': request.POST.get('username', '')})


def logout_view(request):
    logout(request)
    return redirect('/accounts/login')


def _validate_new_password(password1, password2, user=None):
    if password1 != password2:
        return ['Passwords do not match.']
    try:
        validate_password(password1, user=user)
    except ValidationError as exc:
        return list(exc.messages)
    return []


@login_required
@superuser_required
def register(request):
    form = {}
    if request.method == 'POST':
        form = request.POST
        name = (request.POST.get('name') or '').strip()
        role = request.POST.get('role')
        email = (request.POST.get('email') or '').strip().lower()
        phone = (request.POST.get('phone') or '').strip()
        password1 = request.POST.get('password1') or ''
        password2 = request.POST.get('password2') or ''
        site = Site.objects.filter(id=request.POST.get('site') or 0).first()

        errors = []
        if not name or not email:
            errors.append('Name and email are required.')
        if role not in ROLES:
            errors.append('Select a valid role.')
        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            errors.append('A user with this email already exists.')
        errors += _validate_new_password(password1, password2, User(username=email, email=email, first_name=name))

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            with transaction.atomic():
                user = User.objects.create_user(username=email, email=email, password=password1, first_name=name)
                UserModel.objects.create(
                    user=user, name=name, role=role, email=email, site=site, password=password1,
                    phone=phone, profilePic=request.FILES.get('profilePic'),
                )
            messages.success(request, f"User {email} created.")
            return redirect('/accounts/accountSettings')

    return render(request, 'register.html', {'sites': Site.objects.all(), 'roles': ROLES, 'form': form})


@login_required
@manager_required
def accountSettings(request):
    users = UserModel.objects.select_related('user', 'site').order_by('name')
    context = {
        'users': users,
        'sites': Site.objects.all(),
        'roles': ROLES,
    }
    return render(request, 'accountSettings.html', context)


@login_required
@subscription_required
@manager_required
def loginHistory(request):
    history = LoginHistory.objects.select_related('user').prefetch_related('user__userModel').order_by('-timestamp')

    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    try:
        if start_date_str:
            start = timezone.make_aware(datetime.strptime(start_date_str, '%Y-%m-%d'))
            history = history.filter(timestamp__gte=start)
        if end_date_str:
            end = timezone.make_aware(datetime.strptime(end_date_str, '%Y-%m-%d')) + timedelta(days=1)
            history = history.filter(timestamp__lt=end)
    except ValueError:
        messages.warning(request, 'Invalid date filter ignored.')

    history = list(history[:500])
    now = timezone.now()
    for log in history:
        profile = next(iter(log.user.userModel.all()), None)
        log.role = profile.role if profile else 'N/A'
        if profile is None or profile.last_activity is None:
            log.activity = 'unknown'
        elif now - profile.last_activity <= ACTIVE_WINDOW:
            log.activity = 'active'
        else:
            log.activity = 'inactive'

    return render(request, 'loginHistory.html', {
        'history': history,
        'start_date': start_date_str or '',
        'end_date': end_date_str or '',
    })


def logout_user(user):
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        if session.get_decoded().get('_auth_user_id') == str(user.pk):
            session.delete()


@login_required
@subscription_required
@manager_required
@require_POST
def terminateUser(request, userID):
    user = get_object_or_404(User, id=userID)
    if user.is_superuser and not request.user.is_superuser:
        messages.error(request, "Only superusers can terminate a superuser's sessions.")
        return redirect('/accounts/loginHistory')
    logout_user(user)
    messages.success(request, f"All sessions of {user.username} were terminated.")
    if user.pk == request.user.pk:
        return redirect('/accounts/login')
    return redirect('/accounts/loginHistory')


@login_required
@superuser_required
@require_POST
def editUser(request, userID):
    usermodel = get_object_or_404(UserModel.objects.select_related('user'), id=userID)
    user = usermodel.user

    name = (request.POST.get('name') or '').strip()
    email = (request.POST.get('email') or '').strip().lower()
    role = request.POST.get('role')
    password = request.POST.get('password') or ''
    site = Site.objects.filter(id=request.POST.get('site') or 0).first()

    errors = []
    if not name or not email:
        errors.append('Name and email are required.')
    if role not in ROLES:
        errors.append('Select a valid role.')
    if user and User.objects.filter(username__iexact=email).exclude(pk=user.pk).exists():
        errors.append('Another user already uses this email.')
    if password:
        errors += _validate_new_password(password, request.POST.get('password_confirm') or '', user)
    if errors:
        for error in errors:
            messages.error(request, error)
        return redirect('/accounts/accountSettings')

    with transaction.atomic():
        usermodel.name = name
        usermodel.email = email
        usermodel.role = role
        usermodel.site = site
        usermodel.phone = (request.POST.get('phone') or '').strip()
        if password:
            usermodel.password = password
        if request.FILES.get('profilePic'):
            usermodel.profilePic = request.FILES['profilePic']
        usermodel.save()

        if user:
            user.first_name = name
            user.email = email
            user.username = email
            if password:
                user.set_password(password)
            user.save()
            if password and user.pk == request.user.pk:
                update_session_auth_hash(request, user)

    messages.success(request, f"User {email} updated.")
    return redirect('/accounts/accountSettings')


@login_required
@superuser_required
@require_POST
def deleteUser(request, userID):
    usermodel = get_object_or_404(UserModel, id=userID)
    user = usermodel.user
    if user and user.pk == request.user.pk:
        messages.error(request, "You cannot delete your own account.")
        return redirect('/accounts/accountSettings')
    with transaction.atomic():
        usermodel.delete()
        if user:
            user.delete()
    messages.success(request, "User deleted.")
    return redirect('/accounts/accountSettings')
