import random
from datetime import datetime, timedelta
from tqdm import tqdm
from dashboard.models import *
from dynamic.models import Meters

# Get the meter instance
meter, _ = Meters.objects.get_or_create(name="Meter A1-2-3")

# Starting timestamp
start_time = datetime.strptime("03-05-25 00:00", "%d-%m-%y %H:%M")

# Number of entries to generate
num_entries = 13140  # 105120 for 2 year at 10-minute intervals, or 144 for daily. 13140 for 3 month

current_time = start_time

# Realistic starting counters for cumulative power
total_active_power = 1000.0  # e.g., kWh counter
total_reactive_power = 100.0

# List to hold objects for bulk creation
readings_to_create = []

for _ in tqdm(range(num_entries), desc="Generating readings"):
    # Small realistic deltas
    active_increment = round(random.uniform(1.5, 3.5), 3)
    reactive_increment = round(random.uniform(0.2, 0.5), 3)

    total_active_power += active_increment
    total_reactive_power += reactive_increment

    data = {
        "Voltage L1-N": round(random.uniform(229, 231), 1),
        "Voltage L2-N": round(random.uniform(229, 231), 1),
        "Voltage L3-N": round(random.uniform(229.5, 231.5), 1),
        "Voltage L1-L2": round(random.uniform(398, 401), 1),
        "Voltage L2-L3": round(random.uniform(398, 401), 1),
        "Voltage L3-L1": round(random.uniform(398, 401), 1),

        "Current L1": round(random.uniform(11.5, 12.5), 1),
        "Current L2": round(random.uniform(11.5, 12.5), 1),
        "Current L3": round(random.uniform(11.5, 12.5), 1),

        "Apparent Power L1": round(random.uniform(3.0, 3.5), 1),
        "Apparent Power L2": round(random.uniform(3.0, 3.5), 1),
        "Apparent Power L3": round(random.uniform(3.0, 3.5), 1),

        "Active Power L1": round(random.uniform(2.7, 3.0), 1),
        "Active Power L2": round(random.uniform(2.7, 3.0), 1),
        "Active Power L3": round(random.uniform(2.7, 3.0), 1),

        "Reactive Power L1": round(random.uniform(0.3, 0.6), 1),
        "Reactive Power L2": round(random.uniform(0.3, 0.6), 1),
        "Reactive Power L3": round(random.uniform(0.3, 0.6), 1),

        "Power Factor L1": round(random.uniform(0.96, 0.99), 2),
        "Power Factor L2": round(random.uniform(0.96, 0.99), 2),
        "Power Factor L3": round(random.uniform(0.96, 0.99), 2),

        "THD Voltage L1-L2": round(random.uniform(3.5, 5.0), 2),
        "THD Voltage L2-L3": round(random.uniform(3.5, 5.0), 2),
        "THD Voltage L3-L1": round(random.uniform(3.5, 5.0), 2),

        "Line Frequency": round(random.uniform(49.95, 50.05), 2),
        "3-Phase Average Voltage L-N": round(random.uniform(229, 231), 1),
        "3-Phase Average Voltage L-L": round(random.uniform(398, 401), 1),
        "3-Phase Average Current L-L": round(random.uniform(11.5, 12.5), 1),

        "Total Active Power": round(total_active_power, 3),
        "Total Reactive Power": round(total_reactive_power, 3),
        "Total Power Factor": round(random.uniform(0.96, 0.99), 2),

        "Maximum Voltage L1-N": round(random.uniform(230.0, 231.5), 1),
        "Maximum Voltage L2-N": round(random.uniform(230.0, 231.5), 1),
        "Maximum Voltage L3-N": round(random.uniform(230.0, 231.5), 1),
        "Maximum Voltage L1-L2": round(random.uniform(399, 401), 1),
        "Maximum Voltage L2-L3": round(random.uniform(399, 401), 1),
        "Maximum Voltage L3-L1": round(random.uniform(399, 401), 1),

        "Maximum Current L1": round(random.uniform(12.0, 12.5), 1),
        "Maximum Current L2": round(random.uniform(12.0, 12.5), 1),
        "Maximum Current L3": round(random.uniform(12.0, 12.5), 1), 

        "Minimum Voltage L1-N": round(random.uniform(229, 230.0), 1),
        "Minimum Voltage L2-N": round(random.uniform(229, 230.0), 1),
        "Minimum Voltage L3-N": round(random.uniform(229.5, 230.5), 1),
        "Minimum Voltage L1-L2": round(random.uniform(398, 399), 1),
        "Minimum Voltage L2-L3": round(random.uniform(398, 399), 1),
        "Minimum Voltage L3-L1": round(random.uniform(398, 399), 1),

        "Minimum Current L1": round(random.uniform(11.5, 11.8), 1),
        "Minimum Current L2": round(random.uniform(11.5, 11.8), 1),
        "Minimum Current L3": round(random.uniform(11.5, 11.8), 1), 

        "Minimum Power Factor L1": round(random.uniform(0.96, 0.97), 2),
        "Minimum Power Factor L2": round(random.uniform(0.96, 0.97), 2),
        "Minimum Power Factor L3": round(random.uniform(0.96, 0.97), 2), 
    }

    # Create an instance but DO NOT save it yet
    reading_instance = MeterReading(
        meter=meter,
        timestamp=current_time,
        data=data
    )
    readings_to_create.append(reading_instance)

    # Advance time
    current_time += timedelta(minutes=10)

# Finally, save all the objects in one go
print("Saving all records with bulk_create...")
MeterReading.objects.bulk_create(readings_to_create)
print(f"Successfully created {len(readings_to_create)} new records.")