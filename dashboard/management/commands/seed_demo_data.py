"""Wipe the database and load a compact but realistic demo data set.

What gets created (see ``dashboard/demo_plant.py`` for the plant layout):

* 3 sites (Gazipur textile mill, Chattogram plant, Dhaka corporate campus), 10 buildings, 23 areas and
  about 50 meters of every meter type (electricity, water, gas, steam, fuel, temperature, pressure,
  humidity, air quality, transmitter) on every field protocol (Modbus TCP, BACnet/IP, KNX, DALI/DALI-2,
  M-Bus, MQTT, OPC UA), with data points, measurements and units.
* Simulated devices sit on documentation addresses (192.0.2.x, 198.51.100.x, 203.0.113.x), so the poller
  can never reach real equipment; their readings are generated here: hourly since the first day of last
  month, every 15 minutes for the last 48 hours, plus daily-folded history from 1 January of last year
  stored only as weekly/monthly/3monthly/6monthly/yearly and hierarchy aggregates.
* Meters in the *Remote Test Rig* building read live values from public online simulators (OPC UA demo
  servers and the public MQTT test broker); they have no generated history, the poller fills them.
* Alarm limits, alarms derived from injected excursions (old ones acknowledged, recent ones active),
  users for every role, login history, dashboards that use every gadget type, reports, bills, SCADA
  motors and tanks, protocol gateways and CSV files.
"""
import csv
import io
import math
import random
import secrets
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from accounts.models import LoginHistory, UserModel
from alarms.models import Alarms, AlarmsRange
from billing.calculations import calculate_bill
from connections.models import SystemJob
from dashboard.aggregation import (
    RAW_PERIODS, derive_long_periods, fold_readings, rollup, run_hierarchy_aggregation,
)
from dashboard.measurements import MEASUREMENT_UNITS, METER_DEFINITIONS
from dashboard.models import (
    Dashboard, Files, Gadgets, HierarchyDataAggregate, LatestMeterReading, MeterReading, MeterReadingAggregate,
)
from dynamic.models import Areas, Buildings, LoadType, Masters, Measurements, Meters, Site, Units
from dashboard.demo_plant import (
    GATEWAYS, LIVE_BUILDING, LIVE_METERS, LIVE_SITE, LOAD_TYPES, PLC_HOST, SITES, build_device, fields_for,
)
from home.models import GlobalConfiguration
from report.models import Billing, ReportDiagram, ReportFormat
from scada.models import Motor, MotorMasters, Tank
from utils.access import ROLES

JOB_NAME = "daily_time_and_hierarchy_aggregation"

FIELDS_BY_TYPE = {kind: fields for kind, fields in METER_DEFINITIONS.items()}

# Monthly PM2.5 baseline for Bangladesh (dry-season smog, clean monsoon air).
PM25_BY_MONTH = {1: 120, 2: 95, 3: 70, 4: 55, 5: 45, 6: 30, 7: 25, 8: 27, 9: 32, 10: 50, 11: 85, 12: 115}
# Share of HVAC load in use by month.
HVAC_BY_MONTH = {1: 0.35, 2: 0.45, 3: 0.75, 4: 0.95, 5: 1.0, 6: 0.95, 7: 0.9, 8: 0.9, 9: 0.9, 10: 0.75, 11: 0.5, 12: 0.35}


def _days(first, last):
    return {first + timedelta(days=i) for i in range((last - first).days + 1)}


# National holidays and Eid shutdowns (factories close for about a week).
HOLIDAYS = {
    date(2025, 2, 21), date(2025, 3, 26), date(2025, 12, 16),
    date(2026, 2, 21), date(2026, 3, 26), date(2026, 12, 16),
    *_days(date(2025, 3, 29), date(2025, 4, 5)), *_days(date(2025, 6, 5), date(2025, 6, 14)),
    *_days(date(2026, 3, 18), date(2026, 3, 25)), *_days(date(2026, 5, 25), date(2026, 6, 1)),
}


def clip(value, low, high):
    return max(low, min(high, value))


