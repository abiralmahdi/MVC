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
DATA_SIZE = 10  # 1 byte for BOOLs + 2 bytes (INT) + 2 bytes (INT) = 5, rounded to 6 for safety

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
        i_motor_on = int(get_bool(data, 6, 7)) 
        i_motor_off = int(get_bool(data, 7, 0)) 
        level_l = int(get_bool(data, 6, 5))
        level_h = int(get_bool(data, 6, 6))
        run = int(get_bool(data, 6, 4))  
        speed = int(get_int(data, 8))    
        value = int(get_int(data, 4))  
        trip = int(get_bool(data, 6, 2)) 

        # Print nicely
        time_str = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f"✅ {time_str} → Motor On: {i_motor_on}, Motor Off: {i_motor_off}, Run: {run}, speed ip: {speed}, levelLow: {level_l}, levelHigh: {level_h}, value: {value}, trip: {trip}")

        set_bool(data, 6, 2, True)
        # set_int(data, 4, 15) 

        # --- Write back to PLC ---
        plc.write_area(Areas.DB, DB_NUMBER, START_BYTE, data)
        print("✅ Values written back to PLC")

        plc.disconnect()
    except:
        print("===ERROR===")


    time.sleep(5)
