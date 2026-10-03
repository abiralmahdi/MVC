# utils/decorators.py
from django.shortcuts import redirect
from functools import wraps
from home.models import GlobalConfiguration


def subscription_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if GlobalConfiguration.load().subscribed:
            return view_func(request, *args, **kwargs)
        return redirect('/subscription-revoked')
    return _wrapped_view


def subscription_revoked(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not GlobalConfiguration.load().subscribed:
            return view_func(request, *args, **kwargs)
        return redirect('/')
    return _wrapped_view
