from dynamic.models import Measurements, Meters

registers = {
    "Voltage L1-N": 1,
    "Voltage L2-N": 3,
    "Voltage L3-N": 5,
    "Voltage L1-L2": 7,
    "Voltage L2-L3": 9,
    "Voltage L3-L1": 11,
    "Current L1": 13,
    "Current L2": 15,
    "Current L3": 17,
    "Total Active Power": 19,
    "Total Apparent Power": 21,
    "Total Reactive Power": 23,
    "Total Power Factor": 25,
    "Line Frequency": 27,
    "Apparent Power L1": 29,
    "Apparent Power L2": 31,
    "Apparent Power L3": 33,
    "Active Power L1": 35,
    "Active Power L2": 37,
    "Active Power L3": 39,
    "Reactive Power L1": 41,
    "Reactive Power L2": 43,
    "Reactive Power L3": 45,
    "Power Factor L1": 47,
    "Power Factor L2": 49,
    "Power Factor L3": 51,
    "THD Voltage L1-L2": 53,
    "THD Voltage L2-L3": 55,
    "THD Voltage L3-L1": 57,
    "3-Phase Average Voltage L-N": 59,
    "3-Phase Average Voltage L-L": 61,
    "3-Phase Average Current L-L": 63,
    "Maximum Voltage L1-N": 65,
    "Maximum Voltage L2-N": 67,
    "Maximum Voltage L3-N": 69,
    "Maximum Voltage L1-L2": 71,
    "Maximum Voltage L2-L3": 73,
    "Maximum Voltage L3-L1": 75,
    "Maximum Current L1": 77,
    "Maximum Current L2": 79,
    "Maximum Current L3": 81,
    "Minimum Voltage L1-N": 83,
    "Minimum Voltage L2-N": 85,
    "Minimum Voltage L3-N": 87,
    "Minimum Voltage L1-L2": 89,
    "Minimum Voltage L2-L3": 91,
    "Minimum Voltage L3-L1": 93,
    "Minimum Current L1": 95,
    "Minimum Current L2": 97,
    "Minimum Current L3": 99,
    "Minimum Power Factor L1": 101,
    "Minimum Power Factor L2": 103,
    "Minimum Power Factor L3": 105,
}

# You need an existing Meters object.
# Replace this with a valid ID or a way to get your Meters object.
try:
    my_meter = Meters.objects.all().first() 
except Meters.DoesNotExist:
    # Handle the case where the meter doesn't exist.
    # For example, you might create one here.
    my_meter = Meters.objects.create(name="Example Meter", meterType="Electricity Meter")


# Loop through the dictionary keys to create Measurements objects
for key in registers.keys():
    Measurements.objects.create(
        name=key,
        meter=my_meter
    )

print("Measurements populated successfully!")