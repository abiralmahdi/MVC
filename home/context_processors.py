from django.conf import settings

from .features import get_config


def _initials(name):
    parts = [p for p in (name or '').replace('@', ' ').replace('.', ' ').split() if p]
    return ''.join(p[0] for p in parts[:2]).upper() or '?'


def global_configuration(request):
    """Expose the feature flags, plant time zone and navbar data to every template."""
    config = get_config(request)
    context = {'config': config, 'TIME_ZONE': settings.TIME_ZONE, 'ASSET_VERSION': settings.ASSET_VERSION}

    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated:
        from utils.access import get_profile, is_admin, is_manager

        profile = get_profile(user)
        display_name = (profile.name if profile and profile.name else None) or user.get_full_name() or user.username
        context.update({
            'nav_profile': profile,
            'nav_display_name': display_name,
            'nav_initials': _initials(display_name),
            'nav_role': (profile.role if profile and profile.role else ('Superuser' if user.is_superuser else '')),
            'nav_is_admin': is_admin(user),
            'nav_is_manager': is_manager(user),
        })
        if config.alarm:
            from alarms.models import Alarms
            from utils.access import visible_sites

            context['nav_alarm_count'] = Alarms.objects.filter(
                acknowledged=False, meter__area__building__site__in=visible_sites(user)
            ).count()
    return context
