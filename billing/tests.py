from datetime import date, datetime, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from billing.calculations import amount_in_words, calculate_bill
from dashboard.models import MeterReading
from dynamic.models import Areas, Buildings, Meters, Site
from report.models import Billing


class AmountInWordsTests(TestCase):
    def test_paisa_uses_two_decimal_places(self):
        self.assertEqual(amount_in_words(Decimal('12.5')), 'Twelve Taka and fifty Paisa only')
        self.assertEqual(amount_in_words(Decimal('12.05')), 'Twelve Taka and five Paisa only')
        self.assertEqual(amount_in_words(Decimal('100')), 'One hundred Taka only')
        self.assertEqual(amount_in_words(1234.999), 'One thousand, two hundred and thirty-five Taka only')


class BillCalculationTests(TestCase):
    def setUp(self):
        site = Site.objects.create(name='S', latitude='0', longitude='0')
        area = Areas.objects.create(name='A', building=Buildings.objects.create(name='B', site=site))
        self.meter = Meters.objects.create(name='M', ip='1.1.1.1', area=area, meterType='Electricity Meter')
        start = timezone.make_aware(datetime(2026, 3, 1))
        values = [1000, 1010, 1020, 1030, 3, 13]  # meter replaced after 1030
        MeterReading.objects.bulk_create([
            MeterReading(meter=self.meter, timestamp=start + timedelta(days=i), data={'Energy': v, 'Total Active Power': v * 2})
            for i, v in enumerate(values)
        ])

    def test_bill_totals(self):
        bill = Billing.objects.create(
            meter=self.meter, rate=Decimal('8.5'), tax=Decimal('5'), penalty=Decimal('100'),
            date_range_start=date(2026, 3, 1), date_range_end=date(2026, 3, 6), extra_fields={'Demand charge': 50},
        )
        result = calculate_bill(bill)
        self.assertEqual(result.counter, 'Energy')
        self.assertEqual(result.consumption, Decimal('40.00'))
        self.assertEqual(result.energy_charges, Decimal('340.00'))
        self.assertEqual(result.total_before_vat, Decimal('390.00'))
        self.assertEqual(result.vat_amount, Decimal('19.50'))
        self.assertEqual(result.total_with_vat, Decimal('409.50'))
        self.assertEqual(result.total_with_penalty, Decimal('509.50'))

    def test_bill_page_renders(self):
        bill = Billing.objects.create(meter=self.meter, rate=Decimal('8.5'), tax=Decimal('5'),
                                      date_range_start=date(2026, 3, 1), date_range_end=date(2026, 3, 6))
        self.client.force_login(User.objects.create_superuser('root', 'r@example.com', 'VeryStrong#Pass1'))
        response = self.client.get(f'/billing/{bill.id}')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Three hundred and fifty-seven Taka only')

    def test_anonymous_cannot_create_bills(self):
        response = self.client.post('/billing/create_billing', {'meter': self.meter.id})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Billing.objects.count(), 0)
