"""Apply the latest trained models to every meter and motor of the plant."""
import json
import logging
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from django.utils import timezone

from .devices import all_devices
from .features import CHANNEL_LABELS, CHANNELS, FEATURES, channel_features, hourly_alarm_counts, to_hourly
from .models import DeviceHealth, TrainingRun

logger = logging.getLogger('ml')

WINDOW_DAYS = 31
STALE_AFTER = timedelta(days=3)
MODE_LABELS = {
    'none': 'No specific failure pattern',
    'cooling': 'Cooling / heat dissipation problem',
    'power': 'Abnormal power draw',
}


class ModelBundle:
    def __init__(self, run):
        folder = Path(run.artifact_dir)
        self.run = run
        self.meta = json.loads((folder / 'meta.json').read_text())
        self.risk = xgb.Booster(model_file=str(folder / 'risk.json'))
        self.days = xgb.Booster(model_file=str(folder / 'days.json'))
        self.mode = xgb.Booster(model_file=str(folder / 'mode.json'))

    def predict(self, features_row):
        x = features_row[self.meta['features']]
        dm = xgb.DMatrix(x, feature_names=self.meta['features'], missing=np.nan)
        p = float(self.risk.predict(dm, iteration_range=(0, self.meta['risk_iterations']))[0])
        days = float(np.clip(self.days.predict(dm, iteration_range=(0, self.meta['days_iterations']))[0], 0, self.meta['days_cap']))
        contribs = self.risk.predict(dm, pred_contribs=True, iteration_range=(0, self.meta['risk_iterations']))[0][:-1]
        dm_mode = xgb.DMatrix(features_row[self.meta['mode_features']], feature_names=self.meta['mode_features'], missing=np.nan)
        probs = self.mode.predict(dm_mode, iteration_range=(0, self.meta['mode_iterations']))[0]
        return p, days, dict(zip(self.meta['features'], contribs)), dict(zip(self.meta['mode_classes'], map(float, probs)))


def latest_run():
    return (TrainingRun.objects.filter(status=TrainingRun.COMPLETED).exclude(artifact_dir='')
            .order_by('-finished_at').first())


def risk_level(probability, meta):
    """high / medium: alert levels that were right >= 80 % / >= 50 % of the time on unseen machines."""
    medium = meta.get('risk_threshold', 0.5)
    high = meta.get('risk_high_threshold', max(medium, 0.5))
    if probability >= high:
        return 'high'
    if probability >= medium:
        return 'medium'
    return 'low'


def _drivers(contribs, features_row, mapping):
    per_channel = {}
    for channel in CHANNELS:
        per_channel[channel] = sum(v for k, v in contribs.items() if k.startswith(channel + '_'))
    per_channel['alarms'] = contribs.get('alarms_24h', 0.0) + contribs.get('alarms_7d', 0.0)
    drivers = []
    for channel, value in sorted(per_channel.items(), key=lambda kv: -kv[1]):
        if value <= 0.05:
            continue
        if channel == 'alarms':
            count = features_row['alarms_7d'].iloc[0]
            if pd.notna(count) and count > 0:
                drivers.append({'channel': 'alarms', 'label': 'Recent alarms', 'measurement': '',
                                'detail': f"{int(count)} alarm(s) in 7 days", 'contribution': round(float(value), 3)})
            continue
        if channel not in mapping:
            continue
        z = features_row[f'{channel}_z24'].iloc[0]
        slope = features_row[f'{channel}_slope7'].iloc[0]
        direction = 'rising' if (z if pd.notna(z) else 0) >= 0 else 'falling'
        detail = f"{direction} ({z:+.1f}σ vs baseline" if pd.notna(z) else 'unusual'
        if pd.notna(z):
            detail += f", trend {slope:+.2f}σ/day)" if pd.notna(slope) else ')'
        drivers.append({'channel': channel, 'label': CHANNEL_LABELS[channel], 'measurement': mapping[channel],
                        'detail': detail, 'contribution': round(float(value), 3)})
    return drivers[:3]


