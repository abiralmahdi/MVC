import snap7
from snap7.util import get_real, get_dint, get_bool
from snap7.type import Areas
import time

# ---------------- PLC CONFIG ----------------
PLC_IP = '192.168.0.66'
RACK = 0
SLOT = 1
DB_NUMBER = 1
START_BYTE = 0
DATA_SIZE = 21  # 3 REALs (12 bytes) + 2 DINTs (8 bytes) + 1 BOOL byte

# ---------------- LOOP EVERY 5 MINUTES ----------------
while True:
    try:
        # --- Connect and Read from PLC ---
        plc = snap7.client.Client()
        plc.connect(PLC_IP, RACK, SLOT)
        print("Connected:"+str(plc.get_connected()))

        if not plc.get_connected():
            print("❌ PLC not connected")
            time.sleep(300)
            continue
        print(Areas.DB)
        data = plc.read_area(Areas.DB, DB_NUMBER, START_BYTE, DATA_SIZE)

        i_rTemperature = round(float(get_real(data, 0)), 2)
        i_rPressure = round(float(get_real(data, 4)), 2)
        i_rFlow = round(float(get_real(data, 8)), 2)
        i_dipH = int(get_dint(data, 12))
        i_diHumidity = int(get_dint(data, 16))
        i_xMotorRun = int(get_bool(data, 20, 0))  # Byte 20, Bit 0
        i_xMotorTrip = int(get_bool(data, 20, 1))  # Byte 20, Bit 1

        time_str = time.strftime('%Y-%m-%d %H:%M:%S')
        print(f"✅ {time_str} → Temp: {i_rTemperature}, Pressure: {i_rPressure}, Flow: {i_rFlow}, pH: {i_dipH}, Humidity: {i_diHumidity}, Run: {i_xMotorRun}, Trip: {i_xMotorTrip}")

        plc.disconnect()


    except Exception as e:
        print(f"❌ Error: {e}\n")

    # --- Wait for 5 minutes (300 seconds) ---
    time.sleep(60)
