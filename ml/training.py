"""Training pipeline for the predictive-maintenance models (XGBoost).

Three models are trained:

* risk   - probability that the machine fails within the next 7 days (binary classifier)
* days   - days until failure / required maintenance, learned from machines that were
           actually failing (regressor); it is only used when the risk model sees wear
           developing, otherwise the estimate is "30+ days"
* mode   - most likely failure type for rotating/electrical equipment: cooling
           (heat dissipation) or abnormal power draw (multi-class)

Training data (all converted to the device-independent channel features of ml.features):

* Azure fleet telemetry teaches *imminent* failures: its sensors and error events
  deviate in the last 1-2 days before a component fails. Rows 2-30 days before a
  failure carry no precursor signal in that data, so they are left out instead of
  teaching the model noise.
* NASA C-MAPSS run-to-failure engines teach *gradual* wear: temperatures, pressures and
  speeds drift for weeks before failure (one engine cycle is treated as one day).
* AI4I 2020 teaches which failure type an abnormal operating point resembles.

Random channels are hidden during training so the models also work for devices that
measure only some of the signals (a water meter has no vibration sensor).
"""
import json
import logging
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb
from django.conf import settings
from django.utils import timezone
from sklearn.metrics import (accuracy_score, average_precision_score, confusion_matrix, f1_score,
                             mean_absolute_error, precision_score, recall_score, roc_auc_score)
from sklearn.model_selection import GroupShuffleSplit, train_test_split

from . import datasets
from .features import BASELINE_HOURS, CHANNELS, FEATURES, channel_features, hourly_alarm_counts
from .models import TrainingRun

logger = logging.getLogger('ml')

HORIZON_DAYS = 7
DAYS_CAP = 30
SNAPSHOT_STRIDE_HOURS = 6
MODE_FEATURES = [f'{c}_z24' for c in CHANNELS]
MODE_CLASSES = ['none', 'cooling', 'power']
MODE_REQUIRES = ['electrical', 'load']
# Alarm counts are not model inputs: error codes in the fleet data precede failures by a day, while plant
# alarms are process-limit excursions - learning one as the other would make every alarm look like a breakdown.
MODEL_FEATURES = [f for f in FEATURES if not f.startswith('alarms')]
AZURE_CHANNELS = {'volt': 'electrical', 'rotate': 'load', 'pressure': 'process', 'vibration': 'stress'}
# C-MAPSS sensors: fuel flow ratio (power-like), core speed, LPT outlet temperature, HPC static pressure.
CMAPSS_CHANNELS = {'s12': 'electrical', 's9': 'load', 's4': 'process', 's11': 'stress'}
AZURE_SIGNAL_DAYS = 2

STAGES = [
    ('download', 'Download datasets', 0, 15),
    ('features', 'Prepare features', 15, 40),
    ('risk', 'Train failure-risk model', 40, 62),
    ('days', 'Train days-to-maintenance model', 62, 78),
    ('mode', 'Train failure-type model', 78, 90),
    ('save', 'Evaluate & save', 90, 95),
    ('score', 'Score plant devices', 95, 100),
]
STAGE_RANGES = {key: (start, end) for key, _, start, end in STAGES}
STAGE_TITLES = {key: title for key, title, _, _ in STAGES}


