from django.shortcuts import render, redirect, get_object_or_404
from dynamic.models import *
from dashboard.models import *
from django.contrib.auth.decorators import login_required
from django.contrib import messages
import json
from django.http import JsonResponse, FileResponse, Http404, HttpResponse
from django.db.models.functions import TruncDate, TruncMonth, TruncYear, TruncHour
from datetime import timedelta, datetime
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_protect, csrf_exempt
from accounts.models import UserModel
from utils.decorators import subscription_required
from report.models import *
# Create your views here.


@login_required
@subscription_required
def billing(request):
    config = GlobalConfiguration.objects.first()
    if request.user.is_superuser or request.user.userModel.first().role == 'Administrator':
        sites = Site.objects.all()
        billings = Billing.objects.all()
        meters = Meters.objects.filter(meterType='Electricity Meter')
        measurements = Measurements.objects.all()
    else:
        sites = [UserModel.objects.filter(user=request.user).first().site]
        meters = Meters.objects.filter(area__building__site=UserModel.objects.get(user=request.user).site, meterType='Electricity Meter')
        billings = Billing.objects.filter(meter__in=meters)
        measurements = Measurements.objects.all()
    
    context = {
        'billings':billings,
        'meters':meters,
        'measurements':measurements,
        'sites':sites,
        'config':config
    }
    return render(request, 'billing.html', context)




def create_billing(request):
    if request.method == "POST":
        meter_id = request.POST.get("meter")
        rate = request.POST.get("rate")
        tax = request.POST.get("tax")
        date_range_start = request.POST.get("date_range_start") or None
        date_range_end = request.POST.get("date_range_end") or None
        date_due = request.POST.get("date_due") or None
        remarks = request.POST.get("remarks", "")
        extra_fields_json = request.POST.get("extra_fields", "{}")
        penalty = request.POST.get('penalty') or 0
        authority = request.POST.get("authority")

        try:
            meter = Meters.objects.get(id=meter_id)
        except Meters.DoesNotExist:
            messages.error(request, "Invalid meter selected.")
            return redirect("create_billing")

        # Parse JSON safely
        try:
            extra_fields = json.loads(extra_fields_json) if extra_fields_json else {}
        except json.JSONDecodeError:
            extra_fields = {}
            messages.warning(request, "Invalid extra fields format, ignored.")

        billing = Billing.objects.create(
            meter=meter,
            rate=rate or 0,
            tax=tax or 0,
            date_range_start=date_range_start,
            date_range_end=date_range_end,
            date_due=date_due,
            remarks=remarks,
            extra_fields=extra_fields,
            penalty=penalty,
            authority=authority
        )

        messages.success(request, f"Billing record #{billing.id} created successfully!")
        return redirect("billing")  # redirect to your list page
    
from num2words import num2words
def viewBills(request, billID):
    billing = get_object_or_404(Billing, id=billID)
    meter = billing.meter
    start = billing.date_range_start
    end = billing.date_range_end

    # readings within billing period
    readings = MeterReading.objects.filter(
        meter=meter,
        timestamp__date__gte=start,
        timestamp__date__lte=end
    ).order_by('timestamp')

    # calculate consumption
    total_consumption = 0
    first_value = 0
    last_value = 0
    if readings.exists():
        first_value = readings.first().data.get("Total Active Power", 0)
        last_value = readings.last().data.get("Total Active Power", 0)
        total_consumption = float(last_value) - float(first_value)

    billing.total_consumption = total_consumption
    billing.save()

    # energy charges
    total_energy_charges = float(billing.rate) * total_consumption

    # handle extra fields
    extra_fields = billing.extra_fields if billing.extra_fields else {}
    extra_total = sum(float(v) for v in extra_fields.values())

    # total bill before VAT
    total_bill = total_energy_charges + extra_total

    # VAT
    vat_amount = total_bill * float(billing.tax) / 100
    total_with_vat = total_bill + vat_amount

    # Penalty
    penalty = billing.penalty if hasattr(billing, 'penalty') else 0
    total_with_penalty = float(total_with_vat) + float(penalty)

    # billing month
    billing_month = start.strftime("%B %Y") if start else "-"

    # Convert amount to words
    if '.' in str(round(total_with_penalty, 2)):
        taka, paisa = str(round(total_with_penalty, 2)).split('.')
        taka_words = num2words(int(taka), lang='en').capitalize()
        paisa_words = num2words(int(paisa), lang='en')
        total_bill_words = f"{taka_words} Taka and {paisa_words} Paisa only"
    else:
        total_bill_words = f"{num2words(int(total_with_penalty), lang='en').capitalize()} Taka only"

    # Format all monetary values with commas
    total_energy_charges = f"{total_energy_charges:,.2f}"
    total_bill = f"{total_bill:,.2f}"
    vat_amount = f"{vat_amount:,.2f}"
    total_with_vat = f"{total_with_vat:,.2f}"
    total_with_penalty = f"{total_with_penalty:,.2f}"
    formatted_extra_fields = {k: f"{float(v):,.2f}" for k, v in extra_fields.items()}

    config = GlobalConfiguration.objects.first()
    if request.user.is_superuser or request.user.userModel.first().role == 'Administrator':
        sites = Site.objects.all()
        billings = Billing.objects.all()
        meters = Meters.objects.all()
        measurements = Measurements.objects.all()
    else:
        sites = [UserModel.objects.filter(user=request.user).first().site]
        meters = Meters.objects.filter(area__building__site=UserModel.objects.get(user=request.user).site)
        billings = Billing.objects.filter(meter__in=meters)
        measurements = Measurements.objects.all()

    context = {
        "billing": billing,
        "readings": readings,
        "total_consumption": total_consumption,
        "total_energy_charges": total_energy_charges,
        "extra_fields": formatted_extra_fields,
        "extra_total": extra_total,
        "total_bill": total_bill,
        "vat_amount": vat_amount,
        "total_with_vat": total_with_vat,
        "billing_month": billing_month,
        "first_value": first_value,
        "last_value": last_value,
        "total_bill_words": total_bill_words,
        "total_with_penalty": total_with_penalty,
        'billings': billings,
        'meters': meters,
        'measurements': measurements,
        'sites': sites,
        'config': config
    }
    return render(request, "bill_detail.html", context)
