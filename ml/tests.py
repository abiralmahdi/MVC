import shutil
import tempfile
from datetime import timedelta
from unittest import mock

import numpy as np
import pandas as pd
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import UserModel
from dashboard.models import MeterReading
from dynamic.models import Areas, Buildings, Measurements, Meters, Site
from scada.models import Motor

from .demo import DEMO_FIELDS, generate_motor_telemetry
from .devices import all_devices, map_channels
from .features import FEATURES, channel_features, to_hourly
from .models import DeviceHealth, TrainingRun
from .scoring import score_devices
from .training import train_models


def synthetic_fleet(machines=6, days=75, seed=1):
    """Azure-like telemetry where vibration drifts upwards in the week before each failure."""
    rng = np.random.default_rng(seed)
    index = pd.date_range('2015-01-01 06:00', periods=days * 24, freq='h')
    telemetry, failures, errors = [], [], []
    for m in range(1, machines + 1):
        vib = rng.normal(40, 4, len(index))
        volt = rng.normal(170, 12, len(index))
        for fail_day in (40, 62):
            fail_at = index[0] + pd.Timedelta(days=fail_day)
            failures.append({'datetime': fail_at, 'machineID': m, 'failure': 'comp4'})
            ramp = (index > fail_at - pd.Timedelta(days=6)) & (index <= fail_at)
            vib[ramp] += np.linspace(0, 25, ramp.sum())
            errors.append({'datetime': fail_at - pd.Timedelta(days=1), 'machineID': m, 'errorID': 'error1'})
        telemetry.append(pd.DataFrame({'datetime': index, 'machineID': m, 'volt': volt, 'rotate': rng.normal(450, 40, len(index)),
                                       'pressure': rng.normal(100, 9, len(index)), 'vibration': vib}))
    return pd.concat(telemetry), pd.DataFrame(errors), pd.DataFrame(failures)


def synthetic_engines(units=12, seed=4):
    """C-MAPSS-like run-to-failure engines: sensors drift upwards over the last 40 cycles."""
    rng = np.random.default_rng(seed)
    frames = []
    for unit in range(1, units + 1):
        n = int(rng.integers(90, 140))
        wear = np.clip((np.arange(n) - (n - 40)) / 40, 0, None) ** 2
        frames.append(pd.DataFrame({
            'unit': unit, 'cycle': np.arange(1, n + 1),
            's4': 1400 + 25 * wear + rng.normal(0, 3, n), 's9': 9050 + 30 * wear + rng.normal(0, 4, n),
            's11': 47.4 + 0.8 * wear + rng.normal(0, 0.1, n), 's12': 521.7 - 2 * wear + rng.normal(0, 0.3, n),
        }))
    return pd.concat(frames, ignore_index=True)


def synthetic_ai4i(rows=1500, seed=2):
    rng = np.random.default_rng(seed)
    air = rng.normal(300, 2, rows)
    proc = air + rng.normal(10, 1, rows)
    rpm = rng.normal(1540, 170, rows)
    torque = rng.normal(40, 10, rows)
    hdf = ((proc - air) < 8.6) & (rpm < 1380)
    pwf = (torque * rpm * 2 * np.pi / 60 < 3500) | (torque * rpm * 2 * np.pi / 60 > 9000)
    osf = torque > 62
    return pd.DataFrame({
        'Air temperature [K]': air, 'Process temperature [K]': proc, 'Rotational speed [rpm]': rpm,
        'Torque [Nm]': torque, 'Tool wear [min]': rng.integers(0, 250, rows),
        'Machine failure': (hdf | pwf | osf).astype(int), 'TWF': 0, 'HDF': hdf.astype(int),
        'PWF': pwf.astype(int), 'OSF': osf.astype(int), 'RNF': 0,
    })


