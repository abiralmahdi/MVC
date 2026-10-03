"""Create the standard Measurements (and their Units) for every meter (replaces measurementPopulation.py / unitPopulation.py)."""
from django.core.management.base import BaseCommand

from dashboard.measurements import MEASUREMENT_UNITS, METER_DEFINITIONS
from dynamic.models import Measurements, Meters, Units



class Command(BaseCommand):
    help = "Create missing Measurements/Units for each meter according to its meterType."

    def handle(self, *args, **options):
        created = units = skipped = 0
        for meter in Meters.objects.all():
            names = METER_DEFINITIONS.get((meter.meterType or '').strip())
            if not names:
                self.stdout.write(self.style.WARNING(f"Skipping {meter.name}: unknown meter type '{meter.meterType}'"))
                skipped += 1
                continue
            existing = set(Measurements.objects.filter(meter=meter).values_list('name', flat=True))
            for name in names:
                if name in existing:
                    continue
                measurement = Measurements.objects.create(name=name, meter=meter)
                created += 1
                if name in MEASUREMENT_UNITS:
                    Units.objects.create(name=MEASUREMENT_UNITS[name], measurement=measurement)
                    units += 1
        self.stdout.write(self.style.SUCCESS(
            f"Created {created} measurements and {units} units; skipped {skipped} meters."))
