"""Role and site helpers shared by all apps.

Every view used to do ``request.user.userModel.first().role`` which raises
AttributeError (HTTP 500) for anonymous users, users without a profile and
profiles without a site. These helpers never raise.
"""
from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden, JsonResponse

ADMIN_ROLE = 'Administrator'
MANAGER_ROLE = 'Manager'

# Roles offered when creating users / gadgets.
ROLES = [
    'Administrator',
    'Operator',
    'Quality Manager',
    'Shift Manager',
    'Maintenance Personnel',
    'Setup Technician',
]

# Roles allowed to send start/stop commands to plant equipment.
EQUIPMENT_CONTROL_ROLES = {'Administrator', 'Operator', 'Shift Manager'}


def get_profile(user):
    if user is None or not user.is_authenticated:
        return None
    cache_attr = '_mvc_profile_cache'
    if not hasattr(user, cache_attr):
        setattr(user, cache_attr, user.userModel.select_related('site').first())
    return getattr(user, cache_attr)


def get_role(user):
    profile = get_profile(user)
    return (profile.role or '') if profile else ''


def get_user_site(user):
    profile = get_profile(user)
    return profile.site if profile else None


def is_admin(user):
    """Superusers and the Administrator role see every site."""
    if user is None or not user.is_authenticated:
        return False
    return user.is_superuser or get_role(user) == ADMIN_ROLE


def is_manager(user):
    """Administrators, Managers and superusers may manage accounts and view login history."""
    if user is None or not user.is_authenticated:
        return False
    role = get_role(user)
    return user.is_superuser or ADMIN_ROLE in role or MANAGER_ROLE in role


def can_control_equipment(user):
    if user is None or not user.is_authenticated:
        return False
    return user.is_superuser or get_role(user) in EQUIPMENT_CONTROL_ROLES


def can_access_site(user, site):
    if user is None or not user.is_authenticated or site is None:
        return is_admin(user)
    if is_admin(user):
        return True
    user_site = get_user_site(user)
    return user_site is not None and user_site.pk == site.pk


def visible_sites(user):
    """Sites the user is allowed to see, as a queryset."""
    from dynamic.models import Site

    if is_admin(user):
        return Site.objects.all()
    site = get_user_site(user)
    if site is None:
        return Site.objects.none()
    return Site.objects.filter(pk=site.pk)


def _wants_json(request):
    accept = request.headers.get('Accept', '')
    return (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or 'application/json' in accept
        or request.path.startswith('/api/')
    )


def _deny(request, message, status=403):
    if not request.user.is_authenticated:
        if _wants_json(request):
            return JsonResponse({'error': 'Authentication required'}, status=401)
        return redirect_to_login(request.get_full_path())
    if _wants_json(request):
        return JsonResponse({'error': message}, status=status)
    return HttpResponseForbidden(message)


def admin_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not is_admin(request.user):
            return _deny(request, 'You are not authorized to view this page.')
        return view_func(request, *args, **kwargs)
    return _wrapped


def manager_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not is_manager(request.user):
            return _deny(request, 'You are not authorized to view this page.')
        return view_func(request, *args, **kwargs)
    return _wrapped


def superuser_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not (request.user.is_authenticated and request.user.is_superuser):
            return _deny(request, 'Only superusers can perform this action.')
        return view_func(request, *args, **kwargs)
    return _wrapped


def json_login_required(view_func):
    """Like login_required, but answers 401 JSON instead of redirecting (for fetch/axios endpoints)."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        return view_func(request, *args, **kwargs)
    return _wrapped
