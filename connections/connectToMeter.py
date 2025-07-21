import socket
from django.utils import timezone

# TCP server info
TCP_IP = '175.29.127.27'
TCP_PORT = 4010
BUFFER_SIZE = 1024

# Create a TCP socket
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    print('Connecting ... ')
    s.connect((TCP_IP, TCP_PORT))
    print(f"Connected to {TCP_IP}:{TCP_PORT}")
    print(s.recv(BUFFER_SIZE))
    # while True:
    #     data = s.recv(BUFFER_SIZE)
    #     if not data:
    #         break  # connection closed

    #     decoded = data.decode('utf-8').strip()
    #     print(f"Received: {decoded}")

