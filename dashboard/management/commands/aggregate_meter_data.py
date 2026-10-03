from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from connections.models import SystemJob
from dashboard.aggregation import run_hierarchy_aggregation, run_time_aggregation


class Command(BaseCommand):
    help = "Rebuild MeterReadingAggregate and HierarchyDataAggregate (normally done nightly by poll_modbus)."

    def add_arguments(self, parser):
        parser.add_argument('--since', help='Only rebuild periods touching this local date (YYYY-MM-DD). Default: full rebuild.')
        parser.add_argument('--skip-hierarchy', action='store_true')

    def handle(self, *args, **options):
        since = None
        if options['since']:
            try:
                since = date.fromisoformat(options['since'])
            except ValueError:
                raise CommandError('--since must be YYYY-MM-DD')

        written = run_time_aggregation(since=since)
        self.stdout.write(self.style.SUCCESS(f"Time aggregation: {written} rows"))
        if not options['skip_hierarchy']:
            written = run_hierarchy_aggregation(since=since)
            self.stdout.write(self.style.SUCCESS(f"Hierarchy aggregation: {written} rows"))
            SystemJob.objects.update_or_create(
                name="daily_time_and_hierarchy_aggregation", defaults={'last_run': timezone.now()}
            )
