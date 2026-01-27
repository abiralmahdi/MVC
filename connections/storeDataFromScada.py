from opcua import Client
import time

def main():
    url = "opc.tcp://192.168.0.70:4862"
    client = Client(url)

    try:
        client.connect()
        print("Connected to WinCC OPC UA")

        # Use exact ID from OPC Scout table
        nodes = {
            "Voltage_L1": 'ns=1;s=t|Voltage_L1',
            "Voltage_L2": 'ns=1;s=t|Voltage_L2',
            "Voltage_L3": 'ns=1;s=t|Voltage_L3',
            "Frequency":  'ns=1;s=t|Frequency'
        }

        while True:
            for name, nodeid in nodes.items():
                node = client.get_node(nodeid)
                value = node.get_value()  # synchronous version of read_value()
                print(f"{name}: {value}")
            time.sleep(3)

    except Exception as e:
        print("Error:", e)

    finally:
        client.disconnect()
        print("Disconnected from WinCC OPC UA")


main()
