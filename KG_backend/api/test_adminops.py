"""Admin operations API (api/adminops.py): health probe, data quality, system
alerts, traffic analytics, pipeline control, vehicle specs, dashboard.

These endpoints run the platform, so the tests pin three things: every admin
route refuses an anonymous caller, malformed input is a 4xx and never a 500,
and the state changes they make (ZIP queue, pipeline settings) are the ones
the admin asked for. Background work (audits, alert sweeps, crawlers, the
pipeline itself) is mocked at the module boundary; nothing is started.
"""
import datetime
import os
from unittest import mock

from django.test import Client, TestCase
from django.utils import timezone

from .models import (
    ActivityLog, Car, Company, DataQualityRun, PipelineSettings, PortalUser,
    SystemAlert, TrafficStat, VehicleSpec, VisitorSeen, ZipPackage,
)

TOKEN = 'adminops-test-token'
ADMIN_URLS = ['/api/admin/data-quality/', '/api/admin/system/', '/api/admin/traffic/',
              '/api/admin/pipeline/', '/api/admin/vehicle-specs/',
              '/api/admin/processing-snapshot/', '/api/admin/dashboard/']


class AdminCase(TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {'KG_ADMIN_TOKEN': TOKEN})
        env.start()
        self.addCleanup(env.stop)
        self.c = Client()           # REMOTE_ADDR 127.0.0.1: a direct loopback call
        self.h = {'HTTP_AUTHORIZATION': f'Bearer {TOKEN}'}

    def get(self, url, **params):
        return self.c.get(url, params, **self.h)

    def post(self, url, body):
        data = body if isinstance(body, str) else __import__('json').dumps(body)
        return self.c.post(url, data, content_type='application/json', **self.h)


class GateTests(AdminCase):
    def test_every_admin_route_refuses_anonymous_and_wrong_token(self):
        for url in ADMIN_URLS:
            self.assertEqual(self.c.get(url).status_code, 401, url)
            self.assertEqual(self.c.get(url, HTTP_AUTHORIZATION='Bearer nope').status_code, 401, url)

    def test_static_token_is_refused_from_outside_the_host(self):
        r = self.c.get('/api/admin/system/', REMOTE_ADDR='203.0.113.9', **self.h)
        self.assertEqual(r.status_code, 401)


class HealthTests(TestCase):
    def test_health_is_public_and_reports_its_parts(self):
        d = Client().get('/api/health/').json()
        self.assertEqual(set(d), {'ok', 'db', 'rag_index', 'uptime_s'})
        self.assertTrue(d['ok'] and d['db'])

    def test_database_failure_is_a_503(self):
        with mock.patch('api.adminops.Car.objects.exists', side_effect=RuntimeError('db gone')):
            r = Client().get('/api/health/')
        self.assertEqual(r.status_code, 503)
        self.assertEqual((r.json()['ok'], r.json()['db']), (False, False))


class DataQualityTests(AdminCase):
    URL = '/api/admin/data-quality/'

    def test_no_audit_yet(self):
        d = self.get(self.URL).json()
        self.assertEqual((d['report'], d['running']), (None, False))

    def test_latest_finished_report_and_running_flag(self):
        DataQualityRun.objects.create(status='done', summary={'complete': 38},
                                      finished_at=timezone.now())
        DataQualityRun.objects.create(status='running')
        d = self.get(self.URL).json()
        self.assertTrue(d['running'])
        self.assertEqual(d['report']['summary'], {'complete': 38})

    def test_refresh_starts_an_audit_and_passes_fix(self):
        with mock.patch('api.adminops.dataquality.run_audit_async', return_value=True) as run:
            d = self.post(self.URL, {'refresh': True, 'fix': 1}).json()
        run.assert_called_once_with(fix=True)
        self.assertTrue(d['started'])

    def test_refresh_while_running_says_so(self):
        with mock.patch('api.adminops.dataquality.run_audit_async', return_value=False):
            d = self.post(self.URL, {'refresh': True}).json()
        self.assertEqual((d['started'], d['detail']), (False, 'an audit is already running'))

    def test_unknown_and_malformed_posts_are_400(self):
        for body in ({}, '[1,2]', 'not json', '"refresh"'):
            self.assertEqual(self.post(self.URL, body).status_code, 400, body)


class SystemTests(AdminCase):
    URL = '/api/admin/system/'

    def test_open_and_resolved_alerts_are_separated(self):
        SystemAlert.objects.create(key='disk_high', severity='critical', message='disk 95%')
        SystemAlert.objects.create(key='old', message='was bad', is_open=False,
                                   resolved_at=timezone.now())
        with mock.patch('api.adminops.monitoring.system_snapshot', return_value={'cpu': 1}):
            d = self.get(self.URL).json()
        self.assertEqual(d['snapshot'], {'cpu': 1})
        self.assertEqual([a['key'] for a in d['alerts_open']], ['disk_high'])
        self.assertEqual([a['key'] for a in d['alerts_recent']], ['old'])
        self.assertIsNotNone(d['alerts_recent'][0]['resolved_at'])

    def test_check_alerts_runs_the_sweep(self):
        with mock.patch('api.adminops.monitoring.evaluate_alerts',
                        return_value={'opened': 1, 'resolved': 0}) as ev:
            d = self.post(self.URL, {'action': 'check_alerts'}).json()
        ev.assert_called_once()
        self.assertEqual((d['ok'], d['opened']), (True, 1))

    def test_unknown_action_is_400(self):
        self.assertEqual(self.post(self.URL, {'action': 'reboot'}).status_code, 400)


