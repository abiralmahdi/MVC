
from dynamic.models import Meters, Measurements

# ---- YOUR MAPPING ----
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

# ---- MAIN LOGIC ----
def populate_measurements():
    created_count = 0
    skipped_count = 0

    for meter in Meters.objects.all():
        meter_type = meter.meterType.strip()

        if meter_type not in meter_measurements:
            print(f"⚠️ Skipping '{meter.name}' — Unknown meter type: '{meter_type}'")
            skipped_count += 1
            continue

        existing_measurements = set(
            Measurements.objects.filter(meter=meter).values_list("name", flat=True)
        )

        for measurement_name in meter_measurements[meter_type]:
            if measurement_name not in existing_measurements:
                Measurements.objects.create(
                    name=measurement_name,
                    meter=meter,
                    meterType=meter_type,
                )
                created_count += 1

        print(f"✅ Populated measurements for {meter.name} ({meter_type})")

    print(f"\n🎯 Done! Created {created_count} new measurements. Skipped {skipped_count} meters.")


if __name__ == "__main__":
    populate_measurements()