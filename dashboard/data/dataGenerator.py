import csv
from datetime import datetime, timedelta
import random

# Starting timestamp
start_time = datetime.strptime("17-06-25 00:00", "%d-%m-%y %H:%M")

# Output file
filename = "mfm3.csv"

# Column headers
headers = [
    "Timestamp",
    "Voltage_L1_V", "Voltage_L2_V", "Voltage_L3_V",
    "Current_L1_A", "Current_L2_A", "Current_L3_A",
    "Frequency_Hz", "PowerFactor",
    "ActivePower_kW", "ReactivePower_kVAR", "ApparentPower_kVA",
    "Energy_kWh"
]

# Initial energy value
energy = 13527.6

# Generate and write rows
with open(filename, mode="w", newline="") as file:
    writer = csv.writer(file)
    writer.writerow(headers)

    current_time = start_time

    for i in range(80640):
        # Simulate each parameter with small variations
        V1 = round(random.uniform(229, 231), 1)
        V2 = round(random.uniform(229, 231), 1)
        V3 = round(random.uniform(229.5, 231.5), 1)
        I1 = round(random.uniform(11.5, 12.5), 1)
        I2 = round(random.uniform(11.5, 12.5), 1)
        I3 = round(random.uniform(11.5, 12.5), 1)
        freq = round(random.uniform(49.95, 50.05), 2)
        pf = round(random.uniform(0.96, 0.99), 2)
        ap_kW = round(random.uniform(8.5, 9.0), 1)
        rp_kVAR = round(random.uniform(1.0, 1.3), 1)
        sp_kVA = round((ap_kW**2 + rp_kVAR**2)**0.5, 1)
        energy = round(energy + ap_kW / 60, 1)  # Add energy per minute

        row = [
            current_time.strftime("%d-%m-%y %H:%M"),
            V1, V2, V3,
            I1, I2, I3,
            freq, pf,
            ap_kW, rp_kVAR, sp_kVA,
            energy
        ]
        writer.writerow(row)

        # Increment timestamp by 1 minute
        current_time += timedelta(minutes=1)