class MeterSimulator:
    """Produces physically consistent readings for one meter, advancing its counters."""

    def __init__(self, spec, seed, history_start):
        self.spec = spec
        self.kind = spec['type']
        self.rng = random.Random(seed)
        self.history_start = history_start
        self.events = []  # (start, end, mode)
        self.counters = {
            'Energy': self.rng.uniform(150_000, 900_000),
            'Total Reactive Power': self.rng.uniform(40_000, 250_000),
            'Total Volume': self.rng.uniform(20_000, 90_000),
            'Total Gas Volume': self.rng.uniform(300_000, 900_000),
            'Total Steam': self.rng.uniform(3_000_000, 9_000_000),
            'Total Fuel Used': self.rng.uniform(5_000, 25_000),
        }
        self.counters['Total Apparent Power'] = self.counters['Energy'] * 1.05
        self._outage_day = None
        self._outage = None
        self._pm_day = None
        self._pm_factor = 1.0

    # -- load shapes -------------------------------------------------------
    def _growth(self, t):
        return 1 + 0.06 * (t.year - self.history_start.year)

    @staticmethod
    def occupied(t):
        """Office occupancy 0..1 (Bangladesh weekend: Friday and Saturday)."""
        hour = t.hour + t.minute / 60
        if t.date() in HOLIDAYS or t.weekday() in (4, 5):
            return 0.05
        if 9 <= hour < 18:
            return 0.65 if 13 <= hour < 14 else 1.0
        if 8 <= hour < 9 or 18 <= hour < 19.5:
            return 0.45
        return 0.03

    def load(self, t):
        profile = self.spec.get('profile', 'production')
        day, hour = t.date(), t.hour + t.minute / 60
        if profile == 'lighting':
            return 0.25 + 0.7 * self.occupied(t) if 6 <= hour < 21 else 0.18
        if profile == 'chiller':
            base = 0.9 if 8 <= hour < 20 else 0.5
            return base * (0.25 + 0.75 * HVAC_BY_MONTH[t.month]) * (0.6 if day in HOLIDAYS else 1.0)
        if profile == 'flat':
            return 0.8 + 0.03 * math.sin(2 * math.pi * hour / 24)
        if profile == 'solar':
            if not 6 <= hour < 18:
                return 0.0
            monsoon = 0.62 if 6 <= t.month <= 9 else 0.9
            clouds = self.rng.uniform(0.75, 1.0) if 6 <= t.month <= 9 else self.rng.uniform(0.92, 1.0)
            return max(0.0, math.sin(math.pi * (hour - 6) / 12)) * monsoon * clouds
        if profile == 'office':
            if day in HOLIDAYS or t.weekday() in (4, 5):
                base = 0.22
            elif 8.5 <= hour < 18.5:
                base = 0.75 if 13 <= hour < 14 else 0.9
            elif 7.5 <= hour < 8.5 or 18.5 <= hour < 20:
                base = 0.5
            else:
                base = 0.22
            return base * (0.45 + 0.55 * HVAC_BY_MONTH[t.month])
        if profile == 'pumps':
            base = 0.45 + (0.35 if 5 <= hour < 9 or 17 <= hour < 21 else 0.0)
            return base * (0.7 if day in HOLIDAYS else 1.0)
        # Three-shift production (textile mills run around the clock).
        if day in HOLIDAYS:
            return 0.10
        if t.weekday() == 4:  # Friday
            return 0.30
        base = 0.86
        if t.hour in (6, 14, 22):  # shift change
            base *= 0.8
        return base

    def _event(self, t):
        for start, end, mode in self.events:
            if start <= t < end:
                return mode
        return None

    # -- readings ----------------------------------------------------------
    def sample(self, t, hours):
        """Reading at aware time ``t``; counters advance by ``hours`` of flow."""
        local_t = timezone.localtime(t)
        event = self._event(t)
        rng = self.rng
        kind = self.kind
        if kind == 'Electricity Meter':
            return self._electric(local_t, hours, event)
        noise = rng.uniform(0.95, 1.05)
        load = self.load(local_t) * self._growth(local_t) * noise
        if kind == 'Steam Meter':
            flow = self.spec['rated'] * load * (0.6 if event else 1.0)
            pressure = rng.uniform(6.2, 6.6) if event else clip(rng.gauss(9.6, 0.25), 8.8, 10.4)
            self.counters['Total Steam'] += flow * hours
            return {'Steam Flow Rate': round(flow, 1), 'Steam Pressure': round(pressure, 2),
                    'Total Steam': round(self.counters['Total Steam'], 1)}
        if kind == 'Gas Meter':
            flow = self.spec['rated'] * load
            self.counters['Total Gas Volume'] += flow * hours
            return {'Gas Flow Rate': round(flow, 1), 'Gas Pressure': round(clip(rng.gauss(1.2, 0.04), 1.05, 1.35), 2),
                    'Total Gas Volume': round(self.counters['Total Gas Volume'], 1)}
        if kind == 'Water Meter':
            flow = self.spec['rated'] * load
            self.counters['Total Volume'] += flow * hours
            return {'Flow Rate': round(flow, 2), 'Total Volume': round(self.counters['Total Volume'], 2)}
        if kind == 'Fuel Meter':
            rate = self._generator_rate(local_t)
            self.counters['Total Fuel Used'] += rate * hours
            return {'Fuel Consumption Rate': round(rate, 1), 'Total Fuel Used': round(self.counters['Total Fuel Used'], 1)}
        if kind == 'Air Quality' and not self.spec.get('indoor'):
            if self._pm_day != local_t.date():
                self._pm_day, self._pm_factor = local_t.date(), rng.uniform(0.8, 1.2)
            diurnal = 1.25 if 6 <= local_t.hour < 9 or 19 <= local_t.hour < 23 else 0.9
            pm25 = PM25_BY_MONTH[local_t.month] * self.spec.get('air_factor', 1.0) * self._pm_factor * diurnal * rng.uniform(0.9, 1.1)
            if event:
                pm25 = self.spec['pm_limit'] * rng.uniform(1.15, 1.4)
            traffic = 1.0 if 7 <= local_t.hour < 21 else 0.3
            return {'CO2 Level': round(430 + 70 * traffic + rng.uniform(-15, 15), 1),
                    'PM2.5': round(pm25, 1), 'PM10': round(pm25 * rng.uniform(1.6, 2.0), 1)}
        if kind == 'Air Quality' and self.spec.get('indoor'):
            occupancy = self.occupied(local_t)
            co2 = 440 + 400 * occupancy * rng.uniform(0.85, 1.08)
            if event:
                co2 = rng.uniform(1180, 1420)
            pm25 = PM25_BY_MONTH[local_t.month] * 0.3 * rng.uniform(0.8, 1.2)
            return {'CO2 Level': round(co2, 1), 'PM2.5': round(pm25, 1), 'PM10': round(pm25 * rng.uniform(1.4, 1.7), 1)}
        if kind == 'Temperature':
            return {'Temperature': round(self._temperature(local_t, event), 1)}
        if kind == 'Humidity':
            profile = self.spec.get('profile')
            if profile == 'textile':
                rh = clip(rng.gauss(58, 1.6), 53, 63)
            elif profile == 'dock':
                rh = clip((80 if 6 <= local_t.month <= 9 else 66) + 6 * math.cos(math.pi * (local_t.hour - 5) / 12)
                          + rng.gauss(0, 2), 45, 96)
            else:
                rh = clip(rng.gauss(52 if self.occupied(local_t) > 0.4 else 61, 2.5), 38, 72)
            return {'Humidity': round(rh, 1)}
        if kind == 'Pressure':
            return {'Pressure': round(self._pressure(local_t, event), 2)}
        return {}

    def _temperature(self, local_t, event):
        rng = self.rng
        profile = self.spec.get('profile', 'cold_store')
        if profile == 'cold_store':
            temp = clip(rng.gauss(3.6, 0.4), 2.4, 4.8)
            if local_t.hour in (0, 8, 16) and local_t.minute < 30:
                temp += 2.2  # defrost cycle
            return rng.uniform(9.5, 11.5) if event else temp
        if profile == 'data_hall':
            return rng.uniform(27.5, 29.5) if event else clip(rng.gauss(22.4, 0.35), 21.2, 23.6)
        if profile == 'server_room':
            return rng.uniform(28.0, 30.0) if event else clip(rng.gauss(23.1, 0.5), 21.5, 24.8)
        if profile == 'chilled_water':
            return rng.uniform(10.5, 12.0) if event else clip(rng.gauss(6.8, 0.3), 5.9, 7.8)
        # office
        occupied = self.occupied(local_t) > 0.4
        return clip(rng.gauss(24.0 if occupied else 26.6, 0.6 if occupied else 0.7), 21.5, 28.4)

    def _pressure(self, local_t, event):
        rng = self.rng
        profile = self.spec.get('profile')
        if profile == 'compressed_air':
            if event:
                return rng.uniform(5.5, 5.9)
            return clip(rng.gauss(7.0 if self.load(local_t) > 0.5 else 7.4, 0.08), 6.6, 7.7)
        if profile == 'fire_water':
            return clip(rng.gauss(8.6, 0.08), 8.3, 8.9)
        if profile == 'treated_water':
            if event:
                return rng.uniform(1.4, 1.8)
            pumping = 5 <= local_t.hour < 9 or 17 <= local_t.hour < 21
            return clip(rng.gauss(3.3 if pumping else 2.8, 0.12), 2.3, 3.8)
        # condenser water loop
        return clip(rng.gauss(2.2 if 7 <= local_t.hour < 21 else 1.9, 0.07), 1.7, 2.5)

    def _generator_rate(self, local_t):
        """Standby diesel generator: runs only during grid outages (load shedding)."""
        day = local_t.date()
        if self._outage_day != day:
            day_rng = random.Random(day.toordinal() * 31 + 7)
            chance = 0.6 if 4 <= day.month <= 9 else 0.15
            if day_rng.random() < chance:
                start = day_rng.randint(10, 19)
                self._outage = (start, start + day_rng.randint(1, 3))
            else:
                self._outage = None
            self._outage_day = day
        if self._outage and self._outage[0] <= local_t.hour < self._outage[1]:
            return self.rng.uniform(38, 46)
        return 0.0

    def _electric(self, t, hours, event):
        rng = self.rng
        rated = self.spec['rated']
        load = self.load(t) * self._growth(t) * rng.uniform(0.96, 1.04)
        if self.spec.get('profile') == 'compressor':
            load *= rng.uniform(0.85, 1.0)
        kw = rated * load
        pf = rng.uniform(*self.spec.get('pf', (0.925, 0.975)))
        volts = [clip(rng.gauss(230.5, 1.3), 226, 235) for _ in range(3)]
        if event == 'sag':
            volts = [rng.uniform(202, 206) for _ in range(3)]
        elif event == 'low_pf':
            pf = rng.uniform(0.83, 0.86)
        elif event == 'overcurrent':
            kw = rated * rng.uniform(1.35, 1.45)
        kvar = kw * math.tan(math.acos(pf))
        kva = kw / pf
        self.counters['Energy'] += kw * hours
        self.counters['Total Reactive Power'] += kvar * hours
        self.counters['Total Apparent Power'] += kva * hours
        share = [rng.uniform(0.97, 1.03) for _ in range(3)]
        total_share = sum(share)
        phase_kw = [kw * s / total_share for s in share]
        currents = [p * 1000 / (v * pf) for p, v in zip(phase_kw, volts)]
        line = [v * math.sqrt(3) * rng.uniform(0.998, 1.002) for v in volts]
        data = {
            "Voltage L1N": volts[0], "Voltage L2N": volts[1], "Voltage L3N": volts[2],
            "Voltage L1-L2": line[0], "Voltage L2-L3": line[1], "Voltage L3-L1": line[2],
            "3-Phase Average Voltage L-N": sum(volts) / 3, "3-Phase Average Voltage L-L": sum(line) / 3,
            "Current L1": currents[0], "Current L2": currents[1], "Current L3": currents[2],
            "3-Phase Average Current L-L": sum(currents) / 3,
            "Line Frequency": clip(rng.gauss(50.0, 0.08), 49.7, 50.3),
            "Power Factor": pf,
            "Active Power L1": phase_kw[0], "Active Power L2": phase_kw[1], "Active Power L3": phase_kw[2],
            "THD Voltage L1-L2": rng.uniform(2.2, 4.8), "THD Voltage L2-L3": rng.uniform(2.2, 4.8),
            "THD Voltage L3-L1": rng.uniform(2.2, 4.8),
            "Total Active Power": self.counters['Energy'],
            "Total Reactive Power": self.counters['Total Reactive Power'],
            "Total Apparent Power": self.counters['Total Apparent Power'],
            "Energy": self.counters['Energy'],
        }
        digits = {"Power Factor": 3, "Line Frequency": 2}
        return {key: round(value, digits.get(key, 2 if key.startswith(("THD", "Active", "Total", "Energy")) else 1))
                for key, value in data.items()}

    def rated_current(self):
        return self.spec['rated'] * 1000 / (3 * 230 * 0.95)


