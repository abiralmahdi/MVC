from datetime import date, datetime, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from accounts.models import UserModel
from alarms.models import Alarms, AlarmsRange
from dashboard.aggregation import build_hierarchy, fold_readings, run_hierarchy_aggregation, run_time_aggregation
from dashboard.models import Dashboard, Gadgets, LatestMeterReading, MeterReading, MeterReadingAggregate, store_reading
from dynamic.models import Areas, Buildings, LoadType, Measurements, Meters, Site
from home.models import GlobalConfiguration
from utils.timeutils import period_start


def local_dt(*args):
    return timezone.make_aware(datetime(*args))


class Fixture:
    @staticmethod
    def site(name='Site A'):
        site = Site.objects.create(name=name, latitude='23.81', longitude='90.41')
        building = Buildings.objects.create(name=f'{name} B1', site=site)
        area = Areas.objects.create(name='Floor 1', building=building)
        load = LoadType.objects.get_or_create(name='HVAC')[0]
        meters = [
            Meters.objects.create(name=f'{name} M{i}', ip='127.0.0.1', area=area, loadType=load, meterType='Electricity Meter')
            for i in (1, 2)
        ]
        return site, building, area, meters


class AlarmTests(TestCase):
    def setUp(self):
        _, _, _, (self.meter, _) = Fixture.site()
        # Measurement names are not unique any more than they were before: this must not break saving.
        for _ in range(2):
            measurement = Measurements.objects.create(name='Voltage L1N', meter=self.meter)
        AlarmsRange.objects.create(meter=self.meter, measurement=measurement, minValue=200, maxValue=250)

    def test_alarm_raised_once_per_excursion(self):
        for value in (260, 265, 262):
            store_reading(self.meter, {'Voltage L1N': value})
        alarms = Alarms.objects.filter(meter=self.meter)
        self.assertEqual(alarms.count(), 1)
        self.assertEqual(alarms.first().alarmType, 'High')
        self.assertEqual(alarms.first().value, 265)  # worst value kept

        alarms.update(acknowledged=True)
        store_reading(self.meter, {'Voltage L1N': 190})
        self.assertEqual(Alarms.objects.filter(meter=self.meter, acknowledged=False, alarmType='Low').count(), 1)

    def test_latest_reading_is_one_row_per_meter(self):
        for value in (230, 231, 232):
            store_reading(self.meter, {'Voltage L1N': value})
        self.assertEqual(LatestMeterReading.objects.filter(meter=self.meter).count(), 1)
        self.assertEqual(LatestMeterReading.objects.get(meter=self.meter).data['Voltage L1N'], 232)
        self.assertEqual(MeterReading.objects.filter(meter=self.meter).count(), 3)

    def test_timestamps_are_timezone_aware(self):
        reading = store_reading(self.meter, {'Voltage L1N': 230})
        self.assertTrue(timezone.is_aware(reading.timestamp))


