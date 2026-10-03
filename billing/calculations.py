"""Energy bill calculation (all money maths in Decimal)."""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from num2words import num2words

from dashboard.aggregation import fold_readings, meter_rows
from dashboard.measurements import BILLING_COUNTERS, to_number
from utils.timeutils import local_range_bounds

TWO_PLACES = Decimal('0.01')


def to_decimal(value, default='0'):
    try:
        return Decimal(str(value if value not in (None, '') else default))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def money(value):
    return to_decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def amount_in_words(amount):
    """1234.5 -> "One thousand, two hundred and thirty-four Taka and fifty Paisa only"."""
    amount = money(amount)
    negative = amount < 0
    amount = abs(amount)
    taka = int(amount)
    paisa = int((amount - taka) * 100)
    words = num2words(taka, lang='en').capitalize() + " Taka"
    if paisa:
        words += f" and {num2words(paisa, lang='en')} Paisa"
    words += " only"
    return f"Minus {words[0].lower()}{words[1:]}" if negative else words


@dataclass
class BillResult:
    counter: str = None
    first_value: Decimal = Decimal('0')
    last_value: Decimal = Decimal('0')
    consumption: Decimal = Decimal('0')
    energy_charges: Decimal = Decimal('0')
    extra_fields: dict = field(default_factory=dict)
    extra_total: Decimal = Decimal('0')
    total_before_vat: Decimal = Decimal('0')
    vat_amount: Decimal = Decimal('0')
    total_with_vat: Decimal = Decimal('0')
    penalty: Decimal = Decimal('0')
    total_with_penalty: Decimal = Decimal('0')
    readings: int = 0


def meter_consumption(meter, start_day, end_day):
    """Consumption between the start of ``start_day`` and the end of ``end_day`` (plant local days).

    Uses the first available counter in BILLING_COUNTERS and sums positive
    deltas, so a meter reset or replacement does not produce a negative bill.
    """
    start, end = local_range_bounds(start_day, end_day)
    rows, previous = meter_rows(meter, start, end)
    rows = list(rows)
    counter = None
    for name in BILLING_COUNTERS:
        if any(to_number((data or {}).get(name)) is not None for _, data in rows):
            counter = name
            break
    if counter is None:
        return None, Decimal('0'), Decimal('0'), Decimal('0'), len(rows)

    values = [to_number((data or {}).get(counter)) for _, data in rows]
    values = [v for v in values if v is not None]
    buckets = fold_readings(rows, previous, fields={counter})
    consumption = sum((b.deltas.get(counter, 0.0) for b in buckets.values()), 0.0)
    first = to_number((previous or {}).get(counter))
    first = first if first is not None else values[0]
    return counter, to_decimal(first), to_decimal(values[-1]), to_decimal(consumption), len(rows)


def calculate_bill(billing):
    result = BillResult()
    if billing.date_range_start and billing.date_range_end:
        counter, first, last, consumption, count = meter_consumption(
            billing.meter, billing.date_range_start, billing.date_range_end
        )
        result.counter, result.first_value, result.last_value, result.readings = counter, first, last, count
        result.consumption = consumption.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    rate = to_decimal(billing.rate)
    result.energy_charges = money(result.consumption * rate)
    result.extra_fields = {str(k): money(v) for k, v in (billing.extra_fields or {}).items()}
    result.extra_total = money(sum(result.extra_fields.values(), Decimal('0')) + to_decimal(billing.fixed_charge))
    result.total_before_vat = money(result.energy_charges + result.extra_total)
    result.vat_amount = money(result.total_before_vat * to_decimal(billing.tax) / Decimal('100'))
    result.total_with_vat = money(result.total_before_vat + result.vat_amount)
    result.penalty = money(billing.penalty)
    result.total_with_penalty = money(result.total_with_vat + result.penalty)
    return result