# (meter, mode, hours before now, duration in hours, operator note when acknowledged)
EVENTS = [
    ('Dye House Feeder', 'sag', 650, 2, 'Grid voltage dip reported by the utility; dyeing machines restarted, no damage.'),
    ('Dye House Feeder', 'sag', 290, 1, 'Short dip during 33 kV feeder switching.'),
    ('Assembly Line Feeder', 'sag', 330, 1, 'Grid disturbance; line restarted after 12 minutes.'),
    ('Air Compressor 1', 'low_pf', 520, 3, 'Capacitor bank stage 3 contactor failed; replaced.'),
    ('Air Compressor 1', 'low_pf', 200, 2, 'APFC relay set to manual during maintenance.'),
    ('Air Compressor 1', 'low_pf', 3, 2, None),
    ('Ring Frame Line 1', 'overcurrent', 410, 1, 'Motor bearing jam on frame RF-07; bearing replaced.'),
    ('Ring Frame Line 1', 'overcurrent', 70, 1, 'Simultaneous start of frames after power restoration.'),
    ('Boiler Steam Header', 'low_pressure', 460, 2, 'Burner flame failure; boiler restarted by shift engineer.'),
    ('Boiler Steam Header', 'low_pressure', 8, 1.5, None),
    ('Compressed Air Header', 'low_pressure', 120, 2, 'Receiver auto-drain valve stuck open; valve replaced.'),
    ('Compressed Air Header', 'low_pressure', 5, 1.5, None),
    ('Ambient Air Monitor', 'high', 380, 4, 'Construction dust near the boiler house.'),
    ('Ambient Air Monitor', 'high', 150, 3, 'Brick kiln smoke with low wind; windows closed.'),
    ('Plant Ambient Air Monitor', 'high', 6, 4, None),
    ('Cold Store Temperature', 'high', 240, 2, 'Door left open during loading; staff briefed.'),
    ('Cold Store Temperature', 'high', 1.5, 3, None),
    ('Chiller CH-1 Feeder', 'overcurrent', 180, 1, 'Compressor restart after power restoration.'),
    ('Treated Water Pressure', 'low_pressure', 90, 2, 'Transfer pump P-201 tripped on overload; reset and restarted.'),
    ('Data Hall Temperature', 'high', 300, 2, 'CRAC unit 2 tripped on high head pressure; condenser coil cleaned.'),
    ('Data Hall Temperature', 'high', 2, 2, None),
    ('Conference Room CO2', 'high', 30, 3, 'Board meeting with fresh-air damper at minimum; damper setpoint raised.'),
    ('Conference Room CO2', 'high', 4, 2, None),
    ('Tower A Office DB', 'low_pf', 260, 2, 'LED driver batch with poor power factor on level 9; supplier notified.'),
]

PEOPLE = [
    # username, name, role, site index
    ('farhana.rahman@example.com', 'Farhana Rahman', 'Administrator', 0),
    ('imran.hossain@example.com', 'Imran Hossain', 'Operator', 0),
    ('rumana.akter@example.com', 'Rumana Akter', 'Quality Manager', 0),
    ('nusrat.jahan@example.com', 'Nusrat Jahan', 'Shift Manager', 1),
    ('sajid.karim@example.com', 'Sajid Karim', 'Maintenance Personnel', 1),
    ('tanvir.ahmed@example.com', 'Tanvir Ahmed', 'Setup Technician', 1),
    ('mehedi.hasan@example.com', 'Mehedi Hasan', 'Administrator', 2),
    ('sadia.islam@example.com', 'Sadia Islam', 'Operator', 2),
    ('arif.chowdhury@example.com', 'Arif Chowdhury', 'Maintenance Personnel', 2),
]

BROWSERS = [
    ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36', 'Chrome on Windows'),
    ('Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:142.0) Gecko/20100101 Firefox/142.0', 'Firefox on Windows'),
    ('Mozilla/5.0 (Linux; Android 14; SM-A546E) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36', 'Chrome Mobile on Android'),
]


