"""Detected disruptions (contract 6): a vehicle standing > 8 min where its timetable doesn't wait, and the votes on it."""
import json
from datetime import datetime, timezone
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone as djtz

from prestop_api import detected, sources
from prestop_api.models import AlertVote, VehicleHalt
from prestop_statistics.tests.test_statistics import DAY, NOW

STOPS = [(1, 46.00, 14.50, 600), (2, 46.01, 14.50, 0), (3, 46.02, 14.50, 300), (4, 46.03, 14.50, 0)]  # 3: a timed point (5 min wait)


def schedule():
    times = [{'stopPosition': n, 'scheduledArrival': 9 * 3600 + n * 600, 'scheduledDeparture': 9 * 3600 + n * 600 + wait,
              'serviceDay': DAY, 'stop': {'gtfsId': f'IJPP:s{n}', 'lat': lat, 'lon': lon}} for n, lat, lon, wait in STOPS]
    return {'routeId': 'IJPP:r1', 'operatorId': 'IJPP:1123', 'direction': '0', 'bySequence': {s['stopPosition']: s for s in times}}


class Schedules:
    def get_many(self, keys):
        return {k: schedule() for k in keys}


def position(lat, lon, at, vehicle='77'):
    return {'vehicle': {'trip': {'tripId': 'IJPP:t1', 'startDate': '20261009'}, 'vehicle': {'id': vehicle}, 'timestamp': str(int(at)),
                        'position': {'latitude': lat, 'longitude': lon}}}


class DetectTests(TestCase):
    def setUp(self):
        detected._candidates.clear()
        detected._pruned['day'] = 'never'
        detected._cache['rows'] = None

    def stand(self, lat, lon, minutes, start=NOW, frozen=False):
        for m in range(minutes + 1):
            at = start + m * 60
            detected.observe(Schedules(), [position(lat, lon, start if frozen else at - 5)], now=at)
        return start + minutes * 60

    def test_standing_nine_minutes_at_a_stop_on_the_way_is_a_halt_until_it_moves(self):
        self.stand(46.01, 14.5003, 7)
        self.assertFalse(VehicleHalt.objects.exists())  # 7 min: a long dwell, not yet a disruption
        end = self.stand(46.01, 14.5003, 2, start=NOW + 8 * 60)
        halt = VehicleHalt.objects.get()
        self.assertEqual((halt.vehicle_id, halt.stop_id, halt.route_id, halt.cleared), ('IJPP:77', 'IJPP:s2', 'IJPP:r1', None))
        detected.observe(Schedules(), [position(46.0105, 14.5, end + 55)], now=end + 60)  # 55 m on
        self.assertIsNotNone(VehicleHalt.objects.get().cleared)

    def test_not_at_the_end_of_the_trip_nor_with_a_frozen_feed(self):
        self.stand(46.03, 14.5, 12)  # its last stop
        detected._candidates.clear()
        self.stand(46.01, 14.5, 12, start=NOW + 3600, frozen=True)  # the same report every poll
        self.assertFalse(VehicleHalt.objects.exists())

    def test_at_a_timed_point_the_clock_runs_from_the_scheduled_departure(self):
        due = DAY + 9 * 3600 + 3 * 600 + 300  # stop 3: arrives 09:30, leaves 09:35
        end = self.stand(46.02, 14.5, 12, start=due - 300)  # there from 09:30 to 09:42: 7 min past its departure
        self.assertFalse(VehicleHalt.objects.exists())
        self.stand(46.02, 14.5, 2, start=end)
        self.assertEqual(VehicleHalt.objects.get().since.timestamp(), due)

    def test_a_vehicle_gone_from_the_feed_clears(self):
        end = self.stand(46.01, 14.5, 10)
        detected.observe(Schedules(), [], now=end + 200)
        self.assertIsNotNone(VehicleHalt.objects.get().cleared)


@override_settings(ROOT_URLCONF='ojpp_core.urls_prestop')
class AlertAndVoteTests(TestCase):
    def setUp(self):
        detected._cache['rows'] = None
        self.halt = VehicleHalt.objects.create(vehicle_id='IJPP:77', trip_id='IJPP:t1', route_id='IJPP:r1', stop_id='IJPP:s2',
                                               latitude=46.01, longitude=14.5, since=datetime.fromtimestamp(NOW - 600, timezone.utc),
                                               last_seen=djtz.now())
        self.id = f'detected:{self.halt.pk}'

    def alert(self):
        detected._cache['rows'] = None
        found = detected.alerts('sl', {'IJPP:r1': {'shortName': 'I6', 'agencyId': 'IJPP:1123'}}, {'IJPP:s2': 'Kovor'}, now=NOW)
        return found[0] if found else None

    def vote(self, answer, device='device-123456', ip='1.2.3.4'):
        return self.client.post(f'/api/v1/alerts/{self.id}/votes', json.dumps({'vote': answer, 'deviceId': device}),
                                content_type='application/json', REMOTE_ADDR=ip)

    def test_the_alert_carries_contract_6(self):
        a = self.alert()
        self.assertEqual({k: a[k] for k in ('id', 'kind', 'source', 'vehicleId', 'latitude', 'longitude', 'routeIds', 'stopIds', 'operatorId', 'votes', 'to')},
                         {'id': self.id, 'kind': 'vehicle-stopped', 'source': 'detected', 'vehicleId': 'IJPP:77', 'latitude': 46.01, 'longitude': 14.5,
                          'routeIds': ['IJPP:r1'], 'stopIds': ['IJPP:s2'], 'operatorId': 'IJPP:1123', 'votes': {'yes': 0, 'no': 0}, 'to': None})
        self.assertEqual(a['title'], 'I6 stoji na postaji Kovor')
        self.assertIn('10 min', a['message'])

    def test_one_vote_per_device_and_three_no_hide_it(self):
        self.assertEqual(self.vote('yes').json()['data']['votes'], {'yes': 1, 'no': 0})
        self.assertEqual(self.vote('no').json()['data']['votes'], {'yes': 0, 'no': 1})  # the same device changed its mind
        self.vote('no', device='device-222222')
        self.assertIsNotNone(self.alert())
        self.vote('no', device='device-333333')
        self.assertIsNone(self.alert())
        self.assertFalse(AlertVote.objects.filter(device__contains='device').exists())  # only hashes are kept
        self.assertEqual(AlertVote.objects.values('ip').distinct().count(), 1)

    def test_bad_votes_and_the_rate_limit(self):
        self.assertEqual(self.vote('maybe').status_code, 422)
        missing = self.client.post('/api/v1/alerts/alert:abc/votes', json.dumps({'vote': 'yes'}), content_type='application/json')
        self.assertEqual(missing.status_code, 404)
        with mock.patch.object(detected, 'VOTE_LIMIT', (2, 3600)):
            self.vote('yes', device='device-aaaaaa')
            self.vote('yes', device='device-bbbbbb')
            self.assertEqual(self.vote('yes', device='device-cccccc').status_code, 429)
            self.assertEqual(self.vote('yes', device='device-dddddd', ip='5.6.7.8').status_code, 200)

    def test_detected_alerts_join_the_alert_list(self):
        with mock.patch.object(sources, 'alerts_raw', mock.Mock(get=lambda: mock.Mock(value=[]))):
            self.assertEqual([a['id'] for a in sources.alerts('en')], [self.id])
