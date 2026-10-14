from django.test import SimpleTestCase

from prestop_api import journeys, mapping
from prestop_api.tests.test_mapping import NOW, PLACE, leg, otp_alert


def request(**overrides):
    body = {'origin': PLACE, 'destination': {**PLACE, 'name': 'Bled'}, 'via': [], 'dateTime': '2026-10-09T10:00:00Z',
            'timeMode': 'departAt', 'minTransferSeconds': 180, 'modes': ['walk', 'bus', 'rail'], 'riskMode': 'normal', **overrides}
    return journeys.parse_request(body, insane_enabled=False)


def notice(id_, title, kind, start, **extra):
    return {'id': id_, 'title': title, 'message': '', 'operatorId': 'IJPP:1161', 'stopIds': [], 'routeIds': [], 'validFrom': mapping.iso(start),
            'validTo': None, 'sourceUrl': 'https://potniski.sz.si/inf', 'kind': kind, '_from': start, '_to': None, '_aliases': [id_], **extra}


class JourneyAlertTests(SimpleTestCase):
    def test_journey_carries_the_notices_of_its_legs(self):
        at = journeys._ts('2026-10-09T10:00:00+02:00')
        alerts = [notice('alert:works', 'Dela na progi', 'disruption', at - 7200, routeIds=['IJPP:r']),
                  notice('alert:bus', 'Vozni red nadomestnega prevoza: A - B in obratno.', 'replacement', at - 3600, operatorId='IJPP:unknown'),
                  notice('alert:other', 'Elsewhere', 'info', at - 9000, routeIds=['IJPP:elsewhere'])]
        data = {'planConnection': {'edges': [{'node': {'walkTime': 0, 'legs': [leg('RAIL', '10:00:00', '10:30:00', trip='IJPP:1')]}}]}}
        [j] = journeys.build_journeys(data, request(), alerts)
        # alert:X (OTP's, not in the notice list) could not be shown, so it is not counted either.
        self.assertEqual(j['legs'][0]['alertIds'], ['alert:works', 'alert:bus'])
        self.assertEqual([a['id'] for a in j['alerts']], ['alert:bus', 'alert:works'])
        self.assertNotIn('_from', j['alerts'][0])


    def test_otp_attached_notice_for_other_listed_days_is_dropped(self):
        at = journeys._ts('2026-10-09T10:00:00+02:00')
        other_days = notice('alert:X', 'Vozni red nadomestnega prevoza: A - B in obratno (10., 11. oktober).', 'replacement', at - 86400, routeIds=['IJPP:r'])
        data = {'planConnection': {'edges': [{'node': {'walkTime': 0, 'legs': [leg('RAIL', '10:00:00', '10:30:00', trip='IJPP:1')]}}]}}
        [j] = journeys.build_journeys(data, request(), [other_days])
        self.assertEqual((j['legs'][0]['alertIds'], j['alerts']), ([], []))


    def test_otp_attached_notice_for_another_section_is_dropped(self):
        at = journeys._ts('2026-10-09T10:00:00+02:00')
        far = notice('alert:X', 'Vozni red nadomestnega prevoza: C - D in obratno.', 'replacement', at - 86400, routeIds=['IJPP:r'])
        data = {'planConnection': {'edges': [{'node': {'walkTime': 0, 'legs': [leg('RAIL', '10:00:00', '10:30:00', trip='IJPP:1')]}}]}}
        [j] = journeys.build_journeys(data, request(), [far])
        self.assertEqual(j['legs'][0]['alertIds'], [])


class AlertKindTests(SimpleTestCase):
    def test_notices_are_classified(self):
        raw = [otp_alert('r', [{'language': 'sl', 'text': 'Vozni red nadomestnega prevoza: Ljubljana - Borovnica in obratno'}]),
               otp_alert('d', [{'language': 'sl', 'text': 'DELA NA PROGI: Občasna zapora enega tira'}], start=NOW - 40),
               otp_alert('i', [{'language': 'sl', 'text': 'OBVESTILO: Dodatni prestop na postaji Ljubljana Zalog'}], start=NOW - 30)]
        self.assertEqual([a['kind'] for a in mapping.build_alerts(raw, 'sl', NOW)], ['replacement', 'closure', 'other'])


class JourneyHeadsignTests(SimpleTestCase):
    def test_route_style_headsign_keeps_its_destination(self):
        data = {'planConnection': {'edges': [{'node': {'walkTime': 0, 'legs': [leg('RAIL', '10:00:00', '10:30:00', trip='IJPP:1', headsign='Ljubljana - Ilirska Bistrica')]}}]}}
        [j] = journeys.build_journeys(data, request(), [])
        self.assertEqual(j['legs'][0]['headsign'], 'Ilirska Bistrica')
