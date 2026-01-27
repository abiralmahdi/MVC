
import socket
import struct
import time
import math
from datetime import datetime
from dashboard.models import LatestMeterReading, MeterReading

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
    prints the values and stores the data.
    """

    ip = meter.ip
    unit_id = meter.unit_id
    registers = meter.registerMapping or {}
    result = {label: None for label in registers.keys()}  # pre-fill all labels

    print(f"\n============================")
    print(f"🔌 Connecting to {meter.name} ({meter.meterType}) at {ip} [Unit ID: {unit_id}]")
    print(f"============================")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT)

    try:
        sock.connect((ip, PORT))
        print(f"✅ Connected successfully\n")

        transaction_id = 0

        for label, reg_info in registers.items():
            function_code, reg_addr = reg_info
            transaction_id = (transaction_id + 1) % 0xFFFF
            request = build_request(transaction_id, unit_id, function_code, reg_addr, 2)

            try:
                sock.sendall(request)
                response = sock.recv(1024)

                # Validate response
                if len(response) < 9:
                    print(f"⚠️  {label} (Addr {reg_addr}): Incomplete response")
                    continue

                # Modbus exception
                if response[7] & 0x80:
                    print(f"❌ {label} (Addr {reg_addr}): Exception Code {response[8]}")
                    continue

                value = parse_float_from_response(response)
                result[label] = round(value, 3)
                print(f"📊 {label}: {value:.3f}")

            except Exception as e:
                print(f"❌ {label} (Addr {reg_addr}): Error - {e}")
                continue

            time.sleep(0.1)  # brief delay between reads

    except Exception as e:
        print(f"❌ Could not connect to {meter.name} ({ip}): {e}")

    finally:
        sock.close()
        print("🔚 Connection closed.\n")

    # Sanitize all readings
    sanitized = sanitize_dict(result)

    # Store readings in the database
    try:
        MeterReading.objects.create(
            meter=meter,
            timestamp=datetime.now(),
            data=sanitized
        )
        LatestMeterReading.objects.create(
            meter=meter,
            timestamp=datetime.now(),
            data=sanitized
        )
        print(f"✅ Data saved for {meter.name}")
    except Exception as e:
        print(f"❌ Failed to save data for {meter.name}: {e}")

def main():
    """
    Reads all meters of type Selec EM306 (or any type)
    that are connected through Odot-S2E2 gateway.
    Only meters with unit_id == 2 will be read.
    """
    from dynamic.models import Meters

    meters = Meters.objects.all()

    if not meters.exists():
        print("⚠️  No meters found in database.")
        return

    for meter in meters:
        read_meter_data(meter)
        time.sleep(1)
