import hmac

from django.conf import settings
from rest_framework.permissions import BasePermission

API_KEY_HEADER = 'X-API-Key'


def has_valid_master_key(request):
    """True when the request carries the MVC_Master shared secret.

    If no key is configured the API is closed (fail-safe), so a fresh install
    can never be taken over through /api/*.
    """
    expected = getattr(settings, 'MVC_MASTER_API_KEY', '') or ''
    provided = request.headers.get(API_KEY_HEADER, '') or ''
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected.encode(), provided.encode())


class HasMasterApiKey(BasePermission):
    message = 'A valid X-API-Key header is required.'

    def has_permission(self, request, view):
        return has_valid_master_key(request)
