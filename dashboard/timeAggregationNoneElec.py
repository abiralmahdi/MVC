import pandas as pd
from tqdm import tqdm
from dashboard.models import MeterReading, MeterReadingAggregate, Meters

def queryset_to_df(queryset):
    data = []
    for reading in queryset:
        row = reading.data.copy()
        row['timestamp'] = reading.timestamp
        data.append(row)
    return pd.DataFrame(data)

def aggregate_meter_data():
    sample_data = MeterReading.objects.first().data.keys()

    # Group known cumulative and rate fields
    cumulative_fields = [
        "Total Fuel Used", "Total Gas Volume", "Total Steam", "Total Volume"
    ]
    rate_fields = [
        "Fuel Consumption Rate", "Gas Flow Rate", "Steam Flow Rate", "Flow Rate"
    ]
    environmental_fields = [
        "Humidity", "Temperature", "Pressure", "CO2 Level", "PM2.5", "PM10"
    ]
    other_fields = set(sample_data) - set(cumulative_fields + rate_fields + environmental_fields)

    periods = {
        'weekly': 'W-MON',
        'monthly': 'MS',
        '3monthly': 'QS-JAN',
        '6monthly': '2QS-JAN',
        'yearly': 'YS',
    }

    # ✅ Use only the same meter types
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

    meters = []
    for meter_type in meter_definitions.keys():
        # ✅ Only first 3 per type
        meters += list(Meters.objects.filter(meterType=meter_type)[:3])

    for meter in tqdm(meters, desc="Processing Meters"):
        readings = MeterReading.objects.filter(meter=meter).order_by("timestamp")
        if not readings.exists():
            continue

        df = queryset_to_df(readings)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)

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

# Run the function
aggregate_meter_data()
