import socket
import struct
import time

ip_address = '192.168.0.80'
port = 502
unit_id = 1
timeout = 2

def build_request(transaction_id, unit_id, function_code, address, count):
    return struct.pack('>HHHBBHH',
                       transaction_id, 0x0000, 6, unit_id, function_code, address, count)

def is_exception(response):
    if len(response) < 9:
        return True
    function_code = response[7]
    return (function_code & 0x80) != 0  # MSB set means exception

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    print(f"Connecting to {ip_address}:{port} ...")
    sock.connect((ip_address, port))
    print("Connected.\n")

    transaction_id = 0

    for fc in [3, 4]:
        print(f"Scanning Function Code {fc} (", end="")
        print("Holding Registers" if fc == 3 else "Input Registers", end=") ...\n")

        for addr in range(0, 50):
            transaction_id = (transaction_id + 1) % 0xFFFF
            request = build_request(transaction_id, unit_id, fc, addr, 2)

            try:
                sock.sendall(request)
                response = sock.recv(1024)

                if is_exception(response):
                    # Exception response; ignore
                    continue

                # If we got here, it’s a valid response:
                print(f"  Address {addr}: OK")

            except socket.timeout:
                print(f"  Address {addr}: Timeout")
            except Exception as e:
                print(f"  Address {addr}: Error - {e}")

            time.sleep(0.1)  # small delay between requests to avoid flooding

        print()

    sock.close()
    print("Scan complete. Connection closed.")

if __name__ == "__main__":
    main()
