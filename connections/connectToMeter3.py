import socket
import struct
import time
import json

ip_address = '192.168.0.80'
port = 502
unit_id = 1
timeout = 2

# PAC4200 Input Register Map (Add or adjust as needed)
registers = {
    "Voltage L1-N": 1,
    "Voltage L2-N": 3,
    "Voltage L3-N": 5,
    "Voltage L1-L2": 7,
    "Voltage L2-L3": 9,
    "Voltage L3-L1": 11,
    "Current L1": 13,
    "Current L2": 15,
    "Current L3": 17,
    "Total Active Power": 19,
    "Total Apparent Power": 21,
    "Total Reactive Power": 23,
    "Total Power Factor": 25,
    "Line Frequency": 27,
    "Apparent Power L1": 29,
    "Apparent Power L2": 31,
    "Apparent Power L3": 33,
    "Active Power L1": 35,
    "Active Power L2": 37,
    "Active Power L3": 39,
    "Reactive Power L1": 41,
    "Reactive Power L2": 43,
    "Reactive Power L3": 45,
    "Power Factor L1": 47,
    "Power Factor L2": 49,
    "Power Factor L3": 51,
    "THD Voltage L1-L2": 53,
    "THD Voltage L2-L3": 55,
    "THD Voltage L3-L1": 57,
    "3-Phase Average Voltage L-N": 59,
    "3-Phase Average Voltage L-L": 61,
    "3-Phase Average Current L-L": 63,
    "Maximum Voltage L1-N": 65,
    "Maximum Voltage L2-N": 67,
    "Maximum Voltage L3-N": 69,
    "Maximum Voltage L1-L2": 71,
    "Maximum Voltage L2-L3": 73,
    "Maximum Voltage L3-L1": 75,
    "Maximum Current L1": 77,
    "Maximum Current L2": 79,
    "Maximum Current L3": 81,
    "Minimum Voltage L1-N": 83,
    "Minimum Voltage L2-N": 85,
    "Minimum Voltage L3-N": 87,
    "Minimum Voltage L1-L2": 89,
    "Minimum Voltage L2-L3": 91,
    "Minimum Voltage L3-L1": 93,
    "Minimum Current L1": 95,
    "Minimum Current L2": 97,
    "Minimum Current L3": 99,
    "Minimum Power Factor L1": 101,
    "Minimum Power Factor L2": 103,
    "Minimum Power Factor L3": 105,
}

def build_request(transaction_id, unit_id, function_code, address, count):
    # Modbus TCP: MBAP (7 bytes) + PDU (5 bytes)
    return struct.pack('>HHHBBHH',
                       transaction_id, 0x0000, 6, unit_id, function_code, address, count)

def parse_float_from_response(response):
    # Expecting at least 13 bytes: 7 (MBAP) + 1 (Function Code) + 1 (Byte Count) + 4 (Float)
    if len(response) >= 13:
        return struct.unpack('>f', response[9:13])[0]
    else:
        raise ValueError("Response too short to contain float")

def main():
    result = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)

    try:
        sock.connect((ip_address, port))
        print("✅ Connected to PAC4200\n")

        transaction_id = 0
        fc = 4  # Function Code 4: Input Registers

        for label, address in registers.items():
            transaction_id = (transaction_id + 1) % 0xFFFF
            request = build_request(transaction_id, unit_id, fc, address, 2)

            try:
                sock.sendall(request)
                response = sock.recv(1024)

                if len(response) < 9:
                    print(f"❌ {label} (Addr {address}): Incomplete response")
                    continue

                # Check for Modbus exception
                if response[7] & 0x80:
                    print(f"❌ {label} (Addr {address}): Exception Code {response[8]}")
                    continue

                value = parse_float_from_response(response)
                result[label] = round(value, 3)
                print(f"📊 {label} (Addr {address}): {value:.3f}")

            except Exception as e:
                print(f"❌ {label} (Addr {address}): Error - {e}")
                continue

            time.sleep(0.1)

    except Exception as e:
        print(f"❌ Could not connect to PAC4200 - {e}")

    finally:
        sock.close()
        print("\n🔌 Connection closed.")

    # Print final JSON output
    print("\n📦 Final JSON Output:")
    print(json.dumps(result, indent=4))

if __name__ == "__main__":
    main()
