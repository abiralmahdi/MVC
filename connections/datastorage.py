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
    return struct.pack('>HHHBBHH',
                       transaction_id, 0x0000, 6, unit_id, function_code, address, count)

def parse_float_from_response(response):
    """Extract a 4-byte float value from Modbus response"""
    if len(response) >= 13:
        return struct.unpack('>f', response[9:13])[0]
    else:
        raise ValueError("Response too short to contain float")

def read_meter_data(meter):
    ip = meter.ip
    unit_id = meter.unit_id
    registers = meter.registerMapping or {}
    result = {label: None for label in registers.keys()}

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT)

    success = False

    try:
        sock.connect((ip, PORT))
        transaction_id = 0

        for label, reg_info in registers.items():
            function_code, reg_addr = reg_info
            transaction_id = (transaction_id + 1) % 0xFFFF
            request = build_request(transaction_id, unit_id, function_code, reg_addr, 2)
            try:
                sock.sendall(request)
                response = sock.recv(1024)
                if len(response) < 9 or response[7] & 0x80:
                    continue
                value = parse_float_from_response(response)
                result[label] = round(value, 3)
                success = True
            except:
                continue
            time.sleep(0.1)
    except:
        return False
    finally:
        sock.close()

    if success:
        sanitized = sanitize_dict(result)
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
        return True
    else:
        return False
    


from opcua import Client as OPCUAClient
import math
def read_meter_data_scada(meter):
    """
    Read data from SCADA (OPC UA – WinCC) and store in DB
    """
    ip = meter.ip
    port = 4862  # optional port field
    node_map = meter.registerMapping or {}

    if not node_map:
        print(f"⚠️ No OPC UA nodes defined for meter {meter.name}")
        return False

    url = f"opc.tcp://{ip}:{port}"
    client = OPCUAClient(url)

    result = {label: None for label in node_map.keys()} 
    success = False

    try:
        client.connect()
        print(f"🔗 Connected to OPC UA SCADA ({meter.name})")

        for label, nodeid in node_map.items():
            try:
                node = client.get_node(nodeid)
                value = node.get_value()

                if isinstance(value, (int, float)):
                    if math.isnan(value) or math.isinf(value):
                        value = None
                    else:
                        value = round(float(value), 3)

                result[label] = value
                success = True

            except Exception as e:
                print(f"❌ OPC UA read failed [{meter.name} | {label}]: {e}")
                continue

    except Exception as e:
        print(f"❌ OPC UA connection failed for {meter.name}: {e}")
        return False

    finally:
        try:
            client.disconnect()
        except:
            pass
    print(result)

    if success:
        try:
            MeterReading.objects.create(
                meter=meter,
                timestamp=datetime.now(),
                data=result
            )
            LatestMeterReading.objects.create(
                meter=meter,
                timestamp=datetime.now(),
                data=result
            )
            print(f"✅ SCADA data saved for {meter.name}")
            return True

        except Exception as e:
            print(f"❌ Failed to save SCADA data for {meter.name}: {e}")
            return False

    return False


def read_meter_data_all(meter):
    read_meter_data_scada(meter)
    read_meter_data(meter)


def main():
    from dynamic.models import Meters

    meters = Meters.objects.all()
    if not meters.exists():
        print("⚠️  No meters found in database.")
        return

    for meter in meters:
        if meter.isScada:
            stored = read_meter_data_scada(meter)
            if stored:
                print(f"Success: Data stored for meter '{meter.name}'")
            else:
                print(f"Skipped or failed meter '{meter.name}'")
            time.sleep(1)    
        else:
            stored = read_meter_data(meter)
            if stored:
                print(f"Success: Data stored for meter '{meter.name}'")
            else:
                print(f"Skipped or failed meter '{meter.name}'")
            time.sleep(1)
