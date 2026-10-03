"""Feature flags from GlobalConfiguration, enforced on the server.

Hiding a navbar link is not enough: every URL of a disabled module (pages and
the JSON endpoints its pages poll) is refused by ``FeatureGateMiddleware``.
"""
from django.http import JsonResponse
from django.shortcuts import render

from utils.access import get_user_site, is_admin

from .models import GlobalConfiguration

# (URL prefix, GlobalConfiguration flag, label, start page)
FEATURES = [
    ('/dashboard', 'dashboard', 'Dashboards', '/dashboard/'),
    ('/location', 'siteLocations', 'Site Locations', '/location/'),
    ('/scada', 'scada', 'SCADA', '/scada/'),
    ('/alarms', 'alarm', 'Alarms', '/alarms/allAlarms'),
    ('/reports', 'report', 'Reports', '/reports/'),
    ('/billing', 'billing', 'Billing', '/billing/'),
    ('/ml', 'machineLearning', 'Machine Learning', '/ml/'),
]

# Modules that are never a landing target (superuser-only tools).
_NOT_LANDING = {'machineLearning'}


def get_config(request):
    """The configuration row, loaded once per request (shared with the context processor)."""
    if not hasattr(request, '_global_configuration'):
        request._global_configuration = GlobalConfiguration.load()
    return request._global_configuration


def feature_for_path(path):
    for prefix, flag, label, start in FEATURES:
        if path == prefix or path.startswith(prefix + '/'):
            return flag, label
    return None


def landing_url(user, config):
    """First page a user should see, skipping disabled modules. None when nothing is enabled."""
    if is_admin(user) and config.siteLocations:
        return '/location/'
    if config.dashboard:
        site = get_user_site(user)
        if site is not None and not is_admin(user):
            return f'/dashboard/siteDashboard/{site.id}'
        return '/dashboard/'
    for prefix, flag, label, start in FEATURES:
        if flag in _NOT_LANDING:
            continue
        if flag == 'siteLocations' and not is_admin(user):
            continue
        if getattr(config, flag):
            return start
    return None


def _wants_json(request):
    accept = request.headers.get('Accept', '')
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in accept


class FeatureGateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        feature = feature_for_path(request.path)
        # Anonymous users fall through to the views' login redirect.
        if feature and request.user.is_authenticated:
            flag, label = feature
            config = get_config(request)
            if not getattr(config, flag):
                message = f'The {label} module is disabled.'
                if _wants_json(request):
                    return JsonResponse({'error': message}, status=403)
                return render(request, 'featureDisabled.html', {
                    'feature_label': label,
                    'landing': landing_url(request.user, config),
                }, status=403)
        return self.get_response(request)
