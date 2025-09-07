import random
from datetime import datetime, timedelta
from tqdm import tqdm
from dashboard.models import LatestMeterReading
from dynamic.models import Meters

# ========================
# ⚡ Power Meter Generator
# ========================
def generate_power_meter_data(meter, start_time, num_entries, interval):
    # Cumulative counters
    total_active_power = 1000.0
    total_reactive_power = 100.0

    current_time = start_time
    for _ in tqdm(range(num_entries), desc=f"{meter.name} (Power)"):
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
        }

        reading = LatestMeterReading(meter=meter, timestamp=current_time, data=data)
        reading.save()
        current_time += interval

    print(f"✅ Inserted {num_entries} readings for {meter.name} (Power)")


# ======================================
# 🌍 Environmental/Utility Meter Generator
# ======================================
def generate_other_meter_data(meter, meter_type, fields, start_time, num_entries, interval):
    cumulative = {}

    # Initialize cumulative fields
    if 'Total Fuel Used' in fields:
        cumulative['Total Fuel Used'] = 100.0
    if 'Total Gas Volume' in fields:
        cumulative['Total Gas Volume'] = 500.0
    if 'Total Steam' in fields:
        cumulative['Total Steam'] = 1000.0
    if 'Total Volume' in fields:
        cumulative['Total Volume'] = 1000.0

    current_time = start_time
    for _ in tqdm(range(num_entries), desc=f"{meter.name} ({meter_type})"):
        data = {}

        for field in fields:
            if field == 'Fuel Consumption Rate':
                data[field] = round(random.uniform(5.0, 10.0), 2)
            elif field == 'Total Fuel Used':
                increment = data['Fuel Consumption Rate'] * (interval.total_seconds() / 3600.0)
                cumulative['Total Fuel Used'] += increment
                data[field] = round(cumulative['Total Fuel Used'], 2)
            elif field == 'Gas Flow Rate':
                data[field] = round(random.uniform(50.0, 100.0), 2)
            elif field == 'Gas Pressure':
                data[field] = round(random.uniform(2.0, 5.0), 2)
            elif field == 'Total Gas Volume':
                increment = data.get('Gas Flow Rate', random.uniform(50.0, 100.0)) * (interval.total_seconds() / 3600.0)
                cumulative['Total Gas Volume'] += increment
                data[field] = round(cumulative['Total Gas Volume'], 2)
            elif field == 'Humidity':
                data[field] = round(random.uniform(30.0, 70.0), 1)
            elif field == 'Pressure':
                data[field] = round(random.uniform(1.0, 10.0), 2)
            elif field == 'Steam Flow Rate':
                data[field] = round(random.uniform(200.0, 500.0), 2)
            elif field == 'Steam Pressure':
                data[field] = round(random.uniform(5.0, 15.0), 2)
            elif field == 'Total Steam':
                increment = data.get('Steam Flow Rate', random.uniform(200.0, 500.0)) * (interval.total_seconds() / 3600.0)
                cumulative['Total Steam'] += increment
                data[field] = round(cumulative['Total Steam'], 2)
            elif field == 'Temperature':
                data[field] = round(random.uniform(20.0, 100.0), 1)
            elif field == 'Flow Rate':
                data[field] = round(random.uniform(10.0, 50.0), 2)
            elif field == 'Total Volume':
                increment = data.get('Flow Rate', random.uniform(10.0, 50.0)) * (interval.total_seconds() / 3600.0)
                cumulative['Total Volume'] += increment
                data[field] = round(cumulative['Total Volume'], 2)
            elif field == 'CO2 Level':
                data[field] = round(random.uniform(400, 800), 1)
            elif field == 'PM2.5':
                data[field] = round(random.uniform(5.0, 35.0), 1)
            elif field == 'PM10':
                data[field] = round(random.uniform(10.0, 50.0), 1)

        reading = LatestMeterReading(meter=meter, timestamp=current_time, data=data)
        reading.save()
        current_time += interval

    print(f"✅ Inserted {num_entries} readings for {meter.name} ({meter_type})")


# ===================
# 🚀 Main Controller
# ===================
if __name__ == "__main__":
    # Config
    start_time = datetime.strptime("06-09-25 00:00", "%d-%m-%y %H:%M")
    num_entries = 144  # 1 day of 10-min interval
    interval = timedelta(minutes=10)

    # Loop through all Power Meters (limit to first 3 if you want)
    power_meters = Meters.objects.filter(meterType="Electricity Meter") #[:3]
    for meter in power_meters:
        generate_power_meter_data(meter, start_time, num_entries, interval)

    # Other types
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

    for meter_type, fields in meter_definitions.items():
        meters = Meters.objects.filter(meterType=meter_type) #[:3]
        for meter in meters:
            generate_other_meter_data(meter, meter_type, fields, start_time, num_entries, interval)

    print("🎉 All meter data generated successfully.")
