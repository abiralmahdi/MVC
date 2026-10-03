"""Single source of truth for measurement names and how they aggregate.

Measurement keys are the keys stored in ``MeterReading.data``.
"""

# Display order used by tables and gadget forms.
ORDERED_MEASUREMENTS = [
    # Electricity Meter
    "Voltage L1N", "Voltage L2N", "Voltage L3N",
    "Voltage L1-L2", "Voltage L2-L3", "Voltage L3-L1",
    "3-Phase Average Voltage L-N", "3-Phase Average Voltage L-L",
    "Current L1", "Current L2", "Current L3",
    "3-Phase Average Current L-L",
    "Line Frequency",
    "Power Factor L1", "Power Factor L2", "Power Factor L3",
    "Power Factor",
    "Active Power L1", "Active Power L2", "Active Power L3",
    "Total Active Power",
    "Reactive Power L1", "Reactive Power L2", "Reactive Power L3",
    "Total Reactive Power",
    "Apparent Power L1", "Apparent Power L2", "Apparent Power L3",
    "Total Apparent Power",
    "THD Voltage L1-L2", "THD Voltage L2-L3", "THD Voltage L3-L1",
    "Energy",
    "Total kWh DG", "DG Sensing", "CT Secondary", "CT Primary", "PT Secondary", "PT Primary",
    # Water Meter
    "Flow Rate", "Total Volume",
    # Gas Meter
    "Gas Flow Rate", "Gas Pressure", "Total Gas Volume",
    # Steam Meter
    "Steam Flow Rate", "Steam Pressure", "Total Steam",
    # Fuel Meter
    "Fuel Consumption Rate", "Total Fuel Used",
    # Temperature & Humidity
    "Temperature", "Humidity", "Pressure",
    # Air Quality
    "CO2 Level", "PM2.5", "PM10",
]

# Monotonic counters: consumption over a period is the sum of positive deltas
# (robust against meter resets / replacement).
CUMULATIVE_FIELDS = {
    "Total Active Power",
    "Total Reactive Power",
    "Total Apparent Power",
    "Energy",
    "Total kWh DG",
    "Total Volume",
    "Total Gas Volume",
    "Total Steam",
    "Total Fuel Used",
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
        "Total kWh DG", "DG Sensing", "CT Secondary", "CT Primary", "PT Secondary", "PT Primary",
    ],
}

# Default engineering units used when measurements are created automatically.
MEASUREMENT_UNITS = {
    "Voltage L1N": "V", "Voltage L2N": "V", "Voltage L3N": "V",
    "Voltage L1-L2": "V", "Voltage L2-L3": "V", "Voltage L3-L1": "V",
    "Current L1": "A", "Current L2": "A", "Current L3": "A",
    "Apparent Power L1": "kVA", "Apparent Power L2": "kVA", "Apparent Power L3": "kVA",
    "Total Apparent Power": "kVAh", "Energy": "kWh",
    "Active Power L1": "kW", "Active Power L2": "kW", "Active Power L3": "kW",
    "Reactive Power L1": "kVAr", "Reactive Power L2": "kVAr", "Reactive Power L3": "kVAr",
    "Total Active Power": "kWh", "Total Reactive Power": "kVArh",
    "Power Factor L1": "PF", "Power Factor L2": "PF", "Power Factor L3": "PF", "Power Factor": "PF",
    "THD Voltage L1-L2": "%", "THD Voltage L2-L3": "%", "THD Voltage L3-L1": "%",
    "Line Frequency": "Hz", "3-Phase Average Voltage L-N": "V",
    "3-Phase Average Voltage L-L": "V", "3-Phase Average Current L-L": "A",
    "Total kWh DG": "kWh",
    "Flow Rate": "m³/h", "Total Volume": "m³",
    "Fuel Consumption Rate": "L/h", "Total Fuel Used": "L",
    "Gas Flow Rate": "m³/h", "Gas Pressure": "bar", "Total Gas Volume": "m³",
    "Steam Flow Rate": "kg/h", "Steam Pressure": "bar", "Total Steam": "kg",
    "Temperature": "°C", "Pressure": "bar", "Humidity": "%",
    "CO2 Level": "ppm", "PM2.5": "µg/m³", "PM10": "µg/m³",
}

# Intensive quantities: rolling them up the site hierarchy must average, not sum
# (adding the voltages or power factors of three meters is meaningless).
_INTENSIVE_KEYWORDS = (
    "Voltage", "Power Factor", "Frequency", "THD", "Temperature", "Humidity",
    "Pressure", "CO2", "PM2.5", "PM10", "Sensing", "CT ", "PT ", "Average",
)

# Readings used as the billing energy counter, in order of preference.
BILLING_COUNTERS = ["Energy", "Total Active Power"]


def is_cumulative(name):
    return name in CUMULATIVE_FIELDS


def is_intensive(name):
    if name in CUMULATIVE_FIELDS:
        return False
    return any(keyword in name for keyword in _INTENSIVE_KEYWORDS)


def order_measurements(names):
    """Return ``names`` in display order; unknown names are appended alphabetically."""
    names = list(dict.fromkeys(names))
    known = [m for m in ORDERED_MEASUREMENTS if m in names]
    unknown = sorted(n for n in names if n not in ORDERED_MEASUREMENTS)
    return known + unknown


def to_number(value):
    """Readings may contain None/NaN/strings from failed register reads."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float('inf'), float('-inf')):
        return None
    return number