class AggregationTests(TestCase):
    def setUp(self):
        self.site, self.building, self.area, (self.m1, self.m2) = Fixture.site()

    def _readings(self, meter, start, hours, energy_step, voltage):
        rows = []
        energy = 1000.0
        for h in range(hours):
            energy += energy_step
            rows.append(MeterReading(meter=meter, timestamp=start + timedelta(hours=h), data={'Energy': energy, 'Voltage L1N': voltage}))
        MeterReading.objects.bulk_create(rows)

    def test_counter_reset_does_not_create_negative_consumption(self):
        start = local_dt(2026, 3, 2)
        rows = [(start + timedelta(hours=i), {'Energy': v}) for i, v in enumerate([100, 110, 120, 5, 15])]
        bucket = fold_readings(rows)[date(2026, 3, 2)]
        self.assertAlmostEqual(bucket.values()['Energy'], 30.0)  # 10 + 10 + (reset) + 10

    def test_local_midnight_day_boundaries(self):
        # 23:30 and 00:30 local time are different local days even though both are the same UTC day.
        rows = [(local_dt(2026, 3, 2, 23, 30), {'Voltage L1N': 1}), (local_dt(2026, 3, 3, 0, 30), {'Voltage L1N': 3})]
        self.assertEqual(sorted(fold_readings(rows)), [date(2026, 3, 2), date(2026, 3, 3)])

    def test_weekly_periods_start_on_monday_and_match_views(self):
        self._readings(self.m1, local_dt(2026, 3, 4), 48, 1.0, 230)  # Wednesday
        run_time_aggregation()
        weekly = MeterReadingAggregate.objects.filter(meter=self.m1, period_type='weekly')
        self.assertEqual(list(weekly.values_list('start_date', flat=True)), [date(2026, 3, 2)])
        self.assertEqual(period_start(date(2026, 3, 5), 'weekly'), date(2026, 3, 2))
        monthly = MeterReadingAggregate.objects.get(meter=self.m1, period_type='monthly', start_date=date(2026, 3, 1))
        self.assertAlmostEqual(monthly.aggregateData['Energy'], 47.0)

    def test_hierarchy_sums_energy_but_averages_voltage(self):
        self._readings(self.m1, local_dt(2026, 3, 4), 10, 2.0, 230)
        self._readings(self.m2, local_dt(2026, 3, 4), 10, 1.0, 240)
        run_time_aggregation()
        run_hierarchy_aggregation()
        data = build_hierarchy(self.site, 'monthly', date(2026, 3, 1))
        total = data['site_total']
        self.assertAlmostEqual(total['Energy'], 18.0 + 9.0)
        self.assertAlmostEqual(total['Voltage L1N'], 235.0)

    def test_incremental_run_only_touches_recent_periods(self):
        self._readings(self.m1, local_dt(2025, 6, 10), 5, 1.0, 230)
        self._readings(self.m1, local_dt(2026, 3, 4), 5, 1.0, 230)
        run_time_aggregation()
        MeterReadingAggregate.objects.filter(start_date__year=2025).update(aggregateData={'marker': 1})
        run_time_aggregation(since=date(2026, 3, 4))
        self.assertTrue(MeterReadingAggregate.objects.filter(start_date__year=2025, aggregateData={'marker': 1}).exists())

    def test_long_periods_are_derived_from_monthly_aggregates(self):
        # January has no raw readings left (archived); only its monthly aggregate remains.
        MeterReadingAggregate.objects.create(meter=self.m1, period_type='monthly', start_date=date(2026, 1, 1),
                                             aggregateData={'Energy': 100.0, 'Voltage L1N': 220.0})
        self._readings(self.m1, local_dt(2026, 3, 4), 10, 2.0, 240)
        run_time_aggregation(since=date(2026, 3, 4))
        quarter = MeterReadingAggregate.objects.get(meter=self.m1, period_type='3monthly', start_date=date(2026, 1, 1))
        year = MeterReadingAggregate.objects.get(meter=self.m1, period_type='yearly', start_date=date(2026, 1, 1))
        for agg in (quarter, year):
            self.assertAlmostEqual(agg.aggregateData['Energy'], 100.0 + 18.0)
            self.assertAlmostEqual(agg.aggregateData['Voltage L1N'], 230.0)


class DashboardAccessTests(TestCase):
    def setUp(self):
        self.site_a, _, _, (self.meter_a, _) = Fixture.site('Site A')
        self.site_b, _, _, (self.meter_b, _) = Fixture.site('Site B')
        self.dash_a = Dashboard.objects.create(title='A', site=self.site_a)
        self.dash_b = Dashboard.objects.create(title='B', site=self.site_b)
        measurement = Measurements.objects.create(name='Voltage L1N', meter=self.meter_a)
        self.gadget_b = Gadgets.objects.create(name='g', gadget_type='line', dashboard=self.dash_b, access=['Operator'])
        self.gadget_b.meters.set([self.meter_b])
        self.gadget_b.measurement.set([measurement])
        store_reading(self.meter_b, {'Voltage L1N': 230})

        user = User.objects.create_user('op', 'op@example.com', 'VeryStrong#Pass1')
        UserModel.objects.create(user=user, name='Op', email='op@example.com', role='Operator', site=self.site_a)
        self.client.force_login(user)

    def test_operator_cannot_read_other_site_gadget(self):
        for url in (
            f'/dashboard/{self.dash_b.id}/fetchLatestReadings/{self.gadget_b.id}/',
            f'/dashboard/{self.dash_a.id}/fetchLatestReadings/{self.gadget_b.id}/',
        ):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_anonymous_gets_401_json(self):
        self.client.logout()
        response = self.client.get(f'/dashboard/{self.dash_b.id}/fetchLatestReadings/{self.gadget_b.id}/')
        self.assertEqual(response.status_code, 401)

    def test_user_without_profile_does_not_crash(self):
        stranger = User.objects.create_user('nobody', 'n@example.com', 'VeryStrong#Pass1')
        self.client.force_login(stranger)
        for url in ('/', '/dashboard/', f'/dashboard/{self.dash_a.id}', '/alarms/allAlarms', '/reports/', '/billing/', '/scada/'):
            response = self.client.get(url)
            self.assertIn(response.status_code, (200, 302, 403), url)


