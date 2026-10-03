"""Generate realistic synthetic readings for demos and testing (replaces dataGeneratorCombined.py)."""
import math
import random
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from dashboard.measurements import METER_DEFINITIONS
from dashboard.models import LatestMeterReading, MeterReading
from dynamic.models import Meters


def daily_profile(ts):
    """Load factor 0.35..1.0 following a working-day curve (peak around 14:00)."""
    hour = ts.hour + ts.minute / 60
    base = 0.35 + 0.65 * max(0.0, math.sin(math.pi * (hour - 6) / 16)) if 6 <= hour <= 22 else 0.35
    return base * (0.8 if ts.weekday() == 4 else 1.0)  # Friday is the weekend day in Bangladesh


class Command(BaseCommand):
    help = "Insert synthetic readings for every meter (or --meter NAME) over the last N days."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=30)
        parser.add_argument('--interval', type=int, default=15, help='Minutes between readings (default 15).')
        parser.add_argument('--meter', action='append', help='Meter name (repeatable). Default: all meters.')
        parser.add_argument('--seed', type=int, default=7)
        parser.add_argument('--replace', action='store_true', help='Delete existing readings in the generated window first.')

    def handle(self, *args, **options):
        random.seed(options['seed'])
        meters = Meters.objects.all()
        if options['meter']:
            meters = meters.filter(name__in=options['meter'])
        if not meters.exists():
            raise CommandError('No meters found.')

        interval = timedelta(minutes=options['interval'])
        end = timezone.now().replace(second=0, microsecond=0)
        start = end - timedelta(days=options['days'])

        for meter in meters:
            if options['replace']:
                MeterReading.objects.filter(meter=meter, timestamp__gte=start).delete()
            fields = METER_DEFINITIONS.get(meter.meterType, METER_DEFINITIONS['Electricity Meter'])
            rows = list(self.generate(meter, fields, start, end, interval))
            MeterReading.objects.bulk_create(rows, batch_size=2000)
            if rows:
                LatestMeterReading.record(meter, rows[-1].timestamp, rows[-1].data)
            self.stdout.write(f"{meter.name}: {len(rows)} readings")

    def generate(self, meter, fields, start, end, interval):
        hours = interval.total_seconds() / 3600
        scale = random.uniform(0.6, 1.6)
        counters = {'Energy': 5000.0, 'Total Active Power': 1000.0, 'Total Reactive Power': 100.0,
                    'Total Apparent Power': 1100.0, 'Total kWh DG': 50.0, 'Total Volume': 1000.0,
                    'Total Gas Volume': 500.0, 'Total Steam': 1000.0, 'Total Fuel Used': 100.0}
        ts = start
        while ts <= end:
            local_ts = timezone.localtime(ts)
            load = daily_profile(local_ts) * scale
            kw = 45 * load * random.uniform(0.95, 1.05)
            pf = random.uniform(0.92, 0.99)
            kvar = kw * math.tan(math.acos(pf))
            data = {}
            for field in fields:
                if field.startswith('Voltage L') and '-' in field:
                    data[field] = round(random.uniform(398, 402), 1)
                elif field.startswith('Voltage L'):
                    data[field] = round(random.uniform(228, 232), 1)
                elif field == '3-Phase Average Voltage L-N':
                    data[field] = round(random.uniform(229, 231), 1)
                elif field == '3-Phase Average Voltage L-L':
                    data[field] = round(random.uniform(399, 401), 1)
                elif field.startswith('Current') or field == '3-Phase Average Current L-L':
                    data[field] = round(kw * 1000 / (math.sqrt(3) * 400 * pf) * random.uniform(0.97, 1.03), 2)
                elif field.startswith('Active Power L'):
                    data[field] = round(kw / 3 * random.uniform(0.95, 1.05), 2)
                elif field.startswith('Reactive Power L'):
                    data[field] = round(kvar / 3 * random.uniform(0.95, 1.05), 2)
                elif field.startswith('Apparent Power L'):
                    data[field] = round(kw / pf / 3 * random.uniform(0.95, 1.05), 2)
                elif field.startswith('Power Factor'):
                    data[field] = round(pf, 3)
                elif field.startswith('THD'):
                    data[field] = round(random.uniform(2.5, 5.0), 2)
                elif field == 'Line Frequency':
                    data[field] = round(random.uniform(49.9, 50.1), 2)
                elif field in ('Energy', 'Total Active Power'):
                    counters[field] += kw * hours
                    data[field] = round(counters[field], 3)
                elif field == 'Total Reactive Power':
                    counters[field] += kvar * hours
                    data[field] = round(counters[field], 3)
                elif field == 'Total Apparent Power':
                    counters[field] += kw / pf * hours
                    data[field] = round(counters[field], 3)
                elif field == 'Total kWh DG':
                    counters[field] += random.uniform(0, 0.2) * hours
                    data[field] = round(counters[field], 3)
                elif field in ('DG Sensing',):
                    data[field] = 0
                elif field in ('CT Primary', 'CT Secondary', 'PT Primary', 'PT Secondary'):
                    data[field] = {'CT Primary': 400, 'CT Secondary': 5, 'PT Primary': 11000, 'PT Secondary': 110}[field]
                elif field in ('Flow Rate', 'Gas Flow Rate', 'Steam Flow Rate', 'Fuel Consumption Rate'):
                    base = {'Flow Rate': 30, 'Gas Flow Rate': 75, 'Steam Flow Rate': 350, 'Fuel Consumption Rate': 7}[field]
                    data[field] = round(base * load * random.uniform(0.9, 1.1), 2)
                elif field in ('Total Volume', 'Total Gas Volume', 'Total Steam', 'Total Fuel Used'):
                    rate_field = {'Total Volume': 'Flow Rate', 'Total Gas Volume': 'Gas Flow Rate',
                                  'Total Steam': 'Steam Flow Rate', 'Total Fuel Used': 'Fuel Consumption Rate'}[field]
                    counters[field] += data.get(rate_field, 10) * hours
                    data[field] = round(counters[field], 2)
                elif field in ('Gas Pressure', 'Pressure'):
                    data[field] = round(random.uniform(2.0, 5.0), 2)
                elif field == 'Steam Pressure':
                    data[field] = round(random.uniform(8.0, 12.0), 2)
                elif field == 'Temperature':
                    data[field] = round(26 + 6 * load + random.uniform(-1, 1), 1)
                elif field == 'Humidity':
                    data[field] = round(random.uniform(55, 80), 1)
                elif field == 'CO2 Level':
                    data[field] = round(420 + 300 * load + random.uniform(-20, 20), 1)
                elif field == 'PM2.5':
                    data[field] = round(random.uniform(20, 60), 1)
                elif field == 'PM10':
                    data[field] = round(random.uniform(40, 110), 1)
            yield MeterReading(meter=meter, timestamp=ts, data=data)
            ts += interval
