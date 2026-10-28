import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)

class ApiTests(unittest.TestCase):
    def test_baseline_over_http(self):
        response = client.get('/api/analysis')
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['summary']['matched_hours'], 744)
        self.assertEqual(body['summary']['expected_hours'], 744)
        self.assertAlmostEqual(body['summary']['mae_mw'], 2038.9126344086021)
        self.assertAlmostEqual(body['summary']['rmse_mw'], 2504.758652899355)
        self.assertAlmostEqual(body['summary']['bias_mw'], 1747.8870967741937)
        self.assertEqual(body['evaluation_mode'], 'retrospective')
        self.assertEqual(len(body['daily']), 31)
        self.assertEqual(len(body['series']), 744)

    def test_bounds_and_validation_over_http(self):
        for query in ('decision_from=2025-12-31', 'decision_to=2026-02-01',
                      'decision_from=2026-01-20&decision_to=2026-01-19',
                      'cutoff=9:00', 'cutoff=24:00', 'decision_from=not-a-date'):
            with self.subTest(query=query):
                response = client.get('/api/analysis?' + query)
                self.assertEqual(response.status_code, 422)
                self.assertIn('detail', response.json())

    def test_single_day_and_changed_cutoff_over_http(self):
        base = {'decision_from': '2026-01-15', 'decision_to': '2026-01-15'}
        earlier = client.get('/api/analysis', params={**base, 'cutoff':'09:00'}).json()
        later = client.get('/api/analysis', params={**base, 'cutoff':'10:00'}).json()
        self.assertEqual(earlier['delivery_from'], '2026-01-16')
        self.assertEqual(len(earlier['series']), 24)
        self.assertNotEqual(earlier['summary']['mae_mw'], later['summary']['mae_mw'])
        self.assertTrue(all(p['publish_time'] <= p['cutoff_utc'] for p in earlier['series'] if p['publish_time']))

    def test_missing_data_serializes_as_null_over_http(self):
        from backend.main import snapshot
        wind, actual, version, manifest = snapshot()
        with patch('backend.main.snapshot', return_value=([], [], version, manifest)):
            body = client.get('/api/analysis', params={'decision_from':'2026-01-15', 'decision_to':'2026-01-15'}).json()
        self.assertEqual(body['summary']['matched_hours'], 0)
        self.assertIsNone(body['summary']['mae_mw'])
        self.assertIsNone(body['series'][0]['forecast_mw'])
        self.assertIsNone(body['series'][0]['actual_hourly_mean_mw'])
        self.assertIn('no_forecast_by_cutoff', body['series'][0]['missing_reason'])

    def test_health_and_metadata_over_http(self):
        self.assertEqual(client.get('/api/health').json(), {'status':'ok'})
        self.assertEqual(client.get('/api/meta').json()['timezone'], 'Europe/London')
