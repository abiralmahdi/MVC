import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from connections import datastorage
from connections.models import SystemJob
from dynamic.models import Meters

logger = logging.getLogger('connections')

JOB_NAME = "daily_time_and_hierarchy_aggregation"
AGGREGATION_RETRY_SECONDS = 30 * 60


class Command(BaseCommand):
    help = 'Poll all meters over their protocols (Modbus TCP, BACnet/IP, KNX, DALI, M-Bus, MQTT, OPC UA) continuously and run the aggregations once a day after local midnight.'

    def add_arguments(self, parser):
        parser.add_argument('--interval', type=float, default=15.0, help='Seconds between polling cycles (default 15).')
        parser.add_argument('--workers', type=int, default=20, help='Parallel meter connections (default 20).')
        parser.add_argument('--once', action='store_true', help='Run a single polling cycle and exit.')
        parser.add_argument('--no-aggregation', action='store_true', help='Never run the nightly aggregations.')

    _next_aggregation_attempt = 0.0

    def handle(self, *args, **options):
        job, _ = SystemJob.objects.get_or_create(name=JOB_NAME)

        while True:
            loop_start = time.time()
            close_old_connections()

            stored, failed = self.poll_all(options['workers'])
            self.poll_motors()

            if not options['no_aggregation']:
                job.refresh_from_db()
                self.run_aggregations_if_due(job)

            elapsed = time.time() - loop_start
            logger.info("Cycle finished in %.2fs: %d stored, %d failed", elapsed, stored, failed)

            if options['once']:
                return
            time.sleep(max(0.0, options['interval'] - elapsed))

    def poll_all(self, workers):
        meters = {meter.id: meter for meter in Meters.objects.all()}
        if not meters:
            logger.warning("No meters configured.")
            return 0, 0

        stored = failed = 0
        with ThreadPoolExecutor(max_workers=max(1, min(workers, len(meters)))) as executor:
            futures = {executor.submit(datastorage.poll_meter, meter): meter for meter in meters.values()}
            for future in as_completed(futures):
                meter = futures[future]
                try:
                    result = future.result()
                except Exception:
                    logger.exception("Unexpected error while reading meter %s", meter.name)
                    failed += 1
                    continue
                # Database writes happen here, in the main thread only.
                try:
                    if datastorage.store_poll_result(meter, result):
                        stored += 1
                    else:
                        failed += 1
                except Exception:
                    logger.exception("Failed to store reading for meter %s", meter.name)
                    failed += 1
        return stored, failed

    def run_aggregations_if_due(self, job):
        """Run once per local day, at the first cycle after local midnight."""
        from dashboard.aggregation import run_hierarchy_aggregation, run_time_aggregation

        if time.time() < self._next_aggregation_attempt:
            return
        now = timezone.localtime()
        last_run = timezone.localtime(job.last_run) if job.last_run else None
        if last_run is not None and last_run.date() >= now.date():
            return

        since = last_run.date() if last_run else None
        logger.info("Starting daily aggregations (since=%s)", since)
        try:
            run_time_aggregation(since=since)
            run_hierarchy_aggregation(since=since)
        except Exception:
            logger.exception("Aggregation failed; retrying in %d minutes", AGGREGATION_RETRY_SECONDS // 60)
            self._next_aggregation_attempt = time.time() + AGGREGATION_RETRY_SECONDS
            return
        job.last_run = timezone.now()
        job.save(update_fields=["last_run"])
        logger.info("Daily aggregations completed")
        self.score_device_health()

    def poll_motors(self):
        """Store motor values from the PLCs (history for the predictive-maintenance model)."""
        from ml.telemetry import record_motor_readings

        try:
            stored, failed = record_motor_readings()
            if stored or failed:
                logger.info("Motors: %d stored, %d unreachable", stored, failed)
        except Exception:
            logger.exception("Motor telemetry failed")

    def score_device_health(self):
        """Refresh the predictive-maintenance scores once a day with the latest trained model."""
        from ml.scoring import latest_run, score_devices

        try:
            run = latest_run()
            if run is not None:
                results = score_devices(run=run)
                logger.info("Device health scored for %d devices", len(results))
        except Exception:
            logger.exception("Device health scoring failed")
