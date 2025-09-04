from dashboard.models import LatestMeterReading, MeterReading

def migrate_latest_readings():
    """
    Migrates new, unique data from LatestMeterReading to MeterReading.
    """
    print("Starting data migration from LatestMeterReading to MeterReading...")
    
    # Get all existing meter-timestamp pairs from MeterReading for efficient lookup
    existing_readings = set(
        MeterReading.objects.values_list('meter_id', 'timestamp')
    )

    new_readings_to_create = []
    
    # Iterate through all records in LatestMeterReading
    for latest_reading in LatestMeterReading.objects.all():
        meter_id = latest_reading.meter_id
        timestamp = latest_reading.timestamp
        
        # Check if this meter-timestamp combination already exists in the main table
        if (meter_id, timestamp) not in existing_readings:
            # If not, prepare a new MeterReading object
            new_reading = MeterReading(
                meter=latest_reading.meter,
                timestamp=latest_reading.timestamp,
                data=latest_reading.data
            )
            new_readings_to_create.append(new_reading)
    
    if new_readings_to_create:
        # Use bulk_create for a single, efficient database operation
        # This is much faster than saving one object at a time in a loop
        MeterReading.objects.bulk_create(new_readings_to_create)
        print(f"Successfully migrated {len(new_readings_to_create)} new records.")
    else:
        print("No new data to migrate. All records are up-to-date.")

# Example usage:
if __name__ == '__main__':
    migrate_latest_readings()