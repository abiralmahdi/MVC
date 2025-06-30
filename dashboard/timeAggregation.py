

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

    # Define field groups
    power_delta_fields = ["Total Active Power", "Total Reactive Power"]
    voltage_fields = [k for k in sample_data if "Voltage" in k]
    current_fields = [k for k in sample_data if "Current" in k]
    pf_fields = [k for k in sample_data if "Power Factor" in k]
    thd_fields = [k for k in sample_data if "THD" in k or "Line Frequency" in k]
    all_fields = set(sample_data)

    # Remaining fields default to averaging
    handled_fields = set(power_delta_fields + voltage_fields + current_fields + pf_fields + thd_fields)
    other_fields = all_fields - handled_fields

    periods = {
        'weekly': 'W-MON',
        'monthly': 'MS',
        '3monthly': 'QS-JAN',
        '6monthly': '2QS-JAN',
        'yearly': 'YS',
    }

    meters = Meters.objects.all()
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

                # Power deltas
                for field in power_delta_fields:
                    try:
                        agg_data[field] = round(group[field].iloc[-1] - group[field].iloc[0], 3)
                    except:
                        agg_data[field] = 0

                # Voltage fields - average
                for field in voltage_fields:
                    try:
                        agg_data[field] = round(group[field].mean(), 3)
                    except:
                        agg_data[field] = 0

                # Current & Power Factor - skip 0s
                for field in current_fields + pf_fields:
                    try:
                        non_zero = group[group[field] != 0][field]
                        agg_data[field] = round(non_zero.mean(), 3) if not non_zero.empty else 0
                    except:
                        agg_data[field] = 0

                # THD & Line Frequency - average
                for field in thd_fields:
                    try:
                        agg_data[field] = round(group[field].mean(), 3)
                    except:
                        agg_data[field] = 0

                # Catch-all other fields
                for field in other_fields:
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