class TrafficTests(AdminCase):
    URL = '/api/admin/traffic/'

    def setUp(self):
        super().setUp()
        now = timezone.now()
        TrafficStat.objects.create(bucket=now, endpoint='assist', requests=10,
                                   errors_5xx=1, total_ms=5000, max_ms=900)
        TrafficStat.objects.create(bucket=now, endpoint='search', requests=30,
                                   errors_4xx=3, total_ms=3000, max_ms=200)
        TrafficStat.objects.create(bucket=now - datetime.timedelta(days=20), endpoint='old',
                                   requests=999)
        VisitorSeen.objects.create(day=now.date(), ip_hash='a')
        VisitorSeen.objects.create(day=now.date(), ip_hash='b')
        co = Company.objects.create(name='T', active=True)
        u = PortalUser.objects.create(company=co, username='u', password_hash='x',
                                      role='after_sales_specialist', active=True)
        ActivityLog.objects.create(user=u, action='search')

    def test_totals_endpoints_and_features_within_range(self):
        with mock.patch('api.adminops.monitoring.flush_metrics'):
            d = self.get(self.URL).json()
        self.assertEqual(d['totals']['requests'], 40)            # the 20-day-old row is out
        self.assertEqual(d['totals']['avg_ms'], 200)              # 8000 ms / 40
        self.assertEqual((d['totals']['errors_4xx'], d['totals']['errors_5xx']), (3, 1))
        self.assertEqual(d['totals']['unique_visitors'], 2)
        self.assertEqual([e['endpoint'] for e in d['endpoints']], ['search', 'assist'])
        self.assertEqual(d['endpoints'][1]['avg_ms'], 500)
        self.assertEqual(d['feature_usage'], {'search': 1})
        self.assertEqual(d['series'][-1]['unique_visitors'], 2)

    def test_range_clamp_and_flush_failure_does_not_break_the_page(self):
        with mock.patch('api.adminops.monitoring.flush_metrics', side_effect=OSError):
            self.assertEqual(self.get(self.URL, range=30).json()['totals']['requests'], 1039)
            self.assertEqual(self.get(self.URL, range=5000).json()['range_days'], 90)
            self.assertEqual(self.get(self.URL, range='x').json()['range_days'], 7)


