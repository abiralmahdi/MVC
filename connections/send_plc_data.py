import snap7
from snap7.util import get_int, get_bool, set_bool, set_int
from snap7.type import Areas
import time

# ---------------- PLC CONFIG ----------------
PLC_IP = '192.168.0.66'
RACK = 0
SLOT = 1
DB_NUMBER = 1
START_BYTE = 0
DATA_SIZE = 6  # 1 byte for BOOLs + 2 bytes (INT) + 2 bytes (INT) = 5, rounded to 6 for safety

# ---------------- LOOP EVERY 5 MINUTES ----------------
while True:
    try:
        # --- Connect to PLC ---
        plc = snap7.client.Client()
        plc.connect(PLC_IP, RACK, SLOT)
        print("Connected:" + str(plc.get_connected()))

        if not plc.get_connected():
            print("❌ PLC not connected")
            time.sleep(300)
            continue

        # Read DB data
        data = plc.read_area(Areas.DB, DB_NUMBER, START_BYTE, DATA_SIZE)
        print("Data read")

        # --- Extract values ---
        i_motor_on = int(get_bool(data, 0, 4))  # DBX0.0
        i_motor_off = int(get_bool(data, 0, 5))  # DBX0.1
        level_l = int(get_bool(data, 0, 2))
        level_h = int(get_bool(data, 0, 3))
        motor = int(get_bool(data, 0, 6))  # DBX0.2
        speed = int(get_int(data, 2))     # DBW2
        speed_op = int(get_int(data, 4))     # DBW4

        # Print nicely
        time_str = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f"✅ {time_str} → Motor On: {i_motor_on}, Motor Off: {i_motor_off}, Bool3: {motor}, speed ip: {speed}, speed op: {speed_op}, levelLow: {level_l}, levelHigh: {level_h}")

        # --- Modify values to write back ---
        # Example: toggle bools and increment ints
        set_bool(data, 0, 4, True)   # Invert Bool1
        set_bool(data, 0, 5, False)   # Invert Bool1

        set_bool(data, 0, 2, False)
        set_bool(data, 0, 3, True)
        set_int(data, 2, speed + 1)      # Increment Int1
        set_int(data, 4, speed_op + 10)     # Increment Int2



        # --- Write back to PLC ---
        plc.write_area(Areas.DB, DB_NUMBER, START_BYTE, data)
        print("✅ Values written back to PLC")

        plc.disconnect()

    except Exception as e:
        print(f"❌ Error: {e}\n")

    # --- Wait for 5 minutes (300 seconds) ---
    time.sleep(5)
