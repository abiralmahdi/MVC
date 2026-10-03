from django.core.management.base import BaseCommand

from ml.scoring import latest_run, score_devices


class Command(BaseCommand):
    help = "Score every meter and motor with the latest trained predictive-maintenance models."

    def handle(self, *args, **options):
        run = latest_run()
        if run is None:
            self.stdout.write(self.style.WARNING('No completed training run yet: devices are marked "no trained model".'))
        results = score_devices(run=run)
        for health in results:
            device = health.meter or health.motor
            self.stdout.write(f"{device}: {health.status} risk={health.risk} p7d={health.failure_probability} "
                              f"days={health.days_to_maintenance} mode={health.failure_mode!r}")
