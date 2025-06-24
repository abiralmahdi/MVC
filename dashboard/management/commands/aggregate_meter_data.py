# management/commands/aggregate_meter_data.py
from django.core.management.base import BaseCommand
from dashboard.models import MeterReading, MeterReadingAggregate, Meters
from django.db.models import Avg
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        period_configs = {
            # 'daily': lambda d: d.date(),
            # 'weekly': lambda d: d - timedelta(days=d.weekday()),
            'monthly': lambda d: d.replace(day=1).date(),
            # '3monthly': lambda d: d.replace(month=((d.month - 1) // 3 * 3 + 1), day=1).date(),
            # '6monthly': lambda d: d.replace(month=1 if d.month <= 6 else 7, day=1).date(),
            # 'yearly': lambda d: d.replace(month=1, day=1).date(),
        }

        for period, start_func in period_configs.items():
            readings = MeterReading.objects.all()
            aggregates = {}
            count = 0
            for reading in readings.iterator(chunk_size=10000):
                for k, v in reading.data.items():
                    key = (reading.meter_id, k, period, start_func(reading.timestamp))
                    aggregates.setdefault(key, []).append(v)
                    count += 1
                    print("Aggregate done for index-"+str(count))

            for (meter_id, measurement, period, start_date), values in aggregates.items():
                avg_value = sum(values) / len(values)
                MeterReadingAggregate.objects.update_or_create(
                    meter_id=meter_id,
                    measurement=measurement,
                    period_type=period,
                    start_date=start_date,
                    defaults={'average_value': avg_value}
                )
