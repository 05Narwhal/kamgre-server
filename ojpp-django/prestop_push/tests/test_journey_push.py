"""A5: a watched journey warns about a late later ride, a change at risk and a disruption on the way."""
import json
from datetime import datetime, timedelta, timezone
from unittest import mock

from django.test import TestCase

from prestop_push import journey, watcher
from prestop_push.models import PushSubscription, Watch
from prestop_push.tests.test_push import SUB

NOW = datetime(2026, 10, 10, 8, 0, tzinfo=timezone.utc)


def at(minutes, delay=0):
    return (NOW + timedelta(minutes=minutes, seconds=delay)).isoformat()


def stop(sid, name, lat, minutes, delay=None):
    live = delay is not None
    return {'stopId': sid, 'name': name, 'latitude': lat, 'longitude': 14.5,
            'scheduledArrival': at(minutes), 'scheduledDeparture': at(minutes),
            'effectiveArrival': at(minutes, delay) if live else None, 'effectiveDeparture': at(minutes, delay) if live else None, 'canceled': False}


def trips(first_delay=None, second_delay=None):
    """Bus 6 from Bavarski dvor (08:20) to Kolodvor (08:30), then train RG 1 from Ljubljana (08:36, 50 m away)."""
    return {
        'LPP:t6': {'id': 'LPP:t6', 'routeId': 'LPP:6', 'routeName': '6', 'stops': [
            stop('LPP:bd', 'Bavarski dvor', 46.050, 20, first_delay), stop('LPP:kol', 'Kolodvor', 46.058, 30, first_delay)]},
        'IJPP:rg1': {'id': 'IJPP:rg1', 'routeId': 'IJPP:rg', 'routeName': 'RG 1', 'stops': [
            stop('IJPP:lj', 'Ljubljana', 46.0584, 36, second_delay), stop('IJPP:kr', 'Kranj', 46.24, 60, second_delay)]},
    }


class JourneyPushTests(TestCase):
    def setUp(self):
        sub = PushSubscription.objects.create(endpoint=SUB['endpoint'], p256dh=SUB['keys']['p256dh'], auth=SUB['keys']['auth'], language='en')
        self.watch = Watch.objects.create(subscription=sub, client_id='journey:x', kind='journey', notify_at=NOW, title='Home → Kranj',
                                          body='08:20', url='/journeys/x', trip_ids=['LPP:t6', 'IJPP:rg1'], stop_id='LPP:bd',
                                          scheduled_at=NOW + timedelta(minutes=20), expires_at=NOW + timedelta(hours=2), sent_reminder=True)

    def tick(self, minutes, found, alerts=()):
        with mock.patch('prestop_push.watcher.load_trips', return_value=found), \
                mock.patch('prestop_push.watcher.load_alerts', return_value=list(alerts)), \
                mock.patch('prestop_push.journey._usual_delay', return_value=None), \
                mock.patch('prestop_push.sender.webpush') as push:
            watcher.tick(NOW + timedelta(minutes=minutes))
        return [json.loads(c.kwargs['data']) for c in push.call_args_list]

    def test_the_rides_and_the_change_are_found(self):
        built = journey.rides(['LPP:t6', 'IJPP:rg1'], 'LPP:bd', trips())
        self.assertEqual([(r['trip']['id'], r['board'], r['alight']) for r in built], [('LPP:t6', 0, 1), ('IJPP:rg1', 0, None)])

    def test_a_change_at_risk_then_nothing_more_within_ten_minutes(self):
        self.assertEqual(self.tick(1, trips(first_delay=0)), [])  # the first look: what the rider saw in the app
        [sent] = self.tick(2, trips(first_delay=300))  # the bus is 5 min late: 1 min left for the train
        self.assertEqual((sent['kind'], sent['renotify']), ('update', True))
        self.assertIn('change at Ljubljana is at risk', sent['body'])
        self.assertEqual(self.tick(5, trips(first_delay=600)), [])  # now missed, but within 10 min of the last message
        [sent] = self.tick(13, trips(first_delay=600))
        self.assertIn('miss your change at Ljubljana', sent['body'])

    def test_a_later_ride_expected_late_and_no_message_for_under_two_minutes(self):
        self.tick(1, trips(second_delay=0))
        [sent] = self.tick(2, trips(second_delay=240))
        self.assertIn('RG 1 is expected 4 min late', sent['body'])
        self.assertEqual(self.tick(14, trips(second_delay=300)), [])  # 1 more minute: not worth a message
        [sent] = self.tick(25, trips(second_delay=420))
        self.assertIn('7 min late', sent['body'])

    def test_a_disruption_on_the_route(self):
        alert = {'id': 'alert:works', 'title': 'Works between Ljubljana and Kranj', 'routeIds': ['IJPP:rg'], 'stopIds': [],
                 '_from': NOW.timestamp() - 3600, '_to': None}
        other = {**alert, 'id': 'alert:other', 'routeIds': ['IJPP:elsewhere']}
        self.tick(1, trips(), alerts=[other])
        [sent] = self.tick(2, trips(), alerts=[other, alert])
        self.assertEqual(sent['body'], 'Disruption on your way: Works between Ljubljana and Kranj')
        self.assertEqual(self.tick(20, trips(), alerts=[other, alert]), [])  # told once