class PageSmokeTests(TestCase):
    """Every page renders for a superuser with a realistic configuration."""

    def setUp(self):
        GlobalConfiguration.objects.update_or_create(pk=GlobalConfiguration.load().pk, defaults={'scada': True})
        self.site, self.building, self.area, (self.m1, self.m2) = Fixture.site()
        for meter in (self.m1, self.m2):
            Measurements.objects.create(name='Energy', meter=meter)
            Measurements.objects.create(name='Voltage L1N', meter=meter)
        start = timezone.now() - timedelta(days=3)
        for meter in (self.m1, self.m2):
            MeterReading.objects.bulk_create([
                MeterReading(meter=meter, timestamp=start + timedelta(hours=h), data={'Energy': 100 + h, 'Voltage L1N': 230})
                for h in range(72)
            ])
            store_reading(meter, {'Energy': 200, 'Voltage L1N': 231})
        run_time_aggregation()
        run_hierarchy_aggregation()
        self.dashboard = Dashboard.objects.create(title='Main', site=self.site)
        energy = Measurements.objects.filter(name='Energy').first()
        for gadget_type in ('pie', 'bar', 'line', 'table', 'tool', 'sankey', 'heatmap', 'picturemap', 'multiple-meter-table', 'valueCard'):
            gadget = Gadgets.objects.create(name=gadget_type, gadget_type=gadget_type, dashboard=self.dashboard, access=['Administrator'], building=self.building)
            gadget.meters.set([self.m1, self.m2])
            gadget.measurement.set([energy])
        self.admin = User.objects.create_superuser('root', 'root@example.com', 'VeryStrong#Pass1')
        self.client.force_login(self.admin)

    def test_pages(self):
        urls = [
            '/dashboard/', f'/dashboard/{self.dashboard.id}', '/dashboard/centralCommand/industryOverview',
            '/alarms/allAlarms', '/alarms/allAlarms?show=all', '/alarms/setAlarmRange/', '/reports/', '/reports/viewSavedReports',
            '/billing/', '/location/', '/scada/', f'/scada/building/{self.building.id}', '/settings/', '/settings/hierarchy',
            '/settings/configurations', '/accounts/accountSettings', '/accounts/loginHistory', '/accounts/register',
        ]
        for url in urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)

    def test_gadget_endpoints(self):
        today = timezone.localdate().isoformat()
        g = {gd.gadget_type: gd for gd in Gadgets.objects.all()}
        d = self.dashboard.id
        endpoints = [
            f'/dashboard/{d}/fetchLatestReadings/{g["line"].id}/',
            f'/dashboard/{d}/fetchDateTimeWindow/{g["line"].id}/{today}T10:00/',
            f'/dashboard/{d}/data/{g["pie"].id}/Energy/{today}/monthly',
            f'/dashboard/{d}/data/{g["pie"].id}/Energy/{today}/daily',
            f'/dashboard/{d}/multiYearBarData/{g["bar"].id}/Energy/{today}/monthly',
            f'/dashboard/{d}/multiYearBarData/{g["bar"].id}/Energy/{today}/weekly?start=2026-W01&end=2026-W10',
            f'/dashboard/{d}/fetchTableData/{g["table"].id}',
            f'/dashboard/{d}/fetchLatestToolData/{g["tool"].id}/',
            f'/dashboard/{d}/fetchLatestMultipleMeterTableData/{g["multiple-meter-table"].id}/',
            f'/dashboard/{d}/hierarchyy/{self.site.id}/Energy/monthly/{today}/',
            f'/dashboard/{d}/heatmap/{self.m1.id}/{today}/{today}/Energy/',
            f'/dashboard/{d}/building_heatmap/{self.building.id}/Energy/',
            f'/dashboard/{d}/fetchValueCardData/{self.site.id}/{g["valueCard"].measurement.first().id}',
            f'/dashboard/centralCommand/industryOverview/{self.site.id}/Energy/monthly/',
        ]
        for url in endpoints:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, f'{url}: {response.content[:300]}')

        pie = self.client.get(f'/dashboard/{d}/data/{g["pie"].id}/Energy/{today}/monthly').json()
        self.assertEqual(len(pie['data']), 2)
