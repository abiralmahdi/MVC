import random
from datetime import datetime, timedelta
from tqdm import tqdm
from dynamic.models import Meters
from dashboard.models import MeterReading


def generate_meter_data(meter, start_time, num_entries, interval):
    """
    Generate synthetic power meter data for a single meter and insert into DB.
    """
    readings = []
    current_time = start_time

    for _ in tqdm(range(num_entries), desc=f"Generating data for {meter.name}"):
        data = {
            "Voltage L1N": round(random.uniform(229, 231), 1),
            "Voltage L2N": round(random.uniform(229, 231), 1),
            "Voltage L3N": round(random.uniform(229, 231), 1),
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
            "Power Factor": round(random.uniform(0.96, 0.99), 2),
            "THD Voltage L1-L2": round(random.uniform(3.5, 5.0), 2),
            "THD Voltage L2-L3": round(random.uniform(3.5, 5.0), 2),
            "THD Voltage L3-L1": round(random.uniform(3.5, 5.0), 2),
            "Line Frequency": round(random.uniform(49.95, 50.05), 2),
            "3-Phase Average Voltage L-N": round(random.uniform(229, 231), 1),
            "3-Phase Average Voltage L-L": round(random.uniform(398, 401), 1),
            "3-Phase Average Current L-L": round(random.uniform(11.5, 12.5), 1),
            "Total Active Power": round(random.uniform(1000, 1100), 3),
            "Total Reactive Power": round(random.uniform(100, 120), 3),
            "Total Apparent Power": round(random.uniform(1050, 1100), 3),
            "Energy": round(random.uniform(9.0, 12.0), 3)
        }

        readings.append(MeterReading(meter=meter, timestamp=current_time, data=data))
        current_time += interval

    # Bulk insert to speed up
    MeterReading.objects.bulk_create(readings, batch_size=1000)
    print(f"✅ Inserted {len(readings)} readings for {meter.name}")


if __name__ == "__main__":
    # Get your specific meter (example: mtr1)
    meter = Meters.objects.get(name="Electricity - 2")

    # Configurations
    start_time = datetime.strptime("01-01-2024 00:00", "%d-%m-%Y %H:%M")
    num_entries = 1440  # 1 day of 1-minute interval readings
    interval = timedelta(minutes=1)

    generate_meter_data(meter, start_time, num_entries, interval)

    print("🎉 Done generating sample readings for mtr1.")
