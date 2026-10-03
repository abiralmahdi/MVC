from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ml.demo import DEMO_DATA_SIZE, DEMO_FIELDS, generate_motor_telemetry
from ml.models import MotorReading
from scada.models import Motor


class Command(BaseCommand):
    help = "Demo only: generate hourly motor telemetry (one motor with a developing bearing fault)."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=45)
        parser.add_argument('--degrading', help='Motor name that develops a fault (default: the second motor).')
        parser.add_argument('--add-fields', action='store_true',
                            help='Also add winding temperature and vibration fields to motors that lack them.')
        parser.add_argument('--replace', action='store_true', help='Delete existing readings in the window first.')

    def handle(self, *args, **options):
        motors = list(Motor.objects.order_by('id'))
        if not motors:
            raise CommandError('No motors configured.')
        if options['add_fields']:
            for motor in motors:
                fields = dict(motor.fields or {})
                if all(name not in fields for name in ('Winding temperature (°C)', 'Vibration (mm/s)')):
                    fields.update({k: v for k, v in DEMO_FIELDS.items() if k not in fields})
                    motor.fields = fields
                    motor.dataSize = max(motor.dataSize or 0, DEMO_DATA_SIZE)
                    motor.save(update_fields=['fields', 'dataSize'])
        degrading = next((m for m in motors if m.motorName == options['degrading']), None) if options['degrading'] else (motors[1] if len(motors) > 1 else motors[0])
        warming = motors[2] if len(motors) > 2 else None
        if options['replace']:
            MotorReading.objects.filter(timestamp__gte=timezone.now() - timedelta(days=options['days'] + 1)).delete()
        created = generate_motor_telemetry(motors, days=options['days'], degrading=degrading, warming=warming)
        self.stdout.write(self.style.SUCCESS(f'Created {created} motor readings; developing fault on "{degrading.motorName}".'))
