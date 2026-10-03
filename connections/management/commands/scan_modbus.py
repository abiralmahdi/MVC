"""Commissioning helper: find which register addresses a Modbus TCP device answers (replaces scanner.py)."""
from django.core.management.base import BaseCommand

from connections.modbus import ModbusError, ModbusTcpClient, decode_registers


class Command(BaseCommand):
    help = "Scan holding (fc3) and input (fc4) registers of a Modbus TCP device. Read-only."

    def add_arguments(self, parser):
        parser.add_argument('ip')
        parser.add_argument('--port', type=int, default=502)
        parser.add_argument('--unit', type=int, default=1)
        parser.add_argument('--start', type=int, default=0)
        parser.add_argument('--end', type=int, default=100)
        parser.add_argument('--fc', type=int, choices=[3, 4], action='append')

    def handle(self, *args, **options):
        codes = options['fc'] or [3, 4]
        with ModbusTcpClient(options['ip'], options['port'], options['unit'], timeout=2) as client:
            for fc in codes:
                self.stdout.write(f"Function code {fc}:")
                for address in range(options['start'], options['end']):
                    try:
                        payload = client.read_registers(fc, address, 2)
                    except ModbusError:
                        continue
                    except OSError as exc:
                        self.stdout.write(self.style.ERROR(f"  {address}: {exc}"))
                        break
                    self.stdout.write(f"  {address}: float32={decode_registers(payload, 'float32'):.3f} "
                                      f"uint16={decode_registers(payload, 'uint16')}")
