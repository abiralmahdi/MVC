import json
import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from dashboard.aggregation import run_hierarchy_aggregation, run_time_aggregation
from dashboard.models import MeterReading
from dynamic.models import Areas, Buildings, Measurements, Meters, Site
from report.models import ReportDiagram, ReportFormat

PNG_1x1 = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='


class ReportFlowTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.site = Site.objects.create(name='S', latitude='0', longitude='0')
        area = Areas.objects.create(name='A', building=Buildings.objects.create(name='B', site=self.site))
        self.meter = Meters.objects.create(name='M', ip='1.1.1.1', area=area, meterType='Electricity Meter')
        Measurements.objects.create(name='Energy', meter=self.meter)
        start = timezone.now() - timedelta(days=2)
        MeterReading.objects.bulk_create([
            MeterReading(meter=self.meter, timestamp=start + timedelta(hours=h), data={'Energy': 10 + h})
            for h in range(48)
        ])
        run_time_aggregation()
        run_hierarchy_aggregation()
        self.client.force_login(User.objects.create_superuser('root', 'r@example.com', 'VeryStrong#Pass1'))

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.media, ignore_errors=True)

    def test_create_render_and_pdf(self):
        today = timezone.localdate()
        diagrams = [
            {'type': t, 'meters': [str(self.meter.id)], 'measurement': 'Energy', 'startDate': str(today - timedelta(days=3)),
             'endDate': str(today), 'periodType': 'daily', 'description': "Operator's note"}
            for t in ('bar', 'pie', 'heatmap')
        ]
        diagrams.append({'type': 'table', 'meters': [str(self.meter.id)], 'measurements': ['Energy'], 'startDate': str(today - timedelta(days=3)), 'endDate': str(today)})
        diagrams.append({'type': 'line', 'meters': [str(self.meter.id)], 'measurement': 'Energy', 'startDate': f'{today - timedelta(days=3)}T00:00', 'endDate': f'{today}T23:59'})
        diagrams.append({'type': 'sankey', 'meters': [], 'measurement': 'Energy', 'startDate': str(today), 'periodType': 'monthly'})
        response = self.client.post('/reports/createReportFormat', {
            'title': 'Monthly energy', 'description': 'Test', 'site': self.site.id,
            'diagrams[]': [json.dumps(d) for d in diagrams],
        })
        report = ReportFormat.objects.get()
        self.assertRedirects(response, f'/reports/viewReport/{report.id}')
        self.assertEqual(self.client.get(f'/reports/viewReport/{report.id}').status_code, 200)

        endpoints = {'bar': 'getDiagramData', 'pie': 'getDiagramData', 'heatmap': 'heatmap', 'table': 'getTableData', 'line': 'getLineDiagramData', 'sankey': 'sankey_data'}
        for diagram in report.diagrams.all():
            response = self.client.get(f'/reports/{endpoints[diagram.diagram_type]}/{diagram.id}')
            self.assertEqual(response.status_code, 200, f'{diagram.diagram_type}: {response.content[:200]}')
            saved = self.client.post(f'/reports/saveDiagramImage/{diagram.id}', json.dumps({'image': PNG_1x1}), content_type='application/json')
            self.assertEqual(saved.status_code, 200)

        bar = report.diagrams.get(diagram_type='bar')
        self.assertTrue(self.client.get(f'/reports/getDiagramData/{bar.id}').json()['data'])

        pdf = self.client.get(f'/reports/generate_pdf/{report.id}')
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(b''.join(pdf.streaming_content).startswith(b'%PDF'))
        self.assertEqual(self.client.get(f'/reports/viewSavedReports/{report.id}').status_code, 200)
        self.assertEqual(self.client.get(f'/reports/viewSavedReport/{report.id}/').status_code, 200)

    def test_rejects_non_image_upload_data(self):
        report = ReportFormat.objects.create(title='r', site=self.site)
        diagram = ReportDiagram.objects.create(report_format=report, site=self.site, diagram_type='bar')
        response = self.client.post(f'/reports/saveDiagramImage/{diagram.id}', json.dumps({'image': 'data:text/html;base64,PGgxPg=='}), content_type='application/json')
        self.assertEqual(response.status_code, 400)

    def test_saved_pdf_requires_login(self):
        report = ReportFormat.objects.create(title='r', site=self.site)
        self.client.logout()
        self.assertEqual(self.client.get(f'/reports/viewSavedReport/{report.id}/').status_code, 302)
