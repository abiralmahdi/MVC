"""Device-independent features for predictive maintenance.

Every machine - a motor in the training data or a meter/motor in the plant -
is reduced to up to four *signal channels*:

    electrical  voltage / current drawn        (training: voltage)
    load        speed / flow / throughput     (training: rotation speed)
    process     temperature / pressure / level (training: pressure)
    stress      vibration / distortion / dust  (training: vibration)

Values are compared with the machine's **own** healthy baseline, so the
features have no units and a model trained on one fleet can score another:

    <ch>_z24    deviation of the last 24 h mean from the baseline (in baseline std units)
    <ch>_z3     same for the last 3 h (short spikes)
    <ch>_vol24  variability of the last 24 h relative to the baseline variability
    <ch>_slope7 trend over the last 7 days (baseline std units per day)
    alarms_24h, alarms_7d  number of alarm/error events

The baseline is the window 30 to 7 days before the scoring time, so a slow
drift over the last week is measured against how the machine behaved before.
Exactly the same function is used for training and for scoring plant devices.
"""
import numpy as np
import pandas as pd

CHANNELS = ['electrical', 'load', 'process', 'stress']
CHANNEL_LABELS = {
    'electrical': 'Electrical (voltage / current)',
    'load': 'Load (speed / flow)',
    'process': 'Process (temperature / pressure)',
    'stress': 'Stress (vibration / distortion)',
}
CHANNEL_FEATURES = ['z24', 'z3', 'vol24', 'slope7']
FEATURES = [f'{c}_{f}' for c in CHANNELS for f in CHANNEL_FEATURES] + ['alarms_24h', 'alarms_7d']

BASELINE_HOURS = 30 * 24
RECENT_GAP_HOURS = 7 * 24
MIN_BASELINE_SAMPLES = 72


def _rolling_slope_per_day(series, window=168, min_periods=48):
    """Least-squares slope over a trailing window of hourly values, in units per day (NaN-tolerant)."""
    t = pd.Series(np.arange(len(series), dtype=float) / 24.0, index=series.index)
    mask = series.notna()
    y = series.where(mask)
    tt = t.where(mask)
    r = lambda s: s.rolling(window, min_periods=min_periods)
    mean_t, mean_y = r(tt).mean(), r(y).mean()
    mean_ty, mean_tt = r(tt * y).mean(), r(tt * tt).mean()
    var_t = mean_tt - mean_t ** 2
    return (mean_ty - mean_t * mean_y) / var_t.where(var_t > 1e-9)


def channel_features(hourly, alarms=None):
    """Feature rows for every hour of ``hourly``.

    hourly: DataFrame indexed by a regular hourly DatetimeIndex, columns = a subset of CHANNELS.
    alarms: optional Series (same index) with the number of alarm events in each hour.
    """
    out = pd.DataFrame(index=hourly.index)
    for channel in CHANNELS:
        if channel not in hourly:
            for suffix in CHANNEL_FEATURES:
                out[f'{channel}_{suffix}'] = np.nan
            continue
        s = hourly[channel].astype(float)
        base_window = BASELINE_HOURS - RECENT_GAP_HOURS
        base_mean = s.rolling(base_window, min_periods=MIN_BASELINE_SAMPLES).mean().shift(RECENT_GAP_HOURS)
        base_std = s.rolling(base_window, min_periods=MIN_BASELINE_SAMPLES).std().shift(RECENT_GAP_HOURS)
        # A perfectly flat baseline would divide by zero: use 1% of the level as the minimum spread.
        base_std = base_std.where(base_std > 1e-9 + 0.01 * base_mean.abs(), 0.01 * base_mean.abs() + 1e-6)
        out[f'{channel}_z24'] = (s.rolling(24, min_periods=6).mean() - base_mean) / base_std
        out[f'{channel}_z3'] = (s.rolling(3, min_periods=1).mean() - base_mean) / base_std
        out[f'{channel}_vol24'] = s.rolling(24, min_periods=6).std() / base_std
        out[f'{channel}_slope7'] = _rolling_slope_per_day(s) / base_std
    if alarms is None:
        out['alarms_24h'] = np.nan
        out['alarms_7d'] = np.nan
    else:
        a = alarms.reindex(hourly.index).fillna(0).astype(float)
        out['alarms_24h'] = a.rolling(24, min_periods=1).sum()
        out['alarms_7d'] = a.rolling(168, min_periods=1).sum()
    return out[FEATURES].replace([np.inf, -np.inf], np.nan)


def to_hourly(rows, mapping, end=None, hours=31 * 24):
    """Hourly channel frame from (timestamp, data dict) rows.

    mapping: {channel: measurement name}. Rows are averaged per hour; missing hours stay NaN.
    """
    end = pd.Timestamp.now(tz='UTC') if end is None else pd.Timestamp(end)
    end = end.tz_localize('UTC') if end.tzinfo is None else end.tz_convert('UTC')
    index = pd.date_range(end=end.floor('h'), periods=hours, freq='h')
    columns = list(mapping)
    records = []
    for timestamp, data in rows:
        if not isinstance(data, dict):
            continue
        record = {'timestamp': timestamp}
        for channel, name in mapping.items():
            value = data.get(name)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and np.isfinite(value):
                record[channel] = float(value)
        records.append(record)
    if not records:
        return pd.DataFrame(np.nan, index=index, columns=columns)
    df = pd.DataFrame.from_records(records)
    df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True).dt.floor('h')
    grouped = df.groupby('timestamp').mean(numeric_only=True)
    return grouped.reindex(index=index, columns=columns).astype(float)


def hourly_alarm_counts(timestamps, index):
    """Series with the number of alarm timestamps falling in each hour of ``index``."""
    if not len(timestamps):
        return pd.Series(0.0, index=index)
    ts = pd.to_datetime(pd.Series(list(timestamps)), utc=True).dt.floor('h')
    return ts.value_counts().reindex(index).fillna(0.0)