class FeatureTests(TestCase):
    def test_rising_signal_gives_positive_deviation_and_trend(self):
        index = pd.date_range('2026-01-01', periods=31 * 24, freq='h', tz='UTC')
        values = np.r_[np.random.default_rng(0).normal(10, 0.5, 24 * 24), np.linspace(10, 16, 7 * 24)]
        feats = channel_features(pd.DataFrame({'stress': values}, index=index))
        last = feats.iloc[-1]
        self.assertGreater(last['stress_z24'], 3)
        self.assertGreater(last['stress_slope7'], 0)
        self.assertTrue(np.isnan(last['electrical_z24']))
        self.assertEqual(list(feats.columns), FEATURES)

    def test_short_history_has_no_baseline(self):
        now = timezone.now()
        rows = [(now - timedelta(hours=h), {'Temperature': 20 + h * 0.1}) for h in range(48)]
        hourly = to_hourly(rows, {'process': 'Temperature'}, end=now)
        self.assertTrue(np.isnan(channel_features(hourly).iloc[-1]['process_z24']))


class DeviceMappingTests(TestCase):
    def test_every_device_type_maps_to_channels(self):
        electric = ['Voltage L1N', '3-Phase Average Voltage L-N', '3-Phase Average Current L-L', 'Power Factor',
                    'THD Voltage L1-L2', 'Energy', 'Total Active Power', 'Line Frequency']
        self.assertEqual(map_channels(electric), {'electrical': '3-Phase Average Voltage L-N', 'load': '3-Phase Average Current L-L',
                                                  'process': 'Power Factor', 'stress': 'THD Voltage L1-L2'})
        self.assertEqual(map_channels(list(DEMO_FIELDS)), {'electrical': 'Motor current (A)', 'load': 'Speed (rpm)',
                                                           'process': 'Winding temperature (°C)', 'stress': 'Vibration (mm/s)'})
        self.assertEqual(map_channels(['Flow Rate', 'Total Volume']), {'load': 'Flow Rate'})
        self.assertEqual(map_channels(['CO2 Level', 'PM2.5', 'PM10']), {'process': 'CO2 Level', 'stress': 'PM2.5'})
        self.assertEqual(map_channels(['Air Temperature (°F)', 'Temperature Setpoint (°F)']), {'process': 'Air Temperature (°F)'})


class PipelineTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.override = override_settings(ML_ARTIFACTS_DIR=self.tmp)
        self.override.enable()
        site = Site.objects.create(name='S', latitude='0', longitude='0')
        building = Buildings.objects.create(name='B', site=site)
        area = Areas.objects.create(name='A', building=building)
        self.meter = Meters.objects.create(name='Pump feeder', area=area, meterType='Electricity Meter')
        for name in ('3-Phase Average Voltage L-N', '3-Phase Average Current L-L'):
            Measurements.objects.create(name=name, meter=self.meter)
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        rng = np.random.default_rng(3)
        MeterReading.objects.bulk_create([
            MeterReading(meter=self.meter, timestamp=now - timedelta(hours=h),
                         data={'3-Phase Average Voltage L-N': float(rng.normal(230, 1)), '3-Phase Average Current L-L': float(rng.normal(100, 3))})
            for h in range(20 * 24)
        ])
        self.motors = [Motor.objects.create(motorName=f'M{i}', building=building, fields=DEMO_FIELDS) for i in range(3)]
        generate_motor_telemetry(self.motors, days=20, degrading=self.motors[1], warming=self.motors[2])
        Meters.objects.create(name='Empty', area=area, meterType='Water Meter')   # no measurements at all

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_training_run_completes_and_scores_every_device(self):
        telemetry, errors, failures = synthetic_fleet()
        run = TrainingRun.objects.create()
        train_models(run, fleet_frames=(telemetry, errors, failures), engines=synthetic_engines(), ai4i=synthetic_ai4i(),
                     rounds=(40, 40, 30))
        run.refresh_from_db()
        self.assertEqual(run.status, TrainingRun.COMPLETED)
        self.assertEqual(run.progress, 100)
        for key in ('risk', 'days', 'mode', 'curves', 'importance', 'scored'):
            self.assertIn(key, run.metrics)
        self.assertGreater(run.metrics['risk']['roc_auc'], 0.7)
        self.assertIn('calibration', run.metrics['days'])
        self.assertEqual({d['key'] for d in run.metrics['datasets']}, {'azure_pdm', 'nasa_cmapss', 'ai4i_2020'})
        self.assertEqual(DeviceHealth.objects.count(), len(all_devices()))
        degrading = DeviceHealth.objects.get(motor=self.motors[1])
        healthy = DeviceHealth.objects.get(motor=self.motors[0])
        self.assertEqual(degrading.status, DeviceHealth.OK)
        self.assertEqual(set(degrading.channels), {'electrical', 'load', 'process', 'stress'})
        self.assertGreater(degrading.failure_probability, healthy.failure_probability)
        self.assertEqual(DeviceHealth.objects.get(meter=self.meter).status, DeviceHealth.OK)
        self.assertEqual(DeviceHealth.objects.get(meter__name='Empty').status, DeviceHealth.NO_SIGNALS)

        # Re-scoring uses the saved model files.
        results = score_devices()
        self.assertEqual(len(results), len(all_devices()))

    def test_failed_run_is_marked_failed(self):
        run = TrainingRun.objects.create()
        with self.assertRaises(Exception):
            train_models(run, fleet_frames=(pd.DataFrame(), pd.DataFrame(), pd.DataFrame()), engines=synthetic_engines(), ai4i=synthetic_ai4i())
        run.refresh_from_db()
        self.assertEqual(run.status, TrainingRun.FAILED)
        self.assertTrue(run.error)