class Reporter:
    """Writes progress to the TrainingRun (throttled so SQLite is not hammered)."""

    def __init__(self, run, min_interval=1.0):
        self.run = run
        self.min_interval = min_interval
        self._last_save = 0.0
        self.stage_key = None
        self._lines = run.log.splitlines() if run.log else []

    def stage(self, key):
        self.stage_key = key
        self.run.stage = STAGE_TITLES[key]
        self.run.progress = STAGE_RANGES[key][0]
        self.log(f"▶ {STAGE_TITLES[key]}")
        self.save(force=True)

    def within(self, fraction, message=None):
        start, end = STAGE_RANGES[self.stage_key]
        self.run.progress = round(start + (end - start) * max(0.0, min(1.0, fraction)), 1)
        if message is not None:
            self.run.message = message[:500]
        self.save()

    def log(self, line):
        stamp = timezone.localtime().strftime('%H:%M:%S')
        self._lines.append(f"[{stamp}] {line}")
        self._lines = self._lines[-400:]
        self.run.log = '\n'.join(self._lines)
        logger.info(line)
        self.save()

    def metric(self, key, value):
        self.run.metrics[key] = value
        self.save()

    def save(self, force=False):
        now = time.monotonic()
        if force or now - self._last_save >= self.min_interval:
            self.run.save(update_fields=['stage', 'progress', 'message', 'log', 'metrics', 'status', 'updated_at'])
            self._last_save = now


