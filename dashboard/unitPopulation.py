

from dynamic.models import Measurements, Units

# --- Define meter measurements ---
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
    'Steam': ["Timestamp", "Steam Flow Rate", "Steam Pressure", "Total Steam"],
    'Temperature': ["Timestamp", "Temperature"],
    'Pressure': ["Timestamp", "Pressure"],
    'Humidity': ["Timestamp", "Humidity"],
    'Air Meter': ["Timestamp", "CO2 Level", "PM2.5", "PM10"],
}

# --- Define measurement → unit mapping ---
measurement_units = {
    # Electricity
    "Voltage L1N": "V", "Voltage L2N": "V", "Voltage L3N": "V",
    "Voltage L1-L2": "V", "Voltage L2-L3": "V", "Voltage L3-L1": "V",
    "Current L1": "A", "Current L2": "A", "Current L3": "A",
    "Apparent Power L1": "VA", "Apparent Power L2": "VA", "Apparent Power L3": "VA",
    "Total Apparent Power": "kVA", "Energy": "kWh",
    "Active Power L1": "W", "Active Power L2": "W", "Active Power L3": "W",
    "Reactive Power L1": "VAR", "Reactive Power L2": "VAR", "Reactive Power L3": "VAR",
    "Total Active Power": "kW", "Total Reactive Power": "kVAR",
    "Power Factor L1": "PF", "Power Factor L2": "PF", "Power Factor L3": "PF",
    "Power Factor": "PF",
    "THD Voltage L1-L2": "%", "THD Voltage L2-L3": "%", "THD Voltage L3-L1": "%",
    "Line Frequency": "Hz", "3-Phase Average Voltage L-N": "V",
    "3-Phase Average Voltage L-L": "V", "3-Phase Average Current L-L": "A",

    # Water
    "Flow Rate": "L/min", "Total Volume": "L",

    # Fuel
    "Fuel Consumption Rate": "L/h", "Total Fuel Used": "L",

    # Gas
    "Gas Flow Rate": "m³/h", "Gas Pressure": "bar", "Total Gas Volume": "m³",

    # Steam
    "Steam Flow Rate": "kg/h", "Steam Pressure": "bar", "Total Steam": "kg",

    # Temperature
    "Temperature": "°C",

    # Pressure
    "Pressure": "bar",

    # Humidity
    "Humidity": "%",

    # Air
    "CO2 Level": "ppm", "PM2.5": "µg/m³", "PM10": "µg/m³",
}

# --- Populate Measurements and Units ---
created_measurements = 0
created_units = 0

for meter_type, measurements in meter_measurements.items():
    for measurement_name in measurements:
        if measurement_name == "Timestamp":
            continue  # skip timestamp fields

        measurement, m_created = Measurements.objects.get_or_create(
            name=measurement_name,
            defaults={'meter_type': meter_type}
        )

        if m_created:
            created_measurements += 1
            print(f"🆕 Created Measurement: {measurement_name} ({meter_type})")
        else:
            # Update meter type if mismatched
            if measurement.meter.meterType != meter_type:
                measurement.meter.meterType = meter_type
                measurement.save()
                print(f"🔁 Updated meter type for {measurement_name} → {meter_type}")

        # Create or update the corresponding unit
        unit_name = measurement_units.get(measurement_name)
        if unit_name:
            unit, u_created = Units.objects.get_or_create(
                measurement=measurement,
                defaults={'name': unit_name}
            )
            if not u_created and unit.name != unit_name:
                unit.name = unit_name
                unit.save()
                print(f"🔁 Updated Unit for {measurement_name}: {unit_name}")
            elif u_created:
                created_units += 1
                print(f"✅ Created Unit for {measurement_name}: {unit_name}")
        else:
            print(f"⚠️ No unit found for {measurement_name}, skipping...")

print("\nSummary:")
print(f"✅ {created_measurements} new measurements added.")
print(f"✅ {created_units} new units added.")
print("🎯 Population complete!")
