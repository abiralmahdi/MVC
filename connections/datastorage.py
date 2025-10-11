import socket
import struct
import time
import math
import json
from datetime import datetime
from dashboard.models import LatestMeterReading, MeterReading
from dynamic.models import Meters


PORT = 502
TIMEOUT = 2


def sanitize_dict(d):
    """Replace invalid float values (NaN, inf) with None"""
    for k, v in d.items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            d[k] = None
    return d


def build_request(transaction_id, unit_id, function_code, address, count):
    """Build Modbus TCP request packet"""
    # MBAP header (7 bytes) + PDU (5 bytes)
    return struct.pack('>HHHBBHH',
                       transaction_id, 0x0000, 6, unit_id, function_code, address, count)


def parse_float_from_response(response):
    """Extract a 4-byte float value from Modbus response"""
    if len(response) >= 13:
        return struct.unpack('>f', response[9:13])[0]
    else:
        raise ValueError("Response too short to contain float")


def read_meter_data(meter):
    """
    Connects to the meter via Modbus TCP,
    reads all registers from its registerMapping,
    and saves the latest reading to the database.
    """
    ip = meter.ip
    unit_id = meter.unit_id
    registers = meter.registerMapping or {}
    result = {}

    print(f"\n============================")
    print(f"🔌 Connecting to {meter.name} ({meter.meterType}) at {ip} [Unit ID: {unit_id}]")
    print(f"============================")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT)

    try:
        sock.connect((ip, PORT))
        print(f"✅ Connected successfully\n")

        transaction_id = 0
        function_code = 4  # Input Registers (read-only values)

        for label, address in registers.items():
            transaction_id = (transaction_id + 1) % 0xFFFF
            request = build_request(transaction_id, unit_id, function_code, address, 2)

            try:
                sock.sendall(request)
                response = sock.recv(1024)

                # Validate response
                if len(response) < 9:
                    print(f"⚠️  {label} (Addr {address}): Incomplete response")
                    continue

                # Modbus exception
                if response[7] & 0x80:
                    print(f"❌ {label} (Addr {address}): Exception Code {response[8]}")
                    continue

                value = parse_float_from_response(response)
                result[label] = round(value, 3)
                # print(f"📊 {label}: {value:.3f}")

            except Exception as e:
                print(f"❌ {label} (Addr {address}): Error - {e}")
                continue

            time.sleep(0.1)  # brief delay between reads

    except Exception as e:
        print(f"❌ Could not connect to {meter.name} ({ip}): {e}")

    finally:
        sock.close()
        print("🔚 Connection closed.\n")

    if result:
        # Clean and store result
        sanitized = sanitize_dict(result)
        LatestMeterReading.objects.create(
            meter=meter,
            timestamp=datetime.now(),
            data=sanitized
        )

        MeterReading.objects.create(
            meter=meter,
            timestamp=datetime.now(),
            data=sanitized
        )

        print(f"✅ Data saved for {meter.name}")
    else:
        print(f"⚠️  No valid data read from {meter.name}")


def main():
    """
    Reads all meters of type Selec EM306 (or any type)
    that are connected through Odot-S2E2 gateway.
    """
    # Fetch all meters (or filter by type)
    meters = Meters.objects.all()

    if not meters.exists():
        print("⚠️  No Selec EM306 meters found in database.")
        return

    for meter in meters:
        read_meter_data(meter)
        time.sleep(1)  # wait briefly before moving to the next meter


# if __name__ == "__main__":
#     main()