class PipelineTests(AdminCase):
    URL = '/api/admin/pipeline/'

    def zip(self, status, name='a.zip'):
        return ZipPackage.objects.create(path=f'/inbox/{name}', zip_name=name, status=status)

    def test_get_survives_broken_crawler_status(self):
        with mock.patch('api.adminops.tis_crawler.status', side_effect=RuntimeError('no chrome')), \
             mock.patch('api.adminops.partsouq_crawler.status', side_effect=OSError('gone')):
            self.zip('pending')
            d = self.get(self.URL).json()
        self.assertEqual(d['tis'], {'error': 'RuntimeError: no chrome'})
        self.assertEqual(d['partsouq'], {'error': 'OSError: gone'})
        self.assertEqual(d['zip_queue']['counts'], {'pending': 1})

    def test_start_conflict_is_409(self):
        with mock.patch('api.adminops.pipeline.start_job', return_value=(None, 'already running')):
            r = self.post(self.URL, {'action': 'start'})
        self.assertEqual((r.status_code, r.json()['error']), (409, 'already running'))

    def test_schedule_rejects_a_bad_time(self):
        for at in ('tomorrow', '', None, 12):
            self.assertEqual(self.post(self.URL, {'action': 'schedule', 'at': at}).status_code, 400, at)

    def test_schedule_in_the_future_and_in_the_past(self):
        future = (timezone.now() + datetime.timedelta(hours=2)).isoformat()
        with mock.patch('api.adminops.pipeline.start_job', return_value=(None, 'x')) as sj:
            self.post(self.URL, {'action': 'schedule', 'at': future})
            self.assertEqual(sj.call_args.kwargs['trigger'], 'schedule')
            self.post(self.URL, {'action': 'schedule', 'at': '2000-01-01T00:00:00Z'})
            self.assertEqual(sj.call_args.kwargs, {'trigger': 'manual'})

    def test_unknown_or_malformed_ids_are_404_not_500(self):
        # 'abc' used to raise ValueError inside the ORM lookup -> HTTP 500 (D-32).
        for action, key in (('resume', 'job_id'), ('cancel', 'job_id'),
                            ('skip_zip', 'zip_id'), ('requeue_zip', 'zip_id')):
            for bad in (999999, 'abc', None, [1], {'id': 1}, '1; DROP TABLE x'):
                r = self.post(self.URL, {'action': action, key: bad})
                self.assertEqual(r.status_code, 404, (action, bad))

    def test_settings_are_clamped_and_bad_values_ignored(self):
        self.post(self.URL, {'action': 'settings', 'auto_enabled': True, 'load_threshold': 9})
        st = PipelineSettings.get()
        self.assertTrue(st.auto_enabled)
        self.assertEqual(st.load_threshold, 1.5)
        self.post(self.URL, {'action': 'settings', 'load_threshold': 'lots'})
        self.assertEqual(PipelineSettings.get().load_threshold, 1.5)
        self.post(self.URL, {'action': 'settings', 'load_threshold': -1})
        self.assertEqual(PipelineSettings.get().load_threshold, 0.1)

    def test_skip_and_requeue_follow_the_allowed_transitions(self):
        failed = self.zip('failed', 'f.zip')
        done = self.zip('done', 'd.zip')
        self.assertEqual(self.post(self.URL, {'action': 'skip_zip', 'zip_id': failed.id})
                         .json()['zip']['status'], 'skipped_duplicate')
        self.assertEqual(self.post(self.URL, {'action': 'requeue_zip', 'zip_id': failed.id})
                         .json()['zip']['status'], 'pending')
        # a finished package cannot be skipped or requeued
        self.post(self.URL, {'action': 'skip_zip', 'zip_id': done.id})
        self.post(self.URL, {'action': 'requeue_zip', 'zip_id': done.id})
        done.refresh_from_db()
        self.assertEqual(done.status, 'done')
        self.assertEqual(self.post(self.URL, {'action': 'skip_zip', 'zip_id': 424242}).status_code, 404)

    def test_crawler_actions_report_refusals_as_409(self):
        with mock.patch('api.adminops.tis_crawler.start', return_value=(None, 'not logged in')):
            self.assertEqual(self.post(self.URL, {'action': 'tis_start'}).status_code, 409)
        with mock.patch('api.adminops.partsouq_crawler.start', return_value=(4321, None)):
            self.assertEqual(self.post(self.URL, {'action': 'ps_start', 'url': 'x'}).json()['pid'], 4321)

    def test_unknown_action_is_400(self):
        self.assertEqual(self.post(self.URL, {'action': 'format_disk'}).status_code, 400)


class VehicleSpecsTests(AdminCase):
    URL = '/api/admin/vehicle-specs/'

    def setUp(self):
        super().setUp()
        self.camry = Car.objects.create(brand_name='Toyota', car_name='Camry', year=2024, db_address='x')
        self.supra = Car.objects.create(brand_name='Toyota', car_name='Supra', year=2024, db_address='y')
        VehicleSpec.objects.create(car=self.camry, data={'@type': 'Car', 'fuelType': 'Gasoline',
                                                          'driveWheelConfiguration': 'FWD'})

    def test_coverage_list(self):
        d = self.get(self.URL).json()
        self.assertEqual((d['total'], d['with_spec']), (2, 1))
        self.assertEqual(d['field_coverage'], {'driveWheelConfiguration': 1, 'fuelType': 1})
        camry = next(v for v in d['vehicles'] if v['car_name'] == 'Camry')
        self.assertEqual(camry['field_count'], 2)                 # '@type' is not a field

    def test_one_car_and_unknown_car(self):
        d = self.get(self.URL, car_id=self.camry.id).json()
        self.assertEqual(d['spec']['data']['fuelType'], 'Gasoline')
        self.assertIsNone(self.get(self.URL, car_id=self.supra.id).json()['spec'])
        self.assertEqual(self.get(self.URL, car_id=999999).status_code, 404)
        self.assertEqual(self.get(self.URL, car_id='abc').status_code, 404)   # was a 500 (D-32)


class DashboardTests(AdminCase):
    def test_kpis_count_only_active_and_open_things(self):
        Company.objects.create(name='A', active=True)
        Company.objects.create(name='B', active=False)
        SystemAlert.objects.create(key='k', message='m')
        SystemAlert.objects.create(key='k2', message='m', is_open=False)
        d = self.get('/api/admin/dashboard/').json()
        self.assertEqual(d['kpis']['companies'], 1)
        self.assertEqual(d['kpis']['open_alerts'], 1)
        self.assertEqual(len(d['alerts']), 1)


class AdminUsersInputTests(AdminCase):
    """Same defect class in portal.admin_users_view (D-32)."""

    def test_malformed_company_id_is_400_not_500(self):
        for bad in ('abc', None, [1], {'id': 1}, True):
            r = self.post('/api/admin/users/', {'company_id': bad, 'username': 'x'})
            self.assertEqual(r.status_code, 400, bad)
