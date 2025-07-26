# utils/decorators.py
from django.shortcuts import redirect
from django.http import HttpResponse
from functools import wraps
from home.models import GlobalConfiguration 

def subscription_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        config = GlobalConfiguration.objects.first()
        if config and config.subscribed:
            return view_func(request, *args, **kwargs)
        return redirect('/subscription-revoked')
    return _wrapped_view


def subscription_revoked(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        config = GlobalConfiguration.objects.first()
        if config and not config.subscribed:
            return view_func(request, *args, **kwargs)
        return redirect('/location')
    return _wrapped_view