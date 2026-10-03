"""Commissioning helper: read one meter and print the values without storing them."""
import json

from django.core.management.base import BaseCommand, CommandError

from connections import datastorage, drivers, protocols
from dynamic.models import Meters


class Command(BaseCommand):
    help = ("Read a meter once over its protocol (Modbus TCP, BACnet/IP, KNX, DALI, M-Bus, MQTT or OPC UA) "
            "and print the values. Use --store to save the reading.")

    def add_arguments(self, parser):
        parser.add_argument('meter', help='Meter id or exact name')
        parser.add_argument('--store', action='store_true', help='Also store the reading in the database.')
        parser.add_argument('--discover', action='store_true',
                            help='List what the device offers where the protocol supports it '
                                 '(M-Bus data records, MQTT topics).')

    def handle(self, *args, **options):
        key = options['meter']
        meter = Meters.objects.filter(pk=key).first() if key.isdigit() else None
        meter = meter or Meters.objects.filter(name=key).first()
        if meter is None:
            raise CommandError(f"Meter '{key}' not found")

        self.stdout.write(f"{meter.name} - {protocols.label(meter.protocol)} @ {meter.address_summary}")
        host, connection, errors = protocols.clean_connection(meter.protocol, meter.ip, meter.connection)
        for error in errors:
            self.stdout.write(self.style.ERROR(f"  connection: {error}"))
        points, point_errors = protocols.clean_mapping(meter.protocol, meter.registerMapping or {})
        for label, point in points.items():
            self.stdout.write(f"  {label}: {protocols.describe_point(meter.protocol, point)}")
        for error in point_errors:
            self.stdout.write(self.style.ERROR(f"  invalid {error}"))

        if options['discover']:
            found, discover_errors = drivers.discover(meter.protocol, meter.ip, {**meter.connection, '_one_shot': True})
            if found is None and not discover_errors:
                self.stdout.write(self.style.WARNING("  this protocol has no discovery"))
            for item in found or []:
                self.stdout.write(f"  found {json.dumps(item, default=str)}")
            for error in discover_errors:
                self.stdout.write(self.style.WARNING(f"  {error}"))

        result = datastorage.poll_meter(meter, one_shot=not options['store'])
        self.stdout.write(json.dumps(result.data, indent=2, default=str))
        for error in result.errors:
            self.stdout.write(self.style.WARNING(f"  {error}"))
        if options['store']:
            stored = datastorage.store_poll_result(meter, result)
            self.stdout.write(self.style.SUCCESS("Stored") if stored else self.style.ERROR("Nothing stored"))
