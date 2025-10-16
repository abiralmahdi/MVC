import pandas as pd
from tqdm import tqdm
from dashboard.models import MeterReading, MeterReadingAggregate, Meters

# Updated cumulative and meter type definitions
CUMULATIVE_FIELDS = {
    "Total Active Power",
    "Total Reactive Power",
    "Total Fuel Used",
    "Total Gas Volume",
    "Total Steam",
    "Total Volume",
    "Total Apparent Power", 
    "Energy"
}

METER_DEFINITIONS = {
    "Fuel Meter": ["Fuel Consumption Rate", "Total Fuel Used"],
    "Gas Meter": ["Gas Flow Rate", "Gas Pressure", "Total Gas Volume"],
    "Humidity": ["Humidity"],
    "Pressure": ["Pressure"],
    "Steam Meter": ["Steam Flow Rate", "Steam Pressure", "Total Steam"],
    "Temperature": ["Temperature"],
    "Water Meter": ["Flow Rate", "Total Volume"],
    "Air Quality": ["CO2 Level", "PM2.5", "PM10"],
    "Electricity Meter": [
        "Voltage L1N", "Voltage L2N", "Voltage L3N",
        "Voltage L1-L2", "Voltage L2-L3", "Voltage L3-L1",
        "Current L1", "Current L2", "Current L3",
        "Apparent Power L1", "Apparent Power L2", "Apparent Power L3",
        "Active Power L1", "Active Power L2", "Active Power L3",
        "Reactive Power L1", "Reactive Power L2", "Reactive Power L3",
        "Power Factor L1", "Power Factor L2", "Power Factor L3",
        "THD Voltage L1-L2", "THD Voltage L2-L3", "THD Voltage L3-L1",
        "Line Frequency", "3-Phase Average Voltage L-N", "3-Phase Average Voltage L-L",
        "3-Phase Average Current L-L", "Total Active Power",
        "Total Reactive Power", "Power Factor", "Total Apparent Power", "Energy",
            "Total kWh DG",
            "DG Sensing",
            "CT Secondary",
            "CT Primary",
            "PT Secondary",
            "PT Primary"
    ],
}

def queryset_to_df(queryset):
    data = []
    for reading in queryset:
        row = reading.data.copy()
        row['timestamp'] = reading.timestamp
        data.append(row)
    return pd.DataFrame(data)


def aggregate_meter_data():
    periods = {
        'weekly': 'W-MON',
        'monthly': 'MS',
        '3monthly': 'QS-JAN',
        '6monthly': '2QS-JAN',
        'yearly': 'YS',
    }

    # Loop over each meter type and take all meters
    meters = []
    for meter_type in METER_DEFINITIONS.keys():
        meters += list(Meters.objects.filter(meterType=meter_type))

    for meter in tqdm(meters, desc="Processing Meters"):
        readings = MeterReading.objects.filter(meter=meter).order_by("timestamp")
        if not readings.exists():
            continue

        df = queryset_to_df(readings)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)

        # Determine cumulative, rate, environmental, other fields dynamically
        meter_fields = METER_DEFINITIONS.get(meter.meterType, [])
        cumulative_fields = [f for f in meter_fields if f in CUMULATIVE_FIELDS]
        rate_fields = [f for f in meter_fields if f not in cumulative_fields and "Rate" in f]
        environmental_fields = [f for f in meter_fields if f in ["Humidity", "Temperature", "Pressure", "CO2 Level", "PM2.5", "PM10"]]
        other_fields = [f for f in meter_fields if f not in cumulative_fields + rate_fields + environmental_fields]

        for period_name, freq in periods.items():
            grouped = df.groupby(pd.Grouper(freq=freq))
            group_list = list(grouped)

            for start_date, group in tqdm(group_list, desc=f"{meter.name} - {period_name}", leave=False):
                if group.empty:
                    continue

                agg_data = {}

                # Cumulative fields → last - first
                for field in cumulative_fields:
                    if field in group.columns:
                        try:
                            agg_data[field] = round(group[field].iloc[-1] - group[field].iloc[0], 3)
                        except:
                            agg_data[field] = 0

                # Rate fields → average
                for field in rate_fields:
                    if field in group.columns:
                        try:
                            agg_data[field] = round(group[field].mean(), 3)
                        except:
                            agg_data[field] = 0

                # Environmental → average
                for field in environmental_fields:
                    if field in group.columns:
                        try:
                            agg_data[field] = round(group[field].mean(), 3)
                        except:
                            agg_data[field] = 0

                # Other fields → average
                for field in other_fields:
                    if field in group.columns:
                        try:
                            agg_data[field] = round(group[field].mean(), 3)
                        except:
                            agg_data[field] = 0

                MeterReadingAggregate.objects.update_or_create(
                    meter=meter,
                    period_type=period_name,
                    start_date=start_date.date(),
                    defaults={"aggregateData": agg_data}
                )

# Run the aggregation
aggregate_meter_data()
