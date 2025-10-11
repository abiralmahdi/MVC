from dynamic.models import Site, Buildings, Areas, LoadType, Meters, Measurements
import random
import string

# --- Site names: A, B, C ---
site_letters = list(string.ascii_uppercase)[:1]  # ['A', 'B', 'C']

sites = []
for letter in site_letters:
    site = Site.objects.create(name=f"Site {letter}")
    sites.append((letter, site))

# --- Load Types ---
load_types = []
for lt in ['Lighting', 'HVAC', 'Elevator', 'Pump', 'Server Rack']:
    load_type = LoadType.objects.create(name=lt)
    load_types.append(load_type)

# --- Meter type -> measurement names ---
meter_measurements = {
    'Electricity Meter': [
        "Timestamp", "Voltage L1N", "Voltage L2N", "Voltage L3N",
        "Voltage L1-L2", "Voltage L2-L3", "Voltage L3-L1",
        "Current L1", "Current L2", "Current L3",
        "Apparent Power L1", "Apparent Power L2", "Apparent Power L3",
        "Total Apparent Power", "Energy",
        "Active Power L1", "Active Power L2", "Active Power L3",
        "Reactive Power L1", "Reactive Power L2", "Reactive Power L3",
        "Power Factor L1", "Power Factor L2", "Power Factor L3",
        "THD Voltage L1-L2", "THD Voltage L2-L3", "THD Voltage L3-L1",
        "Line Frequency", "3-Phase Average Voltage L-N",
        "3-Phase Average Voltage L-L", "3-Phase Average Current L-L",
        "Total Active Power", "Total Reactive Power", "Power Factor"
    ],
    'Water Meter': ["Timestamp", "Flow Rate", "Total Volume"],
    'Fuel Meter': ["Timestamp", "Fuel Consumption Rate", "Total Fuel Used"],
    'Gas Meter': ["Timestamp", "Gas Flow Rate", "Gas Pressure", "Total Gas Volume"],
    'Steam Meter': ["Timestamp", "Steam Flow Rate", "Steam Pressure", "Total Steam"],
    'Temperature': ["Timestamp", "Temperature"],
    'Pressure': ["Timestamp", "Pressure"],
    'Humidity': ["Timestamp", "Humidity"],
    'Air Quality': ["Timestamp", "CO2 Level", "PM2.5", "PM10"],
}

# --- Track created unique Measurements ---
created_measurements = {}

# --- Cache meters per type ---
type_to_meters = {}

building_count = 0
area_count = 0
meter_count = 0

for site_letter, site in sites:
    for b in range(1):  # (1, 3) for 3 buildings per site
        building_name = f"Building {site_letter}{b}"  # e.g., Building A1
        building = Buildings.objects.create(name=building_name, site=site)
        building_count += 1

        for a in range(1):  # 10 areas per building
            area_name = f"Area {site_letter}{b}-{a}"  # e.g., Area A1-1
            area = Areas.objects.create(name=area_name, building=building)
            area_count += 1

            for m in range(2):  # (1, 3) for 3 meters per area
                meter_type = random.choice(list(meter_measurements.keys()))
                # meter_type = 'Electricity Meter'
                meter_name = f"Meter {site_letter}{b}-{a}-{m}"  # e.g., Meter A1-1-1
                ip = f"192.168.{random.randint(0,255)}.{random.randint(1,254)}"
                load_type = random.choice(load_types)

                meter = Meters.objects.create(
                    name=meter_name,
                    ip=ip,
                    area=area,
                    loadType=load_type,
                    meterType=meter_type
                )
                meter_count += 1

                if meter_type not in type_to_meters:
                    type_to_meters[meter_type] = []
                type_to_meters[meter_type].append(meter)

                for m_name in meter_measurements[meter_type]:
                    if m_name not in created_measurements:
                        # Pick any available meter of this type to attach
                        any_meter = type_to_meters[meter_type][0]
                        m_obj = Measurements.objects.create(
                            name=m_name,
                            meter=any_meter,
                            meterType=meter_type
                        )
                        created_measurements[m_name] = m_obj

print(f"✅ Created: {len(sites)} sites, {building_count} buildings, {area_count} areas, {meter_count} meters, {len(created_measurements)} unique measurements")
