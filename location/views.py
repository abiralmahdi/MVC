from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from alarms.models import Alarms
from dynamic.models import Site
from utils.access import admin_required, can_access_site, json_login_required, visible_sites
from utils.decorators import subscription_required


def _site_status(sites):
    """Unacknowledged alarms per site (ecological meters drive the map marker)."""
    counts = Alarms.objects.filter(acknowledged=False, meter__area__building__site__in=sites).values(
        'meter__area__building__site'
    ).annotate(
        total=Count('id'),
        ecological=Count('id', filter=Q(meter__ecological=True)),
    )
    by_site = {row['meter__area__building__site']: row for row in counts}
    result = []
    for site in sites:
        row = by_site.get(site.id, {})
        result.append({
            'id': site.id,
            'name': site.name,
            'latitude': site.latitude,
            'longitude': site.longitude,
            'alarm': bool(row.get('ecological')),
            'ecological_alarms': row.get('ecological', 0),
            'total_alarms': row.get('total', 0),
        })
    return result


@json_login_required
@subscription_required
def triggerAlarm(request, siteID):
    site = get_object_or_404(Site, id=siteID)
    if not can_access_site(request.user, site):
        return JsonResponse({'error': 'Not found'}, status=404)
    status = _site_status([site])[0]
    return JsonResponse({'alarm': status['alarm'], 'site': status})


@json_login_required
@subscription_required
def alarmStatus(request):
    return JsonResponse({'sites': _site_status(list(visible_sites(request.user)))})


@login_required
@subscription_required
@admin_required
def location(request):
    return render(request, 'location.html', {'sites': Site.objects.all().order_by('name')})