class PageAccessTests(TestCase):
    def setUp(self):
        self.root = User.objects.create_superuser('root', 'root@example.com', 'VeryStrong#Pass1')
        self.admin = User.objects.create_user('boss', 'boss@example.com', 'VeryStrong#Pass1')
        UserModel.objects.create(user=self.admin, name='Boss', email='boss@example.com', role='Administrator')

    def test_only_superusers_can_open_the_page(self):
        self.assertEqual(self.client.get('/ml/').status_code, 302)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/ml/').status_code, 403)
        self.assertEqual(self.client.post('/ml/train').status_code, 403)
        self.client.force_login(self.root)
        response = self.client.get('/ml/')
        self.assertContains(response, 'Machine Learning')
        self.assertContains(response, 'Devices &amp; motors')
        # The clean page no longer shows the training/model detail sections.
        self.assertNotContains(response, 'Training datasets')
        self.assertNotContains(response, 'Training history')

    def test_details_page_has_the_full_view(self):
        self.client.force_login(self.root)
        response = self.client.get('/ml-details')
        self.assertContains(response, 'Devices &amp; motors')
        self.assertContains(response, 'Training datasets')
        self.assertContains(response, 'Training history')

    def test_details_page_is_superuser_only(self):
        self.assertEqual(self.client.get('/ml-details').status_code, 302)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/ml-details').status_code, 403)

    def test_start_training_launches_background_process_and_reports_status(self):
        self.client.force_login(self.root)
        with mock.patch('ml.views.launch_training', return_value=1234) as launch:
            self.client.post('/ml/train')
            self.client.post('/ml/train')   # second click while running must not start another run
        self.assertEqual(launch.call_count, 1)
        run = TrainingRun.objects.get()
        payload = self.client.get(f'/ml/status/{run.pk}', HTTP_ACCEPT='application/json').json()['run']
        self.assertEqual(payload['status'], 'queued')

    def test_stale_run_is_marked_failed(self):
        run = TrainingRun.objects.create(status=TrainingRun.RUNNING)
        TrainingRun.objects.filter(pk=run.pk).update(updated_at=timezone.now() - timedelta(hours=1))
        self.client.force_login(self.root)
        self.client.get('/ml/')
        run.refresh_from_db()
        self.assertEqual(run.status, TrainingRun.FAILED)
