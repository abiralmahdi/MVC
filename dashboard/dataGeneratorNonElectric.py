import random
from datetime import datetime, timedelta
from tqdm import tqdm
from dashboard.models import MeterReading, LatestMeterReading
from dynamic.models import Meters

# Define your meters & their measurements
meter_definitions = {
    'Fuel Meter': ['Fuel Consumption Rate', 'Total Fuel Used'],
    'Gas Meter': ['Gas Flow Rate', 'Gas Pressure', 'Total Gas Volume'],
    'Humidity': ['Humidity'],
    'Pressure': ['Pressure'],
    'Steam Meter': ['Steam Flow Rate', 'Steam Pressure', 'Total Steam'],
    'Temperature': ['Temperature'],
    'Water Meter': ['Flow Rate', 'Total Volume'],
    'Air Quality': ['CO2 Level', 'PM2.5', 'PM10'],
}

# Config
start_time = datetime.strptime("02-07-25 00:00", "%d-%m-%y %H:%M")
num_entries = 144  # 1 day at 10-min intervals
interval = timedelta(minutes=10)

for meter_type, fields in meter_definitions.items():
    meters = Meters.objects.filter(meterType=meter_type)[:3]

    for meter in meters:
        current_time = start_time

        readings = []  # List for bulk insert

        # Set up cumulative values if needed
        cumulative = {}
        if 'Total Fuel Used' in fields:
            cumulative['Total Fuel Used'] = 100.0
        if 'Total Gas Volume' in fields:
            cumulative['Total Gas Volume'] = 500.0
        if 'Total Steam' in fields:
            cumulative['Total Steam'] = 1000.0
        if 'Total Volume' in fields:
            cumulative['Total Volume'] = 1000.0

        print(f"Generating data for {meter.name} ({meter_type})...")

        for _ in tqdm(range(num_entries), desc=f"{meter.name}"):
            data = {}

            for field in fields:
                if field == 'Fuel Consumption Rate':
                    # Instantaneous rate
                    data[field] = round(random.uniform(5.0, 10.0), 2)  # liters/hour
                elif field == 'Total Fuel Used':
                    # Add based on rate & interval
                    increment = data['Fuel Consumption Rate'] * (interval.total_seconds() / 3600.0)
                    cumulative['Total Fuel Used'] += increment
                    data[field] = round(cumulative['Total Fuel Used'], 2)
                elif field == 'Gas Flow Rate':
                    data[field] = round(random.uniform(50.0, 100.0), 2)  # m³/h
                elif field == 'Gas Pressure':
                    data[field] = round(random.uniform(2.0, 5.0), 2)  # bar
                elif field == 'Total Gas Volume':
                    increment = data.get('Gas Flow Rate', random.uniform(50.0, 100.0)) * (interval.total_seconds() / 3600.0)
                    cumulative['Total Gas Volume'] += increment
                    data[field] = round(cumulative['Total Gas Volume'], 2)
                elif field == 'Humidity':
                    data[field] = round(random.uniform(30.0, 70.0), 1)  # %
                elif field == 'Pressure':
                    data[field] = round(random.uniform(1.0, 10.0), 2)  # bar
                elif field == 'Steam Flow Rate':
                    data[field] = round(random.uniform(200.0, 500.0), 2)  # kg/h
                elif field == 'Steam Pressure':
                    data[field] = round(random.uniform(5.0, 15.0), 2)  # bar
                elif field == 'Total Steam':
                    increment = data.get('Steam Flow Rate', random.uniform(200.0, 500.0)) * (interval.total_seconds() / 3600.0)
                    cumulative['Total Steam'] += increment
                    data[field] = round(cumulative['Total Steam'], 2)
                elif field == 'Temperature':
                    data[field] = round(random.uniform(20.0, 100.0), 1)  # °C
                elif field == 'Flow Rate':
                    data[field] = round(random.uniform(10.0, 50.0), 2)  # m³/h
                elif field == 'Total Volume':
                    increment = data.get('Flow Rate', random.uniform(10.0, 50.0)) * (interval.total_seconds() / 3600.0)
                    cumulative['Total Volume'] += increment
                    data[field] = round(cumulative['Total Volume'], 2)
                elif field == 'CO2 Level':
                    data[field] = round(random.uniform(400, 800), 1)  # ppm
                elif field == 'PM2.5':
                    data[field] = round(random.uniform(5.0, 35.0), 1)  # µg/m³
                elif field == 'PM10':
                    data[field] = round(random.uniform(10.0, 50.0), 1)  # µg/m³

            readings.append(
                MeterReading(
                    meter=meter,
                    timestamp=current_time,
                    data=data
                )
            )

            current_time += interval

        # Bulk insert for speed 🚀
        LatestMeterReading.objects.bulk_create(readings, batch_size=1000)
        print(f"✅ Inserted {len(readings)} readings for {meter.name} ({meter_type})")

print("✅ All data generated & inserted successfully.")
