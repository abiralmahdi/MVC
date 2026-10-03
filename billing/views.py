import json
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from dynamic.models import Meters
from report.models import Billing
from utils.access import can_access_site, get_profile, visible_sites
from utils.decorators import subscription_required

from .calculations import amount_in_words, calculate_bill, to_decimal


def _billing_context(request):
    sites = visible_sites(request.user)
    meters = Meters.objects.filter(
        area__building__site__in=sites, meterType='Electricity Meter'
    ).select_related('area__building__site').order_by('name')
    billings = Billing.objects.filter(meter__area__building__site__in=sites).select_related(
        'meter__area__building__site'
    ).order_by('-created_at', '-id')
    return {'sites': sites, 'meters': meters, 'billings': billings}


@login_required
@subscription_required
def billing(request):
    context = _billing_context(request)
    context['preselected_meter'] = request.GET.get('meter', '')
    return render(request, 'billing.html', context)


@login_required
@subscription_required
@require_POST
def create_billing(request):
    meter = Meters.objects.select_related('area__building__site').filter(id=request.POST.get("meter") or 0).first()
    if meter is None or not can_access_site(request.user, meter.area.building.site if meter.area else None):
        messages.error(request, "Select a valid meter.")
        return redirect("billing")

    start = parse_date(request.POST.get("date_range_start") or '')
    end = parse_date(request.POST.get("date_range_end") or '')
    due = parse_date(request.POST.get("date_due") or '')
    authority = (request.POST.get("authority") or '').strip()

    errors = []
    if not authority:
        errors.append("Billing authority is required.")
    if not start or not end:
        errors.append("Previous and current dates are required.")
    elif end < start:
        errors.append("The current date must be after the previous date.")

    rate, tax, penalty = (to_decimal(request.POST.get(name)) for name in ("rate", "tax", "penalty"))
    if rate < 0 or tax < 0 or penalty < 0:
        errors.append("Rate, tax and penalty cannot be negative.")
    if tax > 100:
        errors.append("Tax is a percentage between 0 and 100.")

    try:
        extra_fields = json.loads(request.POST.get("extra_fields") or "{}")
        if not isinstance(extra_fields, dict):
            raise ValueError
        extra_fields = {str(k).strip(): float(v) for k, v in extra_fields.items() if str(k).strip()}
    except (ValueError, TypeError):
        errors.append("Extra fields must be name/amount pairs.")
        extra_fields = {}

    if errors:
        for error in errors:
            messages.error(request, error)
        return redirect(f"/billing?meter={meter.id}")

    bill = Billing.objects.create(
        meter=meter,
        rate=rate,
        tax=tax,
        date_range_start=start,
        date_range_end=end,
        date_due=due,
        remarks=(request.POST.get("remarks") or '')[:1000],
        extra_fields=extra_fields,
        penalty=penalty,
        authority=authority[:100],
        generatedBy=get_profile(request.user),
    )
    result = calculate_bill(bill)
    bill.total_consumption = result.consumption
    bill.save(update_fields=['total_consumption'])

    messages.success(request, f"Billing record #{bill.id} created.")
    return redirect(f"/billing/{bill.id}")


def _fmt(value):
    return f"{Decimal(value):,.2f}"


@login_required
@subscription_required
def viewBills(request, billID):
    bill = get_object_or_404(Billing.objects.select_related('meter__area__building__site', 'generatedBy'), id=billID)
    site = bill.meter.area.building.site if bill.meter.area else None
    if not can_access_site(request.user, site):
        messages.error(request, "You are not authorized to view that bill.")
        return redirect('billing')

    result = calculate_bill(bill)
    if bill.total_consumption != result.consumption:
        bill.total_consumption = result.consumption
        bill.save(update_fields=['total_consumption'])

    context = _billing_context(request)
    context.update({
        "billing": bill,
        "site": site,
        "counter": result.counter,
        "readings_count": result.readings,
        "total_consumption": _fmt(result.consumption),
        "first_value": _fmt(result.first_value),
        "last_value": _fmt(result.last_value),
        "total_energy_charges": _fmt(result.energy_charges),
        "extra_fields": {k: _fmt(v) for k, v in result.extra_fields.items()},
        "total_bill": _fmt(result.total_before_vat),
        "vat_amount": _fmt(result.vat_amount),
        "total_with_vat": _fmt(result.total_with_vat),
        "penalty": _fmt(result.penalty),
        "total_with_penalty": _fmt(result.total_with_penalty),
        "total_bill_words": amount_in_words(result.total_with_vat),
        "total_with_penalty_words": amount_in_words(result.total_with_penalty),
        "billing_month": bill.date_range_end.strftime("%B %Y") if bill.date_range_end else "-",
    })
    return render(request, "bill_detail.html", context)