def score_device(device, bundle, now=None):
    """Compute (and store) the DeviceHealth of one device."""
    now = now or timezone.now()
    mapping = device.channels
    lookup = {'meter': device.obj} if device.kind == 'meter' else {'motor': device.obj}
    health, _ = DeviceHealth.objects.get_or_create(**lookup)
    previous_risk = health.risk
    health.channels = mapping
    health.run = bundle.run if bundle else None
    health.failure_probability = health.days_to_maintenance = health.health_score = None
    health.failure_mode, health.failure_mode_probability, health.drivers, health.risk = '', None, [], 'unknown'

    if not mapping:
        health.status, health.hours_of_data = DeviceHealth.NO_SIGNALS, 0
        health.save()
        return health

    since = now - timedelta(days=WINDOW_DAYS)
    rows = device.history(since)
    last_seen = rows[-1][0] if rows else None
    # Score at the latest reading, so a meter that stopped reporting is judged on its last known state.
    end = min(now, last_seen) if last_seen else now
    hourly = to_hourly(rows, mapping, end=end, hours=WINDOW_DAYS * 24)
    health.hours_of_data = int(hourly.notna().any(axis=1).sum())
    alarm_times = device.alarm_times(since)
    alarms = hourly_alarm_counts(alarm_times, hourly.index) if alarm_times is not None else None
    features_row = channel_features(hourly, alarms).iloc[[-1]]
    health.last_data_at = last_seen

    has_baseline = any(pd.notna(features_row[f'{c}_z24'].iloc[0]) for c in mapping)
    if bundle is None:
        health.status = DeviceHealth.NO_MODEL
    elif not has_baseline:
        health.status = DeviceHealth.LEARNING
    else:
        p, days, contribs, mode_probs = bundle.predict(features_row)
        cap = bundle.meta['days_cap']
        if p < bundle.meta.get('days_min_probability', 0.0):
            days = cap          # no wear developing: nothing to count down
        health.status = DeviceHealth.OK
        health.failure_probability = round(p, 4)
        health.days_to_maintenance = round(days, 1)
        health.health_score = int(round(100 * (1 - p) * min(1.0, 0.5 + days / 60)))
        health.risk = risk_level(p, bundle.meta)
        machine_like = all(c in mapping for c in bundle.meta.get('mode_requires', []))
        failure_modes = {k: v for k, v in mode_probs.items() if k != 'none'}
        best = max(failure_modes, key=failure_modes.get) if failure_modes else None
        if health.risk != 'low' and machine_like and best and failure_modes[best] >= mode_probs.get('none', 0) * 0.5:
            health.failure_mode, health.failure_mode_probability = MODE_LABELS[best], round(failure_modes[best], 3)
        elif health.risk != 'low':
            health.failure_mode = MODE_LABELS['none'] if machine_like else 'Abnormal readings'
        health.drivers = _drivers(contribs, features_row, mapping)
    health.save()

    # Notify the relevant authorities when a machine newly enters (or escalates into) an alert level.
    if health.status == DeviceHealth.OK and health.risk in ('high', 'medium'):
        escalated = previous_risk not in ('high', 'medium') or (previous_risk == 'medium' and health.risk == 'high')
        if escalated:
            try:
                from home.notifications import notify_health
                notify_health(health, previous_risk)
            except Exception:
                logger.exception('Health notification failed for %s', device.name)
    return health


def score_devices(run=None, reporter=None, now=None):
    run = run or latest_run()
    bundle = ModelBundle(run) if run and run.artifact_dir else None
    devices = all_devices()
    results = []
    for i, device in enumerate(devices):
        try:
            results.append(score_device(device, bundle, now=now))
        except Exception:
            logger.exception('Scoring failed for %s', device.name)
        if reporter:
            reporter.within((i + 1) / max(1, len(devices)), f'Scoring {device.name}')
    return results
