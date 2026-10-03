"""One-off repair for readings stored before the time-zone fix.

The old poller saved naive ``datetime.now()`` (plant local time) while Django
treated it as UTC, so those timestamps are ahead of real UTC by the plant's
UTC offset (+6 h for Asia/Dhaka). Run this ONCE, with --before set to the
moment the fixed poller was started, e.g.:

    python manage.py fix_reading_timezone --before "2026-09-14 15:00" --dry-run
    python manage.py fix_reading_timezone --before "2026-09-14 15:00"
"""
from datetime import datetime, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from connections.models import SystemJob
from dashboard.models import LatestMeterReading, MeterReading

JOB_NAME = 'fix_reading_timezone'


class Command(BaseCommand):
    help = "Shift readings saved with local wall-clock time back to real UTC (run once)."

    def add_arguments(self, parser):
        parser.add_argument('--before', required=True, help='Local date-time "YYYY-MM-DD HH:MM"; only older readings are shifted.')
        parser.add_argument('--hours', type=float, help='Offset to subtract. Default: current UTC offset of TIME_ZONE.')
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--force', action='store_true', help='Run even if it was already applied.')

    def handle(self, *args, **options):
        try:
            before = timezone.make_aware(datetime.strptime(options['before'], '%Y-%m-%d %H:%M'))
        except ValueError:
            raise CommandError('--before must look like "2026-09-14 15:00"')
        hours = options['hours']
        if hours is None:
            hours = timezone.localtime().utcoffset().total_seconds() / 3600
        offset = timedelta(hours=hours)

        if SystemJob.objects.filter(name=JOB_NAME, last_run__isnull=False).exists() and not options['force']:
            raise CommandError('This repair was already applied. Use --force to run it again.')

        # The stored values are "local time labelled as UTC", so compare against before + offset.
        cutoff = before + offset
        readings = MeterReading.objects.filter(timestamp__lt=cutoff)
        latest = LatestMeterReading.objects.filter(timestamp__lt=cutoff)
        self.stdout.write(f"Shifting {readings.count()} readings and {latest.count()} latest snapshots by -{hours} h")
        if options['dry_run']:
            return

        with transaction.atomic():
            for model_qs in (readings, latest):
                for obj in model_qs.only('id', 'timestamp').iterator(chunk_size=2000):
                    type(obj).objects.filter(pk=obj.pk).update(timestamp=obj.timestamp - offset)
            SystemJob.objects.update_or_create(name=JOB_NAME, defaults={'last_run': timezone.now()})
        self.stdout.write(self.style.SUCCESS('Done. Re-run "manage.py aggregate_meter_data" to rebuild aggregates.'))