def artifacts_root():
    root = Path(settings.ML_ARTIFACTS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------

def build_fleet_frame(telemetry, errors, failures, reporter=None):
    """Snapshot feature rows with labels from fleet telemetry (Azure format)."""
    telemetry = telemetry.rename(columns=AZURE_CHANNELS)
    machines = sorted(telemetry['machineID'].unique())
    errors_by_machine = {m: g['datetime'] for m, g in errors.groupby('machineID')}
    failures_by_machine = {m: np.sort(g['datetime'].values) for m, g in failures.groupby('machineID')}
    frames = []
    for i, machine in enumerate(machines):
        g = telemetry[telemetry['machineID'] == machine].set_index('datetime').sort_index()
        g = g[~g.index.duplicated()]
        hourly = g[CHANNELS].asfreq('h')
        hourly.index = hourly.index.tz_localize('UTC')
        alarms = hourly_alarm_counts(errors_by_machine.get(machine, pd.Series(dtype='datetime64[ns]')), hourly.index)
        feats = channel_features(hourly, alarms)
        snap = feats.iloc[BASELINE_HOURS::SNAPSHOT_STRIDE_HOURS].copy()
        t = snap.index.tz_localize(None).values
        end = hourly.index[-1].tz_localize(None).to_datetime64()
        fails = failures_by_machine.get(machine, np.array([], dtype='datetime64[ns]'))
        pos = np.searchsorted(fails, t, side='right')
        has_next = pos < len(fails)
        next_fail = np.where(has_next, fails[np.minimum(pos, max(len(fails) - 1, 0))] if len(fails) else t, t)
        days = np.where(has_next, (next_fail - t) / np.timedelta64(1, 'D'), np.nan)
        days_left_in_data = (end - t) / np.timedelta64(1, 'D')
        snap['days_to_failure'] = days
        snap['observed_days'] = days_left_in_data
        snap['machine'] = f'azure-{machine}'
        snap['source'] = 'azure'
        frames.append(snap)
        if reporter:
            reporter.within((i + 1) / len(machines), f'Features for machine {i + 1}/{len(machines)}')
    return add_labels(pd.concat(frames, ignore_index=True))


def build_degradation_frame(engines, rng, reporter=None):
    """Snapshot rows from run-to-failure engines (C-MAPSS format); one cycle = one day of 24 hourly samples."""
    frames = []
    units = sorted(engines['unit'].unique())
    min_days = BASELINE_HOURS // 24 + 8
    for i, unit in enumerate(units):
        g = engines[engines['unit'] == unit].sort_values('cycle')
        n = len(g)
        if n < min_days:
            continue
        index = pd.date_range('2020-01-01', periods=n * 24, freq='h', tz='UTC')
        data = {}
        for sensor, channel in CMAPSS_CHANNELS.items():
            values = g[sensor].to_numpy(dtype=float)
            spread = values[:30].std() or abs(values[:30].mean()) * 0.001 or 1e-3
            data[channel] = np.repeat(values, 24) + rng.normal(0, 0.5 * spread, n * 24)
        feats = channel_features(pd.DataFrame(data, index=index))
        positions = np.arange(BASELINE_HOURS + 23, n * 24, 24)
        snap = feats.iloc[positions].copy()
        rul = (n - 1) - positions // 24
        snap['days_to_failure'] = rul.astype(float)
        snap['observed_days'] = rul.astype(float)
        snap['machine'] = f'engine-{unit}'
        snap['source'] = 'cmapss'
        frames.append(snap)
        if reporter:
            reporter.within((i + 1) / len(units), f'Degradation features for engine {i + 1}/{len(units)}')
    return add_labels(pd.concat(frames, ignore_index=True))


def add_labels(frame):
    # Binary label: failure within the horizon (drop rows whose horizon runs past the end of the data).
    frame['fail_7d'] = np.where(frame['days_to_failure'] <= HORIZON_DAYS, 1.0,
                                np.where(frame['observed_days'] >= HORIZON_DAYS, 0.0, np.nan))
    # Regression target, right-censored at DAYS_CAP.
    frame['days_target'] = np.where(frame['days_to_failure'].notna(), np.minimum(frame['days_to_failure'], DAYS_CAP),
                                    np.where(frame['observed_days'] >= DAYS_CAP, DAYS_CAP, np.nan))
    usable = frame[[f'{c}_z24' for c in CHANNELS]].notna().any(axis=1)
    return frame[usable].reset_index(drop=True)


def mask_channels(frame, rng, feature_cols, p_drop=0.4, p_alarm_drop=0.5):
    """Copy of ``frame`` where random channels are hidden, as on devices that lack those sensors."""
    masked = frame.copy()
    keep = rng.random((len(frame), len(CHANNELS))) >= p_drop
    none_kept = ~keep.any(axis=1)
    keep[none_kept, rng.integers(0, len(CHANNELS), none_kept.sum())] = True
    for j, channel in enumerate(CHANNELS):
        cols = [c for c in feature_cols if c.startswith(channel + '_')]
        masked.loc[~keep[:, j], cols] = np.nan
    if 'alarms_7d' in feature_cols:
        drop_alarms = rng.random(len(frame)) < p_alarm_drop
        masked.loc[drop_alarms, ['alarms_24h', 'alarms_7d']] = np.nan
    return masked


def build_mode_frame(ai4i):
    """AI4I operating points as channel deviations with a failure-type label."""
    df = ai4i.copy()
    power = df['Torque [Nm]'] * df['Rotational speed [rpm]'] * 2 * np.pi / 60.0
    signals = pd.DataFrame({
        'electrical': power,
        'load': df['Rotational speed [rpm]'],
        'process': df['Process temperature [K]'] - df['Air temperature [K]'],
        'stress': df['Torque [Nm]'],
    })
    healthy = df['Machine failure'] == 0
    z = (signals - signals[healthy].mean()) / signals[healthy].std()
    frame = pd.DataFrame({f'{c}_z24': z[c] for c in CHANNELS})
    label = np.select([df['HDF'] == 1, df['PWF'] == 1], ['cooling', 'power'], 'none')
    # Tool-wear, overstrain (torque x tool wear) and random failures cannot be explained without a
    # tool-wear signal, which plant devices do not have: leave them out.
    unexplained = (df['Machine failure'] == 1) & (label == 'none')
    frame['label'] = label
    return frame[~unexplained].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Training helpers
# ---------------------------------------------------------------------------

class ProgressCallback(xgb.callback.TrainingCallback):
    def __init__(self, reporter, total_rounds, curve_key, every=5):
        self.reporter = reporter
        self.total = total_rounds
        self.curve_key = curve_key
        self.every = every

    def after_iteration(self, model, epoch, evals_log):
        if epoch % self.every == 0 or epoch + 1 == self.total:
            curves = {}
            for data_name, metrics in evals_log.items():
                for metric, values in metrics.items():
                    curves[f'{data_name}_{metric}'] = [round(float(v), 5) for v in values[::self.every]]
            self.reporter.run.metrics.setdefault('curves', {})[self.curve_key] = curves
            self.reporter.within((epoch + 1) / self.total, f'{STAGE_TITLES[self.reporter.stage_key]}: round {epoch + 1}/{self.total}')
        return False


def _train(params, dtrain, dval, rounds, reporter, curve_key):
    return xgb.train(
        params, dtrain, num_boost_round=rounds, evals=[(dtrain, 'train'), (dval, 'validation')],
        early_stopping_rounds=max(20, rounds // 8), verbose_eval=False,
        callbacks=[ProgressCallback(reporter, rounds, curve_key)],
    )


def channel_importance(booster, feature_names):
    gain = booster.get_score(importance_type='total_gain')
    per_feature = {name: float(gain.get(name, 0.0)) for name in feature_names}
    total = sum(per_feature.values()) or 1.0
    per_channel = {c: round(sum(v for k, v in per_feature.items() if k.startswith(c + '_')) / total, 4) for c in CHANNELS}
    per_channel['alarms'] = round(sum(v for k, v in per_feature.items() if k.startswith('alarms')) / total, 4)
    top = sorted(((k, round(v / total, 4)) for k, v in per_feature.items()), key=lambda kv: -kv[1])[:12]
    return per_channel, top


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class _SubReporter:
    """Maps 0..1 progress of a sub-step onto part of the current stage."""

    def __init__(self, reporter, start, end):
        self.reporter, self.start, self.end = reporter, start, end

    def within(self, fraction, message=None):
        self.reporter.within(self.start + (self.end - self.start) * fraction, message)


def train_models(run, fleet_frames=None, engines=None, ai4i=None, rounds=(500, 500, 300), score=True, seed=42):
    """Run the whole pipeline for ``run``. Data frames can be injected (tests); otherwise datasets are downloaded."""
    reporter = Reporter(run)
    run.status = TrainingRun.RUNNING
    run.started_at = timezone.now()
    run.error = ''
    run.metrics = {'stages': [{'key': k, 'title': t} for k, t, _, _ in STAGES]}
    run.save()
    rng = np.random.default_rng(seed)
    out_dir = artifacts_root() / 'runs' / f'run_{run.pk}'
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Datasets ------------------------------------------------------------------
        reporter.stage('download')
        dataset_info = []
        if fleet_frames is None or ai4i is None or engines is None:
            paths = {}
            for index, dataset in enumerate(datasets.DATASETS):
                def report(done, total, name, index=index):
                    share = (done / total) if total else 0.0
                    reporter.within((index + share) / len(datasets.DATASETS),
                                    f'Downloading {name}: {done / 1e6:.1f} MB' + (f' of {total / 1e6:.1f} MB' if total else ''))
                reporter.log(f'Fetching {dataset.title} ({len(dataset.files)} file(s))')
                paths[dataset.key] = datasets.download(dataset, report)
            reporter.log('Reading dataset files')
            telemetry, errors, failures = datasets.load_azure(paths['azure_pdm'])
            engines = datasets.load_cmapss(paths['nasa_cmapss'])
            ai4i = datasets.load_ai4i(paths['ai4i_2020'])
        else:
            telemetry, errors, failures = fleet_frames
        stats = {
            'azure_pdm': {'rows': int(len(telemetry)), 'machines': int(telemetry['machineID'].nunique()), 'failures': int(len(failures))},
            'nasa_cmapss': {'rows': int(len(engines)), 'machines': int(engines['unit'].nunique()), 'failures': int(engines['unit'].nunique())},
            'ai4i_2020': {'rows': int(len(ai4i)), 'failures': int(ai4i['Machine failure'].sum())},
        }
        for dataset in datasets.DATASETS:
            dataset_info.append({'key': dataset.key, 'title': dataset.title, 'source': dataset.source, 'used_for': dataset.used_for,
                                 'size_mb': round(datasets.cached_size(dataset) / 1e6, 1), **stats[dataset.key]})
        reporter.metric('datasets', dataset_info)
        reporter.log(f'Azure: {len(telemetry):,} hourly rows, {telemetry["machineID"].nunique()} machines, {len(failures)} failures; '
                     f'C-MAPSS: {engines["unit"].nunique()} run-to-failure engines ({len(engines):,} cycles); AI4I: {len(ai4i):,} operating points')

        # 2. Features -------------------------------------------------------------------
        reporter.stage('features')
        fleet = build_fleet_frame(telemetry, errors, failures, _SubReporter(reporter, 0.0, 0.7))
        degradation = build_degradation_frame(engines, rng, _SubReporter(reporter, 0.7, 1.0))
        frame = pd.concat([fleet, degradation], ignore_index=True)
        silent = (frame['source'] == 'azure') & (frame['days_to_failure'] > AZURE_SIGNAL_DAYS)
        frame['use_risk'] = ~(silent & (frame['days_to_failure'] <= HORIZON_DAYS)) & frame['fail_7d'].notna()
        frame['use_days'] = ~(silent & (frame['days_to_failure'] <= DAYS_CAP)) & frame['days_target'].notna()
        splitter = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=seed)
        train_idx, val_idx = next(splitter.split(frame, groups=frame['machine'].values))
        train, val = frame.iloc[train_idx], frame.iloc[val_idx]
        train_aug = pd.concat([train, mask_channels(train, rng, MODEL_FEATURES)], ignore_index=True)
        reporter.log(f'{len(frame):,} snapshots ({len(fleet):,} fleet, {len(degradation):,} degradation); '
                     f'validation uses {val["machine"].nunique()} machines/engines never seen in training')
        reporter.metric('samples', {'snapshots': int(len(frame)), 'fleet': int(len(fleet)), 'degradation': int(len(degradation)),
                                    'train': int(len(train_aug)), 'validation': int(len(val)),
                                    'positives': int(frame.loc[frame['use_risk'], 'fail_7d'].sum())})

        # 3. Failure risk (classifier) ----------------------------------------------------
        reporter.stage('risk')
        tr = train_aug[train_aug['use_risk']]
        va = val[val['use_risk']]
        risk_params = {
            'objective': 'binary:logistic', 'eval_metric': ['logloss', 'auc'], 'tree_method': 'hist',
            'max_depth': 6, 'eta': 0.05, 'subsample': 0.8, 'colsample_bytree': 0.8, 'min_child_weight': 10,
            'seed': seed, 'nthread': 0,
        }
        d_tr = xgb.DMatrix(tr[MODEL_FEATURES], label=tr['fail_7d'], feature_names=MODEL_FEATURES, missing=np.nan)
        d_va = xgb.DMatrix(va[MODEL_FEATURES], label=va['fail_7d'], feature_names=MODEL_FEATURES, missing=np.nan)
        risk = _train(risk_params, d_tr, d_va, rounds[0], reporter, 'risk')
        p_va = risk.predict(d_va, iteration_range=(0, risk.best_iteration + 1))
        y_va = va['fail_7d'].values
        thresholds = np.linspace(0.02, 0.98, 97)
        f1s = np.array([f1_score(y_va, p_va >= th, zero_division=0) for th in thresholds])
        precisions = np.array([precision_score(y_va, p_va >= th, zero_division=0) for th in thresholds])
        # Alert levels chosen on machines the model has never seen:
        # medium = catches at least half of the failures a week ahead; high = at least half of the alerts are real.
        recalls = np.array([recall_score(y_va, p_va >= th, zero_division=0) for th in thresholds])
        sensitive = thresholds[recalls >= 0.5]
        medium_th = float(sensitive[-1]) if len(sensitive) else float(thresholds[int(np.argmax(f1s))])
        confident = thresholds[(precisions >= 0.5) & (thresholds > medium_th)]
        high_th = float(confident[0]) if len(confident) else float(max(medium_th + 0.05, np.quantile(p_va, 0.97)))
        # For maintenance planning an alert is useful if the machine fails within two weeks.
        fail_14d = (va['days_to_failure'] <= 14).values
        precision_14d = lambda th: round(float(fail_14d[p_va >= th].mean()), 4) if (p_va >= th).any() else None
        va_masked = mask_channels(va, rng, MODEL_FEATURES)
        p_masked = risk.predict(xgb.DMatrix(va_masked[MODEL_FEATURES], feature_names=MODEL_FEATURES, missing=np.nan),
                                iteration_range=(0, risk.best_iteration + 1))
        by_source = {}
        for source in ('azure', 'cmapss'):
            sel = (va['source'] == source).values
            if sel.any() and len(np.unique(y_va[sel])) == 2:
                by_source[source] = round(float(roc_auc_score(y_va[sel], p_va[sel])), 4)
        risk_metrics = {
            'roc_auc': round(float(roc_auc_score(y_va, p_va)), 4),
            'pr_auc': round(float(average_precision_score(y_va, p_va)), 4),
            'threshold': round(medium_th, 2),
            'high_threshold': round(high_th, 2),
            'precision': round(float(precision_score(y_va, p_va >= medium_th, zero_division=0)), 4),
            'recall': round(float(recall_score(y_va, p_va >= medium_th, zero_division=0)), 4),
            'f1': round(float(f1s.max()), 4),
            'precision_high': round(float(precision_score(y_va, p_va >= high_th, zero_division=0)), 4),
            'precision_14d': precision_14d(medium_th),
            'precision_high_14d': precision_14d(high_th),
            'recall_high': round(float(recall_score(y_va, p_va >= high_th, zero_division=0)), 4),
            'roc_auc_by_source': by_source,
            'roc_auc_partial_signals': round(float(roc_auc_score(y_va, p_masked)), 4),
            'best_iteration': int(risk.best_iteration + 1),
            'positive_rate': round(float(y_va.mean()), 4),
        }
        reporter.metric('risk', risk_metrics)
        reporter.log(f"Failure-risk model: ROC-AUC {risk_metrics['roc_auc']} (imminent fleet failures {by_source.get('azure')}, "
                     f"gradual wear {by_source.get('cmapss')}); medium alert catches {risk_metrics['recall']:.0%} of failures a week ahead "
                     f"({(risk_metrics['precision_14d'] or 0):.0%} of its alerts fail within 14 days), high alert {risk_metrics['recall_high']:.0%} "
                     f"({(risk_metrics['precision_high_14d'] or 0):.0%} within 14 days); "
                     f"with some sensors missing ROC-AUC {risk_metrics['roc_auc_partial_signals']}")

        # 4. Days to maintenance (regressor) ---------------------------------------------
        reporter.stage('days')
        # Learn the countdown only from machines that really were on their way to a failure.
        tr = train_aug[train_aug['use_days'] & (train_aug['days_to_failure'] <= DAYS_CAP)]
        va_all = val[val['use_days']]
        va = va_all[va_all['days_to_failure'] <= DAYS_CAP]
        days_params = {
            'objective': 'reg:absoluteerror', 'eval_metric': ['mae'], 'tree_method': 'hist',
            'max_depth': 6, 'eta': 0.05, 'subsample': 0.8, 'colsample_bytree': 0.8, 'min_child_weight': 10,
            'seed': seed, 'nthread': 0,
        }
        d_tr = xgb.DMatrix(tr[MODEL_FEATURES], label=tr['days_to_failure'], feature_names=MODEL_FEATURES, missing=np.nan)
        d_va = xgb.DMatrix(va[MODEL_FEATURES], label=va['days_to_failure'], feature_names=MODEL_FEATURES, missing=np.nan)
        days = _train(days_params, d_tr, d_va, rounds[1], reporter, 'days')
        days_iterations = (0, days.best_iteration + 1)
        risk_iterations = (0, risk.best_iteration + 1)
        show_th = float(medium_th)

        actual = va['days_to_failure'].values
        est = np.clip(days.predict(d_va, iteration_range=days_iterations), 0, DAYS_CAP)
        p_fail = risk.predict(xgb.DMatrix(va[MODEL_FEATURES], feature_names=MODEL_FEATURES, missing=np.nan), iteration_range=risk_iterations)
        detected = p_fail >= show_th
        wear = (va['source'] == 'cmapss').values
        # Two-stage estimate over every validation row, as shown on the page.
        d_all = xgb.DMatrix(va_all[MODEL_FEATURES], feature_names=MODEL_FEATURES, missing=np.nan)
        shown = np.where(risk.predict(d_all, iteration_range=risk_iterations) >= show_th,
                         np.clip(days.predict(d_all, iteration_range=days_iterations), 0, DAYS_CAP), DAYS_CAP)
        target_all = va_all['days_target'].values
        calibration = []
        for lo in range(0, DAYS_CAP, 3):
            sel = wear & (actual >= lo) & (actual < lo + 3)
            if sel.sum() >= 5:
                calibration.append({'actual': lo + 1.5, 'predicted': round(float(est[sel].mean()), 2),
                                    'p10': round(float(np.quantile(est[sel], 0.1)), 2),
                                    'p90': round(float(np.quantile(est[sel], 0.9)), 2)})
        mae = lambda a, b: round(float(mean_absolute_error(a, b)), 2) if len(a) else None
        days_metrics = {
            'mae_days_failing': mae(actual, est),
            'mae_days_detected': mae(actual[detected], est[detected]),
            'detected_share': round(float(detected.mean()), 4) if len(detected) else None,
            'mae_days_gradual_wear': mae(actual[wear], est[wear]),
            'mae_days_all': mae(target_all, shown),
            'baseline_mae_days': mae(actual, np.full(len(actual), np.median(tr['days_to_failure']))),
            'mae_days': mae(actual[detected], est[detected]),
            'show_threshold': round(show_th, 3),
            'cap_days': DAYS_CAP,
            'calibration': calibration,
            'best_iteration': int(days.best_iteration + 1),
        }
        reporter.metric('days', days_metrics)
        reporter.log(f"Days-to-maintenance model: when wear is detected ({days_metrics['detected_share']:.0%} of failing snapshots) "
                     f"the estimate is off by {days_metrics['mae_days_detected']} days on average "
                     f"(all failing machines {days_metrics['mae_days_failing']}, naive guess {days_metrics['baseline_mae_days']}); "
                     f"gradual wear {days_metrics['mae_days_gradual_wear']} days")

        # 5. Failure type (multi-class) -------------------------------------------------
        reporter.stage('mode')
        mode_frame = build_mode_frame(ai4i)
        y = mode_frame['label'].map({c: i for i, c in enumerate(MODE_CLASSES)}).values
        m_train, m_val, y_train, y_val = train_test_split(mode_frame[MODE_FEATURES], y, test_size=0.2,
                                                          random_state=seed, stratify=y)
        m_train_aug = pd.concat([m_train, mask_channels(m_train, rng, MODE_FEATURES, p_drop=0.25)], ignore_index=True)
        y_train_aug = np.concatenate([y_train, y_train])
        counts = np.bincount(y_train_aug, minlength=len(MODE_CLASSES)).astype(float)
        weights = (len(y_train_aug) / (len(MODE_CLASSES) * np.maximum(counts, 1)))[y_train_aug]
        mode_params = {
            'objective': 'multi:softprob', 'num_class': len(MODE_CLASSES), 'eval_metric': ['merror', 'mlogloss'],
            'tree_method': 'hist', 'max_depth': 5, 'eta': 0.08, 'subsample': 0.9, 'colsample_bytree': 1.0,
            'min_child_weight': 2, 'seed': seed, 'nthread': 0,
        }
        d_tr = xgb.DMatrix(m_train_aug, label=y_train_aug, weight=weights, feature_names=MODE_FEATURES, missing=np.nan)
        d_va = xgb.DMatrix(m_val, label=y_val, feature_names=MODE_FEATURES, missing=np.nan)
        mode = _train(mode_params, d_tr, d_va, rounds[2], reporter, 'mode')
        pred_mode = mode.predict(d_va, iteration_range=(0, mode.best_iteration + 1)).argmax(axis=1)
        mode_metrics = {
            'accuracy': round(float(accuracy_score(y_val, pred_mode)), 4),
            'macro_f1': round(float(f1_score(y_val, pred_mode, average='macro', zero_division=0)), 4),
            'recall_per_class': {MODE_CLASSES[i]: round(float(r), 4) for i, r in
                                 enumerate(recall_score(y_val, pred_mode, average=None, labels=range(len(MODE_CLASSES)), zero_division=0))},
            'confusion_matrix': confusion_matrix(y_val, pred_mode, labels=range(len(MODE_CLASSES))).tolist(),
            'classes': MODE_CLASSES,
            'best_iteration': int(mode.best_iteration + 1),
        }
        reporter.metric('mode', mode_metrics)
        reporter.log(f"Failure-type model: accuracy {mode_metrics['accuracy']}, macro F1 {mode_metrics['macro_f1']}")

        # 6. Save --------------------------------------------------------------------------
        reporter.stage('save')
        risk.save_model(out_dir / 'risk.json')
        days.save_model(out_dir / 'days.json')
        mode.save_model(out_dir / 'mode.json')
        channel_gain, top_features = channel_importance(risk, MODEL_FEATURES)
        reporter.metric('importance', {'channels': channel_gain, 'top_features': top_features})
        meta = {
            'features': MODEL_FEATURES, 'mode_features': MODE_FEATURES, 'mode_classes': MODE_CLASSES,
            'risk_threshold': risk_metrics['threshold'], 'risk_high_threshold': risk_metrics['high_threshold'],
            'horizon_days': HORIZON_DAYS, 'days_cap': DAYS_CAP, 'days_min_probability': days_metrics['show_threshold'],
            'mode_requires': MODE_REQUIRES,
            'risk_iterations': risk_metrics['best_iteration'], 'days_iterations': days_metrics['best_iteration'],
            'mode_iterations': mode_metrics['best_iteration'], 'xgboost_version': xgb.__version__,
            'trained_at': timezone.now().isoformat(),
        }
        (out_dir / 'meta.json').write_text(json.dumps(meta, indent=2))
        run.artifact_dir = str(out_dir)
        run.save(update_fields=['artifact_dir'])
        reporter.log(f'Models saved to {out_dir}')

        # 7. Score plant devices ------------------------------------------------------------
        reporter.stage('score')
        if score:
            from .scoring import score_devices
            results = score_devices(run=run, reporter=reporter)
            summary = {status: sum(1 for r in results if r.status == status) for status in {r.status for r in results}}
            reporter.metric('scored', {'devices': len(results), 'by_status': summary,
                                       'high_risk': sum(1 for r in results if r.risk == 'high')})
            reporter.log(f'Scored {len(results)} plant devices: {summary}')

        run.status = TrainingRun.COMPLETED
        run.progress = 100
        run.stage = 'Completed'
        run.message = 'Training finished'
        run.finished_at = timezone.now()
        reporter.log('✔ Training completed')
        run.save()
    except Exception as exc:
        run.status = TrainingRun.FAILED
        run.error = traceback.format_exc()
        run.message = str(exc)[:500]
        run.finished_at = timezone.now()
        reporter.log(f'✖ Training failed: {exc}')
        run.save()
        raise
    return run