class Command(BaseCommand):
    help = "Delete ALL data and load a compact, realistic demo data set (see module docstring)."

    def add_arguments(self, parser):
        parser.add_argument('--flush', action='store_true',
                            help='Required: confirms that every row in the database will be deleted first.')
        parser.add_argument('--password', help='Password for the demo accounts (default: a random one, printed).')
        parser.add_argument('--admin-password', help="Password for the 'admin' superuser (default: --password).")
        parser.add_argument('--seed', type=int, default=2026)

    def handle(self, *args, **options):
        if not options['flush']:
            raise CommandError('This command deletes every row in the database. Re-run with --flush to confirm.')
        password = options['password'] or secrets.token_urlsafe(9)
        admin_password = options['admin_password'] or password
        self.rng = random.Random(options['seed'])
        self.seed = options['seed']

        self.now = timezone.now().replace(second=0, microsecond=0)
        self.now -= timedelta(minutes=self.now.minute % 15)
        self.today = timezone.localdate(self.now)
        first_of_month = self.today.replace(day=1)
        self.raw_start_day = (first_of_month - timedelta(days=1)).replace(day=1)
        self.history_start_day = date(self.today.year - 1, 1, 1)
        self.raw_start = self._aware(self.raw_start_day)
        self.dense_start = self.now - timedelta(hours=48)

        self.stdout.write('Deleting all data...')
        call_command('flush', interactive=False, verbosity=0)

        with transaction.atomic():
            self.create_configuration()
            self.create_plant()
            self.create_users(password, admin_password)
        self.create_readings()
        with transaction.atomic():
            self.stdout.write('Building hierarchy aggregates...')
            run_hierarchy_aggregation()
            SystemJob.objects.update_or_create(name=JOB_NAME, defaults={'last_run': self.now})
            self.create_alarms()
            self.create_dashboards()
            self.create_reports()
            self.create_bills()
            self.create_scada()
            self.create_files()

        with connection.cursor() as cursor:
            if connection.vendor == 'sqlite':
                cursor.execute('VACUUM')
        self.summary(password, admin_password)

    # ------------------------------------------------------------------
    def _aware(self, day, hour=0, minute=0):
        return timezone.make_aware(datetime.combine(day, time(hour, minute)))

    def create_configuration(self):
        GlobalConfiguration.objects.create(report=True, dashboard=True, alarm=True, siteLocations=True,
                                           scada=True, billing=True, subscribed=True, treeType='hierarchy')
        labels = {
            'opcua': 'OPC UA server (Siemens WinCC)', 'mbus': 'M-Bus level converter with TCP port (Relay PW3)',
            'dali': 'DALI gateway (daliserver)', 'knx': 'KNXnet/IP interface (MDT SCN-IP100)', 'mqtt': 'MQTT broker (Mosquitto)',
        }
        ports = {'opcua': 4862, 'mbus': 10001, 'dali': 55825, 'knx': 3671, 'mqtt': 1883}
        for site in SITES:
            used = {m['protocol'] for _, areas in site['buildings'] for _, meters in areas for m in meters}
            for protocol, host in GATEWAYS.items():
                if protocol in used:
                    Masters.objects.create(masterType=f"{labels[protocol]} - {site['name']}",
                                           ip=f"{site['net']}.{host}", port=ports[protocol])
        Masters.objects.create(masterType='Public OPC UA demo server (Unified Automation)', ip='opcuaserver.com', port=48010)
        Masters.objects.create(masterType='Public OPC UA sample server (OPC Labs)', ip='opcua.demo-this.com', port=51210)
        Masters.objects.create(masterType='Public MQTT test broker (Eclipse Mosquitto)', ip='test.mosquitto.org', port=1883)

    def create_plant(self):
        self.load_types = {name: LoadType.objects.create(name=name) for name in LOAD_TYPES}
        self.sites, self.buildings, self.meters, self.simulators = [], {}, {}, {}
        self.live_meters = set()
        device_no = 0
        for site_index, site_spec in enumerate(SITES):
            site = Site.objects.create(name=site_spec['name'], latitude=site_spec['latitude'], longitude=site_spec['longitude'])
            self.sites.append(site)
            host = 10
            counters = {'mbus': 0, 'dali': 0, 'knx': 0}
            for building_no, (building_name, areas) in enumerate(site_spec['buildings'], start=1):
                building = Buildings.objects.create(name=building_name, site=site)
                self.buildings[building_name] = building
                for area_name, meters in areas:
                    area = Areas.objects.create(name=area_name, building=building)
                    for spec in meters:
                        host += 1
                        device_no += 1
                        spec = dict(spec, _site=site_spec['name'])
                        spec['_fields'] = fields_for(spec, FIELDS_BY_TYPE)
                        if spec['protocol'] in counters:
                            counters[spec['protocol']] += 1
                        ip, conn, mapping = build_device(
                            spec, site_spec['net'], host, device_no,
                            mbus_address=counters['mbus'] or 1, dali_address=4 * counters['dali'],
                            knx_main=building_no)
                        meter = self._meter(area, spec, ip, conn, mapping)
                        self.meters[meter.name] = meter
                        self.simulators[meter.name] = MeterSimulator(spec, self.seed + device_no, self.history_start_day)
            if site_spec['name'] == LIVE_SITE:
                self._create_live_meters(site)

        # PM2.5 limit just above the worst normal value of the stored months (smog season is much higher).
        months = {self.raw_start_day.month, self.today.month}
        for name, simulator in self.simulators.items():
            if simulator.kind == 'Air Quality' and not simulator.spec.get('indoor'):
                worst = max(PM25_BY_MONTH[m] for m in months) * simulator.spec.get('air_factor', 1.0) * 1.2 * 1.25 * 1.1
                simulator.spec['pm_limit'] = max(75, 5 * math.ceil(worst / 5 + 2))

        for name, mode, hours_ago, duration, _ in EVENTS:
            start = self.now - timedelta(hours=hours_ago)
            self.simulators[name].events.append((start, start + timedelta(hours=duration), mode))

    def _create_live_meters(self, site):
        building = Buildings.objects.create(name=LIVE_BUILDING, site=site)
        self.buildings[LIVE_BUILDING] = building
        for area_name, meters in LIVE_METERS:
            area = Areas.objects.create(name=area_name, building=building)
            for spec in meters:
                meter = self._meter(area, spec, spec['host'], dict(spec['connection']), spec['mapping'])
                self.meters[meter.name] = meter
                self.live_meters.add(meter.name)

    def _meter(self, area, spec, ip, conn, mapping):
        meter = Meters.objects.create(
            name=spec['name'], ip=ip, area=area, loadType=self.load_types[spec['load']], meterType=spec['type'],
            ecological=spec.get('ecological', False), registerMapping=mapping, protocol=spec['protocol'], connection=conn,
        )
        for field in mapping:
            measurement = Measurements.objects.create(name=field, meter=meter)
            if field in MEASUREMENT_UNITS:
                Units.objects.create(name=MEASUREMENT_UNITS[field], measurement=measurement)
        return meter

    # ------------------------------------------------------------------
    def create_users(self, password, admin_password):
        joined = self._aware(self.history_start_day + timedelta(days=4), 10)
        admin = User.objects.create_superuser('admin', 'admin@example.com', admin_password,
                                              first_name='System', last_name='Administrator')
        User.objects.filter(pk=admin.pk).update(date_joined=joined)
        self.admin_profile = UserModel.objects.create(user=admin, name='System Administrator', email='admin@example.com',
                                                      role='Administrator', site=self.sites[0], password=admin_password,
                                                      phone='+8801700000000')
        self.profiles = {'admin': self.admin_profile}
        for index, (username, name, role, site_index) in enumerate(PEOPLE, start=1):
            first, last = name.split(' ', 1)
            user = User.objects.create_user(username, username, password, first_name=first, last_name=last)
            User.objects.filter(pk=user.pk).update(date_joined=joined + timedelta(days=self.rng.randint(1, 200)))
            self.profiles[username] = UserModel.objects.create(
                user=user, name=name, email=username, role=role, site=self.sites[site_index], password=password,
                phone=f'+88017{index:02d}{self.rng.randint(100000, 999999)}',
                last_activity=self.now - timedelta(minutes=self.rng.randint(5, 3000)),
            )

        history = []
        for profile in self.profiles.values():
            site_net = 10 * (1 + self.sites.index(profile.site))
            for _ in range(self.rng.randint(2, 5)):
                agent, device = self.rng.choice(BROWSERS)
                history.append(LoginHistory(
                    user=profile.user, ip_address=f"192.168.{site_net}.{self.rng.randint(20, 220)}",
                    user_agent=agent, device=device,
                ))
        LoginHistory.objects.bulk_create(history)
        for entry in LoginHistory.objects.all():
            day = self.today - timedelta(days=self.rng.randint(0, 13))
            stamp = min(self._aware(day, self.rng.randint(7, 20), self.rng.randint(0, 59)), self.now)
            LoginHistory.objects.filter(pk=entry.pk).update(timestamp=stamp)
            User.objects.filter(pk=entry.user_id, last_login__lt=stamp).update(last_login=stamp)
            User.objects.filter(pk=entry.user_id, last_login__isnull=True).update(last_login=stamp)

    # ------------------------------------------------------------------
    def create_readings(self):
        history_start = self._aware(self.history_start_day)
        self.raw_rows = {}
        total = 0
        for name, meter in self.meters.items():
            if name in self.live_meters:
                continue
            sim = self.simulators[name]
            fields = list(meter.registerMapping)
            stored = []

            def sample(t, hours):
                data = sim.sample(t, hours)
                return {k: data[k] for k in fields if k in data}

            def stream():
                t = history_start
                while t < self.raw_start:  # history: folded into aggregates, never stored
                    yield t, sample(t, 2)
                    t += timedelta(hours=2)
                while t <= self.now:
                    step = 0.25 if t >= self.dense_start else 1
                    data = sample(t, step)
                    stored.append(MeterReading(meter=meter, timestamp=t, data=data))
                    yield t, data
                    t += timedelta(hours=step)

            buckets = fold_readings(stream())
            with transaction.atomic():
                MeterReading.objects.bulk_create(stored, batch_size=1000)
                LatestMeterReading.record(meter, stored[-1].timestamp, stored[-1].data)
                aggregates = [
                    MeterReadingAggregate(meter=meter, period_type=period_type, start_date=start_date,
                                          aggregateData=bucket.values())
                    for period_type in RAW_PERIODS
                    for start_date, bucket in rollup(buckets, period_type).items()
                ]
                MeterReadingAggregate.objects.bulk_create(aggregates, batch_size=500)
                derive_long_periods(meter)
            self.raw_rows[name] = [(row.timestamp, row.data) for row in stored]
            total += len(stored)
            self.stdout.write(f"  {name} ({meter.get_protocol_display()}): {len(stored)} readings")
        self.stdout.write(f"Stored {total} raw readings for {len(self.raw_rows)} simulated meters; "
                          f"{len(self.live_meters)} meters read live from online simulators.")

    # ------------------------------------------------------------------
    def create_alarms(self):
        def m(meter, field):
            return Measurements.objects.get(meter=meter, name=field)

        temperature_limits = {'cold_store': (0, 8), 'server_room': (None, 27), 'data_hall': (18, 27),
                              'chilled_water': (5, 9), 'office': (18, 29.5)}
        humidity_limits = {'textile': (50, 65), 'dock': (None, 94), 'office': (30, 70)}
        pressure_limits = {'compressed_air': (6.2, 8.0), 'fire_water': (7.5, None), 'treated_water': (2.0, 4.5),
                           'condenser': (1.5, 3.0)}
        ranges = []
        for name, meter in self.meters.items():
            if name in self.live_meters:
                continue
            sim = self.simulators[name]
            fields = set(meter.registerMapping)
            profile = sim.spec.get('profile')
            kind = meter.meterType
            if kind == 'Electricity Meter':
                if 'Voltage L1N' in fields:
                    ranges.append((meter, 'Voltage L1N', 207, 253))
                if 'Power Factor' in fields and profile != 'solar':
                    ranges.append((meter, 'Power Factor', 0.90, None))
                if 'Current L1' in fields:
                    ranges.append((meter, 'Current L1', None, round(sim.rated_current() * 1.15)))
            elif kind == 'Temperature':
                ranges.append((meter, 'Temperature', *temperature_limits[profile]))
            elif kind == 'Humidity':
                ranges.append((meter, 'Humidity', *humidity_limits[profile]))
            elif kind == 'Pressure':
                ranges.append((meter, 'Pressure', *pressure_limits[profile]))
            elif kind == 'Air Quality':
                ranges.append((meter, 'CO2 Level', None, 1000))
                if not sim.spec.get('indoor'):
                    ranges.append((meter, 'PM2.5', None, sim.spec['pm_limit']))
            elif kind == 'Steam Meter':
                ranges.append((meter, 'Steam Pressure', 7.0, 11.5))
            elif kind == 'Gas Meter' and 'Gas Pressure' in fields:
                ranges.append((meter, 'Gas Pressure', 0.8, 1.6))
            elif kind == 'Water Meter':
                ranges.append((meter, 'Flow Rate', None, round(sim.spec['rated'] * 1.6, 1)))
            elif kind == 'Fuel Meter':
                ranges.append((meter, 'Fuel Consumption Rate', None, 60))
        range_objects = [
            AlarmsRange.objects.create(meter=meter, measurement=m(meter, field), minValue=low, maxValue=high)
            for meter, field, low, high in ranges
        ]

        notes = {}
        for name, _, hours_ago, _, note in EVENTS:
            notes.setdefault(name, []).append((self.now - timedelta(hours=hours_ago), note))

        acknowledgers = {site.pk: [p.user for p in self.profiles.values()
                                   if p.site_id == site.pk and p.role in ('Administrator', 'Operator', 'Shift Manager')]
                         for site in self.sites}
        created = 0
        for range_obj in range_objects:
            meter, name = range_obj.meter, range_obj.measurement.name
            excursion = None
            excursions = []
            for timestamp, data in self.raw_rows[meter.name]:
                value = data.get(name)
                direction = None
                if value is not None:
                    if range_obj.minValue is not None and value < range_obj.minValue:
                        direction = 'Low'
                    elif range_obj.maxValue is not None and value > range_obj.maxValue:
                        direction = 'High'
                if direction and excursion and excursion['type'] == direction:
                    worse = value < excursion['value'] if direction == 'Low' else value > excursion['value']
                    if worse:
                        excursion['value'] = value
                elif direction:
                    excursion = {'type': direction, 'start': timestamp, 'value': value}
                    excursions.append(excursion)
                else:
                    excursion = None

            for exc in excursions:
                limit = range_obj.minValue if exc['type'] == 'Low' else range_obj.maxValue
                desc = f"{name} {'below min' if exc['type'] == 'Low' else 'above max'} ({limit})"
                note = next((text for start, text in notes.get(meter.name, [])
                             if abs((start - exc['start']).total_seconds()) <= 3600 and text), None)
                acknowledged = exc['start'] < self.now - timedelta(hours=24) and note is not None
                alarm = Alarms.objects.create(meter=meter, measurement=range_obj.measurement, value=exc['value'],
                                              alarmType=exc['type'], desc=note if acknowledged else desc)
                update = {'date': exc['start']}
                if acknowledged:
                    people = acknowledgers[meter.area.building.site_id]
                    update.update(acknowledged=True, acknowledgedBy=self.rng.choice(people),
                                  acknowledgedAt=exc['start'] + timedelta(minutes=self.rng.randint(8, 95)))
                Alarms.objects.filter(pk=alarm.pk).update(**update)
                created += 1
        self.stdout.write(f"Created {len(range_objects)} alarm limits and {created} alarms.")

    # ------------------------------------------------------------------
    def create_dashboards(self):
        everyone = list(ROLES)
        analysts = ['Administrator', 'Operator', 'Quality Manager', 'Shift Manager']

        def gadget(dashboard, name, kind, meters=(), measurements=(), access=everyone, building=None):
            g = Gadgets.objects.create(name=name, gadget_type=kind, dashboard=dashboard, access=list(access),
                                       building=self.buildings.get(building))
            meter_objs = [self.meters[m] for m in meters]
            g.meters.set(meter_objs)
            site = dashboard.site
            picked = []
            for field in measurements:
                qs = Measurements.objects.filter(name=field)
                qs = qs.filter(meter__in=meter_objs) if meter_objs else qs.filter(meter__area__building__site=site)
                picked.append(qs.order_by('id').first())
            g.measurement.set([p for p in picked if p])
            return g

        gazipur, chattogram, dhaka = self.sites
        live = ['3-Phase Average Voltage L-N', '3-Phase Average Current L-L', 'Power Factor', 'Energy']

        # Every overview dashboard uses all ten gadget types.
        feeders = ['Ring Frame Line 1', 'Ring Frame Line 2', 'Air Compressor 1', 'Dye House Feeder', 'Admin HVAC & Lighting']
        mill = Dashboard.objects.create(title='Mill Energy Overview', site=gazipur)
        gadget(mill, 'Site energy', 'valueCard', measurements=['Energy'])
        gadget(mill, 'Energy share by feeder', 'pie', feeders, ['Energy'], analysts)
        gadget(mill, 'Monthly energy, year on year', 'bar', ['Ring Frame Line 1', 'Ring Frame Line 2', 'Dye House Feeder'], ['Energy'], analysts)
        gadget(mill, 'Ring Frame Line 1 phase voltages', 'line', ['Ring Frame Line 1'], ['Voltage L1N', 'Voltage L2N', 'Voltage L3N'])
        gadget(mill, 'Feeder status', 'multiple-meter-table', ['Ring Frame Line 1', 'Ring Frame Line 2', 'Air Compressor 1', 'Dye House Feeder'], live)
        gadget(mill, 'Energy flow', 'sankey', measurements=['Energy'], access=analysts)
        gadget(mill, 'Air compressor hourly energy', 'heatmap', ['Air Compressor 1'], ['Energy'], analysts)
        gadget(mill, 'Air Compressor 1 live', 'tool', ['Air Compressor 1'], ['Active Power L1', '3-Phase Average Current L-L', 'Power Factor'])
        gadget(mill, 'Spinning Unit energy map', 'picturemap', measurements=['Energy'], access=analysts, building='Spinning Unit')
        gadget(mill, 'Ring Frame Line 2 readings', 'table', ['Ring Frame Line 2'])

        utilities = Dashboard.objects.create(title='Boiler & Utilities', site=gazipur)
        gadget(utilities, 'Steam header', 'line', ['Boiler Steam Header'], ['Steam Flow Rate', 'Steam Pressure'])
        gadget(utilities, 'Gas consumption, year on year', 'bar', ['Boiler Gas Line'], ['Total Gas Volume'], analysts)
        gadget(utilities, 'Process water log', 'table', ['Process Water Inlet'])
        gadget(utilities, 'Ambient air quality', 'tool', ['Ambient Air Monitor'], ['PM2.5', 'PM10', 'CO2 Level'])
        gadget(utilities, 'Compressed air pressure by hour', 'heatmap', ['Compressed Air Header'], ['Pressure'])
        gadget(utilities, 'Spinning hall humidity', 'line', ['Spinning Hall Humidity'], ['Humidity'])
        gadget(utilities, 'Server room temperature', 'tool', ['Server Room Temperature'], ['Temperature'])

        sims = Dashboard.objects.create(title='Live Simulator Feed', site=gazipur)
        gadget(sims, 'AHU supply air temperature (live)', 'line', ['AHU-1 Climate (UA demo)', 'AHU-2 Climate (UA demo)'],
               ['Air Temperature (°F)'])
        gadget(sims, 'Air handling units', 'multiple-meter-table', ['AHU-1 Climate (UA demo)', 'AHU-2 Climate (UA demo)'],
               ['Air Temperature (°F)', 'Humidity', 'Temperature Setpoint (°F)'])
        gadget(sims, 'AHU-4 humidity (live)', 'line', ['AHU-4 Humidity (UA demo)'], ['Humidity', 'Humidity Setpoint'])
        gadget(sims, 'AHU-3 power', 'tool', ['AHU-3 Power (UA demo)'], ['Power Consumption', 'Air Temperature (°F)', 'Unit State'])
        gadget(sims, 'Furnace-1 burner', 'tool', ['Furnace-1 Gas Burner (UA demo)'], ['Gas Flow', 'Air Temperature (°F)', 'Temperature Setpoint (°F)'])
        gadget(sims, 'Furnace-2 burner', 'tool', ['Furnace-2 Gas Burner (UA demo)'], ['Gas Flow', 'Air Temperature (°F)', 'Power Consumption'])
        gadget(sims, 'Boiler #1 drum log', 'table', ['Boiler #1 Drum (OPC Labs demo)'])
        gadget(sims, 'Boiler #1 flows (live)', 'line', ['Boiler #1 Drum (OPC Labs demo)'], ['Feed Water Flow', 'Steam Flow'])
        gadget(sims, 'Public MQTT broker load', 'line', ['Public Broker Telemetry (test.mosquitto.org)'],
               ['Messages Received (1 min avg)'])
        gadget(sims, 'Public MQTT broker', 'tool', ['Public Broker Telemetry (test.mosquitto.org)'],
               ['Clients Connected', 'Messages Received (1 min avg)', 'Data Received (MB, 1 min avg)'])
        gadget(sims, 'AHU-1 temperature by hour', 'heatmap', ['AHU-1 Climate (UA demo)'], ['Air Temperature (°F)'])

        plant_feeders = ['Assembly Line Feeder', 'Utility Pump House', 'Chiller CH-1 Feeder', 'Dispatch Bay Lighting']
        plant = Dashboard.objects.create(title='Chattogram Plant Overview', site=chattogram)
        gadget(plant, 'Site energy', 'valueCard', measurements=['Energy'])
        gadget(plant, 'Energy share by feeder', 'pie', plant_feeders, ['Energy'], analysts)
        gadget(plant, 'Monthly energy, year on year', 'bar', ['Assembly Line Feeder', 'Utility Pump House', 'Chiller CH-1 Feeder'], ['Energy'], analysts)
        gadget(plant, 'Assembly line phase currents', 'line', ['Assembly Line Feeder'], ['Current L1', 'Current L2', 'Current L3'])
        gadget(plant, 'Feeder status', 'multiple-meter-table', ['Assembly Line Feeder', 'Utility Pump House', 'Chiller CH-1 Feeder'], live)
        gadget(plant, 'Energy flow', 'sankey', measurements=['Energy'], access=analysts)
        gadget(plant, 'Cold store temperature profile', 'heatmap', ['Cold Store Temperature'], ['Temperature'])
        gadget(plant, 'Standby generator', 'tool', ['Standby Generator'], ['Fuel Consumption Rate', 'Total Fuel Used'])
        gadget(plant, 'Production Hall energy map', 'picturemap', measurements=['Energy'], access=analysts, building='Production Hall')
        gadget(plant, 'Chilled water supply log', 'table', ['Chilled Water Supply'])

        chain = Dashboard.objects.create(title='Cold Chain & Utility Centre', site=chattogram)
        gadget(chain, 'Cold store and chilled water', 'line', ['Cold Store Temperature', 'Chilled Water Supply'], ['Temperature'])
        gadget(chain, 'Water pressures', 'multiple-meter-table', ['Treated Water Pressure', 'Fire Water Header'], ['Pressure'])
        gadget(chain, 'Loading dock humidity by hour', 'heatmap', ['Loading Dock Humidity'], ['Humidity'])
        gadget(chain, 'Raw water intake, year on year', 'bar', ['Raw Water Intake'], ['Total Volume'], analysts)
        gadget(chain, 'Steam main', 'tool', ['Boiler Steam Main'], ['Steam Flow Rate', 'Steam Pressure', 'Total Steam'])
        gadget(chain, 'Plant ambient air', 'tool', ['Plant Ambient Air Monitor'], ['PM2.5', 'PM10', 'CO2 Level'])
        gadget(chain, 'Dispatch bay lighting log', 'table', ['Dispatch Bay Lighting'])

        campus_loads = ['Tower A Office DB', 'Campus Chiller Feeder', 'Data Centre UPS Output', 'Tower A Lobby Lighting',
                        'Conference Level Lighting', 'Cafeteria Tenant Submeter']
        campus = Dashboard.objects.create(title='Campus Energy & Comfort', site=dhaka)
        gadget(campus, 'Campus energy', 'valueCard', measurements=['Energy'])
        gadget(campus, 'Energy by system', 'pie', campus_loads, ['Energy'], analysts)
        gadget(campus, 'Chiller and offices, year on year', 'bar', ['Campus Chiller Feeder', 'Tower A Office DB'], ['Energy'], analysts)
        gadget(campus, 'Office and data hall temperature', 'line', ['Office Floor Temperature', 'Data Hall Temperature'], ['Temperature'])
        gadget(campus, 'Main distribution boards', 'multiple-meter-table', ['Tower A Office DB', 'Campus Chiller Feeder', 'Data Centre UPS Output'], live)
        gadget(campus, 'Energy flow', 'sankey', measurements=['Energy'], access=analysts)
        gadget(campus, 'Rooftop solar yield by hour', 'heatmap', ['Rooftop Solar Inverter'], ['Energy'])
        gadget(campus, 'Atrium air quality', 'tool', ['Atrium Air Quality'], ['CO2 Level', 'PM2.5', 'PM10'])
        gadget(campus, 'Tower A energy map', 'picturemap', measurements=['Energy'], access=analysts, building='Tower A')
        gadget(campus, 'Conference room CO2 log', 'table', ['Conference Room CO2'])

        tenants = Dashboard.objects.create(title='Lighting, Tenants & Utilities', site=dhaka)
        gadget(tenants, 'Lighting power', 'line', ['Tower A Lobby Lighting', 'Conference Level Lighting'], ['Active Power L1'])
        gadget(tenants, 'Lighting and tenant energy', 'pie', ['Tower A Lobby Lighting', 'Conference Level Lighting', 'Cafeteria Tenant Submeter'], ['Energy'], analysts)
        gadget(tenants, 'Cafeteria tenant, year on year', 'bar', ['Cafeteria Tenant Submeter'], ['Energy'], analysts)
        gadget(tenants, 'Kitchen gas', 'tool', ['Kitchen Gas Meter'], ['Gas Flow Rate', 'Total Gas Volume'])
        gadget(tenants, 'Campus water main log', 'table', ['Campus Water Main'])
        gadget(tenants, 'Condenser water pressure by hour', 'heatmap', ['Condenser Water Pressure'], ['Pressure'])
        gadget(tenants, 'Office climate', 'multiple-meter-table', ['Office Floor Temperature', 'Office Floor Humidity'], ['Temperature', 'Humidity'])
        gadget(tenants, 'Standby generator', 'tool', ['Campus Standby Generator'], ['Fuel Consumption Rate', 'Total Fuel Used'])

    # ------------------------------------------------------------------
    def create_reports(self):
        gazipur, chattogram, dhaka = self.sites
        month = self.raw_start_day
        month_end = self.today.replace(day=1) - timedelta(days=1)
        month_label = month.strftime('%B %Y')

        def day_start(day):
            return self._aware(day)

        def diagram(report, kind, meters, measurements, start, end, period=None, description=''):
            d = ReportDiagram.objects.create(report_format=report, site=report.site, diagram_type=kind,
                                             date_range_start=start, date_range_end=end, period_type=period,
                                             description=description)
            d.meters.set([self.meters[m] for m in meters])
            meter_objs = [self.meters[m] for m in meters] or list(Meters.objects.filter(area__building__site=report.site))
            d.measurements.set([Measurements.objects.filter(name=f, meter__in=meter_objs).order_by('id').first()
                                for f in measurements])
            return d

        farhana = self.profiles['farhana.rahman@example.com']
        nusrat = self.profiles['nusrat.jahan@example.com']
        mehedi = self.profiles['mehedi.hasan@example.com']

        r1 = ReportFormat.objects.create(
            title=f'Monthly Energy Report - {month_label}', site=gazipur, user=farhana, logo='',
            description=f'Electricity consumption, power quality and energy flow of Gazipur Textile Mill for {month_label}.')
        feeders = ['Ring Frame Line 1', 'Ring Frame Line 2', 'Air Compressor 1', 'Dye House Feeder', 'Admin HVAC & Lighting']
        diagram(r1, 'bar', ['Ring Frame Line 1', 'Ring Frame Line 2', 'Dye House Feeder'], ['Energy'],
                day_start(month.replace(month=1)), day_start(month_end), 'monthly',
                'Production feeders compared with the same months of last year.')
        diagram(r1, 'pie', feeders, ['Energy'], day_start(month), day_start(month_end), 'monthly',
                'Share of each feeder in the monthly electricity consumption.')
        diagram(r1, 'sankey', [], ['Energy'], day_start(month), day_start(month), 'monthly',
                'Energy flow from site to buildings, areas and meters.')
        diagram(r1, 'heatmap', ['Air Compressor 1'], ['Energy'], day_start(month), day_start(month_end), None,
                'Hourly compressor energy; night-time use points to air leaks.')
        diagram(r1, 'line', ['Ring Frame Line 1'], ['Voltage L1N', 'Voltage L2N', 'Voltage L3N'],
                self._aware(month + timedelta(days=9)), self._aware(month + timedelta(days=12)), None,
                'Supply voltage at the ring frame section over three days.')
        diagram(r1, 'table', ['Ring Frame Line 1'], ['3-Phase Average Voltage L-N', '3-Phase Average Current L-L', 'Power Factor', 'Energy'],
                day_start(month_end), day_start(month_end), None, 'Hourly readings on the last day of the month.')

        week_start = self.today - timedelta(days=self.today.weekday() + 7)
        r2 = ReportFormat.objects.create(
            title='Boiler House Weekly Review', site=gazipur, user=farhana, logo='',
            description='Steam generation, gas use, compressed air and ambient air quality around the boiler house.')
        diagram(r2, 'line', ['Boiler Steam Header'], ['Steam Flow Rate'],
                self._aware(week_start), self._aware(week_start + timedelta(days=7)), None, 'Steam demand over the week.')
        diagram(r2, 'bar', ['Boiler Gas Line'], ['Total Gas Volume'], day_start(week_start - timedelta(days=21)),
                day_start(week_start + timedelta(days=6)), 'weekly', 'Weekly gas consumption.')
        diagram(r2, 'heatmap', ['Ambient Air Monitor'], ['PM2.5'], day_start(week_start),
                day_start(week_start + timedelta(days=6)), None, 'PM2.5 by hour of day.')
        diagram(r2, 'heatmap', ['Compressed Air Header'], ['Pressure'], day_start(week_start),
                day_start(week_start + timedelta(days=6)), None, 'Compressed air header pressure by hour of day.')

        r3 = ReportFormat.objects.create(
            title='Chattogram Cold Chain & Utilities', site=chattogram, user=nusrat, logo='',
            description='Cold store and chilled water temperatures, standby generator use and feeder consumption.')
        diagram(r3, 'heatmap', ['Cold Store Temperature'], ['Temperature'], day_start(self.today - timedelta(days=13)),
                day_start(self.today), None, 'Hourly average temperature (limit 8 °C).')
        diagram(r3, 'line', ['Standby Generator'], ['Fuel Consumption Rate'],
                self._aware(self.today - timedelta(days=7)), self.now, None, 'Generator running periods during grid outages.')
        diagram(r3, 'pie', ['Assembly Line Feeder', 'Utility Pump House', 'Chiller CH-1 Feeder', 'Dispatch Bay Lighting'], ['Energy'],
                day_start(month), day_start(month_end), 'monthly', 'Consumption split between production, utilities and cooling.')
        diagram(r3, 'line', ['Chilled Water Supply'], ['Temperature'], self._aware(self.today - timedelta(days=3)), self.now, None,
                'Chilled water supply temperature over the last three days.')

        r4 = ReportFormat.objects.create(
            title=f'Dhaka Campus Energy & Comfort - {month_label}', site=dhaka, user=mehedi, logo='',
            description=f'Energy by building system, rooftop solar yield, tenant consumption and indoor climate for {month_label}.')
        diagram(r4, 'pie', ['Tower A Office DB', 'Campus Chiller Feeder', 'Data Centre UPS Output', 'Tower A Lobby Lighting',
                            'Conference Level Lighting', 'Cafeteria Tenant Submeter'], ['Energy'],
                day_start(month), day_start(month_end), 'monthly', 'Share of each building system in the monthly consumption.')
        diagram(r4, 'bar', ['Campus Chiller Feeder', 'Tower A Office DB'], ['Energy'], day_start(month.replace(month=1)),
                day_start(month_end), 'monthly', 'Chiller and office consumption compared with last year.')
        diagram(r4, 'sankey', [], ['Energy'], day_start(month), day_start(month), 'monthly', 'Energy flow through the campus.')
        diagram(r4, 'heatmap', ['Rooftop Solar Inverter'], ['Energy'], day_start(month), day_start(month_end), None,
                'Hourly solar yield; cloudy monsoon days stand out.')
        diagram(r4, 'line', ['Office Floor Temperature', 'Data Hall Temperature'], ['Temperature'],
                self._aware(month + timedelta(days=14)), self._aware(month + timedelta(days=17)), None,
                'Office and data hall temperatures over three working days.')
        diagram(r4, 'table', ['Cafeteria Tenant Submeter'], ['Voltage L1N', 'Current L1', 'Energy'],
                day_start(month_end), day_start(month_end), None, 'Tenant submeter readings on the last day of the month.')

    # ------------------------------------------------------------------
    def create_bills(self):
        month = self.raw_start_day
        month_end = self.today.replace(day=1) - timedelta(days=1)
        farhana = self.profiles['farhana.rahman@example.com']
        nusrat = self.profiles['nusrat.jahan@example.com']
        mehedi = self.profiles['mehedi.hasan@example.com']
        specs = [
            ('Ring Frame Line 1', 'Gazipur Palli Bidyut Samity-1', 10.69, farhana, 0, {'Demand charge': 29400, 'Meter rent': 1500}),
            ('Ring Frame Line 2', 'Gazipur Palli Bidyut Samity-1', 10.69, farhana, 0, {'Demand charge': 26600, 'Meter rent': 1500}),
            ('Dye House Feeder', 'Gazipur Palli Bidyut Samity-1', 10.69, farhana, 0, {'Demand charge': 17500}),
            ('Assembly Line Feeder', 'BPDB Chattogram Distribution Zone', 11.03, nusrat, 850, {'Demand charge': 21000, 'Power factor surcharge': 3200}),
            ('Cafeteria Tenant Submeter', 'Dhaka Corporate Campus - Facilities (tenant recharge)', 12.67, mehedi, 0,
             {'Common area share': 4500, 'Service charge': 2000}),
            ('Campus Chiller Feeder', 'Dhaka Electric Supply Company (DESCO)', 11.93, mehedi, 0, {'Demand charge': 38000}),
        ]
        for meter_name, authority, rate, author, penalty, extras in specs:
            bill = Billing(meter=self.meters[meter_name], rate=rate, tax=5, fixed_charge=0, penalty=penalty,
                           date_range_start=month, date_range_end=month_end, date_due=month_end + timedelta(days=20),
                           authority=authority, extra_fields=extras, generatedBy=author,
                           remarks=f"Tariff for {month.strftime('%B %Y')}.")
            bill.save()
            bill.total_consumption = calculate_bill(bill).consumption
            bill.save(update_fields=['total_consumption'])
            Billing.objects.filter(pk=bill.pk).update(created_at=month_end + timedelta(days=2))

        provisional = Billing(meter=self.meters['Ring Frame Line 1'], rate=10.69, tax=5, fixed_charge=0, penalty=0,
                              date_range_start=self.today.replace(day=1), date_range_end=self.today,
                              date_due=self.today + timedelta(days=30), authority='Gazipur Palli Bidyut Samity-1',
                              extra_fields={}, generatedBy=farhana, remarks='Provisional month-to-date estimate.')
        provisional.save()
        provisional.total_consumption = calculate_bill(provisional).consumption
        provisional.save(update_fields=['total_consumption'])

    # ------------------------------------------------------------------
    def create_scada(self):
        from ml.demo import DEMO_DATA_SIZE, DEMO_FIELDS, generate_motor_telemetry

        masters = {}
        for site, cpu in ((SITES[0], 'Siemens S7-1200 (CPU 1214C)'), (SITES[1], 'Siemens S7-1500 (CPU 1511-1 PN)'),
                          (SITES[2], 'Siemens S7-1200 (CPU 1215C)')):
            ip = f"{site['net']}.{PLC_HOST}"
            masters[ip] = MotorMasters.objects.create(masterType=f"{cpu} - {site['name']}", ip=ip, port=102)

        fields = dict(DEMO_FIELDS)
        offsets = dict(motorOnOffset={'byte': 6, 'bit': 7}, motorOffOffset={'byte': 7, 'bit': 0},
                       runFeedbackOffset={'byte': 6, 'bit': 4}, tripOffset={'byte': 6, 'bit': 2})
        motors = [
            ('Process Water Pump P-101', 'Dyeing Unit', 0, 10, True),
            ('Cooling Tower Fan CT-1', 'Dyeing Unit', 0, 11, True),
            ('Overhead Tank Transfer Pump P-201', 'Production Hall', 1, 10, False),
            ('Chilled Water Pump CHWP-1', 'Energy Centre', 2, 10, True),
        ]
        created = []
        for name, building, site_index, db_no, is_on in motors:
            ip = f"{SITES[site_index]['net']}.{PLC_HOST}"
            motor = Motor.objects.create(motorName=name, motorMaster=masters[ip], building=self.buildings[building], ip=ip,
                                         dbNo=db_no, rack=0, slot=1, startByte=0, dataSize=DEMO_DATA_SIZE, fields=fields,
                                         isOn=is_on, **offsets)
            created.append(motor)
            if 'Tank' in name:
                Tank.objects.create(tankName='Overhead Water Tank (20 m³)', motor=motor, highByte=6, highBit=6,
                                    lowByte=6, lowBit=5, valueByte=4, tankVolume=20000)
            elif 'P-101' in name:
                Tank.objects.create(tankName='Process Water Tank (50 m³)', motor=motor, highByte=6, highBit=6,
                                    lowByte=6, lowBit=5, valueByte=4, tankVolume=50000)
        # Motor history for the predictive-maintenance model: the cooling tower fan develops a bearing fault.
        generate_motor_telemetry(created, days=45, degrading=created[1], warming=created[2], now=self.now)

    # ------------------------------------------------------------------
    def create_files(self):
        yesterday = self.today - timedelta(days=1)
        start, end = self._aware(yesterday), self._aware(self.today)
        for meter_name, columns in (
            ('Ring Frame Line 1', ['3-Phase Average Voltage L-N', '3-Phase Average Current L-L', 'Power Factor', 'Energy']),
            ('Boiler Steam Header', ['Steam Flow Rate', 'Steam Pressure', 'Total Steam']),
            ('Rooftop Solar Inverter', ['Active Power L1', 'Active Power L2', 'Active Power L3', 'Energy']),
        ):
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(['Timestamp'] + columns)
            for timestamp, data in self.raw_rows[meter_name]:
                if start <= timestamp < end:
                    writer.writerow([timezone.localtime(timestamp).strftime('%Y-%m-%d %H:%M')] + [data.get(c) for c in columns])
            slug = meter_name.lower().replace(' ', '-')
            meter = self.meters[meter_name]
            record = Files(name=f"{meter_name} export {yesterday.isoformat()}", meter=meter)
            record.file.save(f"{slug}-{yesterday.isoformat()}.csv", ContentFile(buffer.getvalue().encode('utf-8')), save=True)

    # ------------------------------------------------------------------
    def summary(self, password, admin_password):
        import os

        db_path = settings.DATABASES['default']['NAME']
        size = os.path.getsize(db_path) / 1_048_576 if connection.vendor == 'sqlite' and os.path.exists(db_path) else None
        by_protocol = ', '.join(f"{label} {Meters.objects.filter(protocol=key).count()}"
                                for key, label in Meters._meta.get_field('protocol').choices)
        rows = [
            ('Sites / buildings / areas', f"{Site.objects.count()} / {Buildings.objects.count()} / {Areas.objects.count()}"),
            ('Meters / measurements', f"{Meters.objects.count()} / {Measurements.objects.count()}"),
            ('Meters by protocol', by_protocol),
            ('Meter types', ', '.join(sorted(set(Meters.objects.values_list('meterType', flat=True))))),
            ('Raw readings', MeterReading.objects.count()),
            ('Meter aggregates', MeterReadingAggregate.objects.count()),
            ('Hierarchy aggregates', HierarchyDataAggregate.objects.count()),
            ('Alarms (active)', f"{Alarms.objects.count()} ({Alarms.objects.filter(acknowledged=False).count()})"),
            ('Dashboards / gadgets', f"{Dashboard.objects.count()} / {Gadgets.objects.count()}"),
            ('Reports / bills', f"{ReportFormat.objects.count()} / {Billing.objects.count()}"),
            ('Users', User.objects.count()),
        ]
        for label, value in rows:
            self.stdout.write(f"  {label:28} {value}")
        if size is not None:
            self.stdout.write(f"  {'Database size':28} {size:.1f} MB")
        admin_note = '' if admin_password == password else " ('admin' uses the --admin-password)"
        self.stdout.write(self.style.SUCCESS(
            f"Demo data loaded. Log in as 'admin' or any <name>@example.com user with password: {password}{admin_note}"))
