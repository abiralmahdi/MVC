from django.shortcuts import redirect, render

from utils.decorators import subscription_required, subscription_revoked

from .features import get_config, landing_url


@subscription_required
def introPage(request):
    if not request.user.is_authenticated:
        return redirect('/accounts/login')
    target = landing_url(request.user, get_config(request))
    if target is None:
        return render(request, 'featureDisabled.html', {'feature_label': None, 'landing': None})
    return redirect(target)


@subscription_revoked
def subscriptionRevoked(request):
    return render(request, 'subscriptionRevoked.html')
