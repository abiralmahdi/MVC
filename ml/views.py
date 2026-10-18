from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from utils.access import json_login_required, superuser_required

from . import datasets
from .devices import all_devices
from .features import CHANNEL_LABELS, CHANNELS
from .models import DeviceHealth, TrainingRun
from .runner import active_run, launch_training
from .scoring import latest_run, score_devices
from .training import STAGES


def _run_payload(run):
    if run is None:
        return None
    return {
        'id': run.pk,
        'status': run.status,
        'progress': run.progress,
        'stage': run.stage,
        'message': run.message,
        'log': run.log.splitlines()[-120:],
        'metrics': run.metrics,
        'error': run.error.strip().splitlines()[-1] if run.error else '',
        'started_at': run.started_at.isoformat() if run.started_at else None,
        'finished_at': run.finished_at.isoformat() if run.finished_at else None,
        'duration': run.duration_seconds,
    }


def _location(device):
    """(site, building, area, load type) of a device; area/load type are blank for motors."""
    obj = device.obj
    if device.kind == 'meter' and getattr(obj, 'area', None):
        building = obj.area.building
        return building.site.name, building.name, obj.area.name, (obj.loadType.name if obj.loadType_id else '')
    if device.kind == 'motor' and getattr(obj, 'building', None):
        return obj.building.site.name, obj.building.name, '', ''
    return '', '', '', ''


def lifespan_elapsed(health):
    """How much of the device's life is used up (%), derived from the ML health score."""
    if health is None or health.health_score is None:
        return None
    return max(0, min(100, 100 - health.health_score))


def _device_rows():
    health = {}
    for item in DeviceHealth.objects.select_related('run'):
        health[('meter', item.meter_id) if item.meter_id else ('motor', item.motor_id)] = item
    rows = []
    for device in all_devices():
        item = health.get((device.kind, device.obj.pk))
        site, building, area, load_type = _location(device)
        rows.append({
            'device': device,
            'channels': [(CHANNEL_LABELS[c].split(' (')[0], device.channels[c]) for c in CHANNELS if c in device.channels],
            'health': item,
            'site': site, 'building': building, 'area': area, 'load_type': load_type,
            'lifespan': lifespan_elapsed(item),
        })
    order = {'high': 0, 'medium': 1, 'low': 2, 'unknown': 3}
    rows.sort(key=lambda r: (order.get(r['health'].risk if r['health'] else 'unknown', 3), r['device'].kind, r['device'].name))
    return rows


def _ml_context():
    current = active_run() or TrainingRun.objects.first()
    rows = _device_rows()
    summary = {
        'devices': len(rows),
        'supported': sum(1 for r in rows if r['channels']),
        'high': sum(1 for r in rows if r['health'] and r['health'].risk == 'high'),
        'medium': sum(1 for r in rows if r['health'] and r['health'].risk == 'medium'),
    }
    return {
        'current': current,
        'current_payload': _run_payload(current),
        'model_run': latest_run(),
        'runs': TrainingRun.objects.select_related('triggered_by')[:12],
        'stages': [{'key': k, 'title': t, 'start': s, 'end': e} for k, t, s, e in STAGES],
        'datasets': [{'dataset': d, 'size_mb': round(datasets.cached_size(d) / 1e6, 1)} for d in datasets.DATASETS],
        'rows': rows,
        'summary': summary,
        'channel_labels': CHANNEL_LABELS,
        'filters': {
            'sites': sorted({r['site'] for r in rows if r['site']}),
            'buildings': sorted({r['building'] for r in rows if r['building']}),
            'areas': sorted({r['area'] for r in rows if r['area']}),
            'load_types': sorted({r['load_type'] for r in rows if r['load_type']}),
        },
    }


@login_required
@superuser_required
def machine_learning(request):
    """Clean page: only the devices & motors list. Full detail lives at /ml-details."""
    return render(request, 'ml/machine_learning.html', _ml_context())


@login_required
@superuser_required
def machine_learning_details(request):
    """Hidden full view: training progress, model quality, datasets and history."""
    return render(request, 'ml/machine_learning_details.html', _ml_context())


@login_required
@superuser_required
@require_POST
def start_training(request):
    running = active_run()
    if running:
        messages.warning(request, f'Training run #{running.pk} is already in progress.')
        return redirect('/ml-details')
    run = TrainingRun.objects.create(triggered_by=request.user, stage='Starting', message='Starting the training process')
    try:
        launch_training(run)
    except Exception as exc:
        run.status, run.error, run.message = TrainingRun.FAILED, str(exc), 'Could not start the training process'
        run.save()
        messages.error(request, f'Could not start training: {exc}')
        return redirect('/ml-details')
    messages.success(request, f'Training run #{run.pk} started.')
    return redirect('/ml-details')


@json_login_required
@superuser_required
def training_status(request, run_id):
    active_run()   # fails runs whose process died
    return JsonResponse({'run': _run_payload(get_object_or_404(TrainingRun, pk=run_id))})


@login_required
@superuser_required
@require_POST
def score_now(request):
    run = latest_run()
    if run is None:
        messages.error(request, 'Train the models first.')
        return redirect('/ml/')
    results = score_devices(run=run)
    scored = sum(1 for r in results if r.status == DeviceHealth.OK)
    messages.success(request, f'Scored {len(results)} devices ({scored} with enough data).')
    return redirect('/ml/#devices')
