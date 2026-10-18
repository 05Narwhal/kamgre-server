from unittest import mock

from django.test import SimpleTestCase

from prestop_api import journeys, mapping, sources

NOW = 1791557200  # 2026-10-09 15:26:40 UTC

ROUTES = {
    'LPP:r6': {'gtfsId': 'LPP:r6', 'shortName': '6', 'mode': 'BUS', 'agencyId': 'LPP:lpp'},
    'MARPROM:73': {'gtfsId': 'MARPROM:73', 'shortName': '6', 'mode': 'BUS', 'agencyId': 'MARPROM:3'},
}


def position(trip, vehicle_id, stamp=NOW - 20, **extra):
    return {'id': vehicle_id, 'vehicle': {'trip': {'tripId': trip, 'routeId': extra.pop('route', None)}, 'timestamp': str(stamp),
                                          'position': {'latitude': 46.05, 'longitude': 14.5, 'bearing': 370},
                                          'vehicle': {'id': vehicle_id, 'label': 'LJ 301'}, **extra}}


class VehicleTests(SimpleTestCase):
    def test_vehicle_gets_route_destination_and_delay_at_its_stop(self):
        updates = mapping.trip_update_index([{'tripUpdate': {'trip': {'tripId': 'LPP:t1'}, 'stopTimeUpdate': [
            {'stopSequence': 3, 'stopId': 'LPP:s3', 'arrival': {'delay': 60}},
            {'stopSequence': 4, 'stopId': 'LPP:s4', 'arrival': {'delay': 120}}]}}])
        [v] = mapping.build_vehicles([position('LPP:t1', 'LPP:bus-1', stopId='LPP:s4')], updates,
                                     {'LPP:t1': {'routeId': 'LPP:r6', 'destination': 'Črnuče'}}, ROUTES, {'LPP:s4': 'Bavarski dvor'}, NOW)
        self.assertEqual((v['routeName'], v['destination'], v['nextStop'], v['delaySeconds']), ('6', 'Črnuče', 'Bavarski dvor', 120))
        self.assertEqual((v['operatorId'], v['mode'], v['bearing']), ('LPP:lpp', 'bus', 10.0))

    def test_unknown_delay_stays_null(self):
        [v] = mapping.build_vehicles([position('LPP:t1', 'LPP:bus-1')], {}, {'LPP:t1': {'routeId': 'LPP:r6'}}, ROUTES, {}, NOW)
        self.assertIsNone(v['delaySeconds'])

    def test_stale_positions_are_dropped_and_bare_ids_qualified(self):
        stale = position('LPP:t1', 'LPP:old', stamp=NOW - 3600)
        bare = position('MARPROM:101750', '472', route='MARPROM:73')
        result = mapping.build_vehicles([stale, bare], {}, {}, ROUTES, {}, NOW)
        self.assertEqual([v['id'] for v in result], ['MARPROM:472'])
        self.assertEqual(result[0]['routeId'], 'MARPROM:73')


def stoptime(trip, first, last, dep=36000, rt=None, state='SCHEDULED'):
    return {'serviceDay': 1791496800, 'scheduledArrival': dep, 'scheduledDeparture': dep,
            'realtimeArrival': rt or dep, 'realtimeDeparture': rt or dep, 'realtime': rt is not None, 'realtimeState': state,
            'stopPosition': 2, 'pickupType': 'SCHEDULED', 'dropoffType': 'SCHEDULED', 'stop': {'platformCode': '3'},
            'trip': {'gtfsId': trip, 'route': {'gtfsId': 'IJPP:r1', 'shortName': 'RG 310', 'mode': 'RAIL', 'agency': {'gtfsId': 'IJPP:1161'}},
                     'departureStoptime': {'stop': {'gtfsId': first, 'name': 'Ljubljana'}},
                     'arrivalStoptime': {'stop': {'gtfsId': last, 'name': 'Jesenice'}}}}


class BoardTests(SimpleTestCase):
    def test_each_row_says_when_its_trip_starts(self):
        """A5: a row's "usually" is its own departure's, learned under the trip's start (aggregation.departure_delays)."""
        morning, evening = stoptime('IJPP:m', 'IJPP:x', 'IJPP:y'), stoptime('IJPP:e', 'IJPP:x', 'IJPP:y', dep=66000)
        morning['trip']['departureStoptime']['scheduledDeparture'] = 7 * 3600 + 600
        evening['trip']['departureStoptime']['scheduledDeparture'] = 18 * 3600 + 600
        rows = mapping.build_board('IJPP:s', [morning, evening, stoptime('IJPP:n', 'IJPP:x', 'IJPP:y')], 'departure', [])
        self.assertEqual([r.get('tripStart') for r in rows], ['07:10', '18:10', None])

    def test_departures_skip_terminating_trips_and_arrivals_skip_originating(self):
        here = 'IJPP:here'
        rows = [stoptime('IJPP:a', 'IJPP:x', 'IJPP:y'), stoptime('IJPP:ends', 'IJPP:x', here), stoptime('IJPP:starts', here, 'IJPP:y')]
        self.assertEqual([e['tripId'] for e in mapping.build_board(here, rows, 'departure', [])], ['IJPP:a', 'IJPP:starts'])
        arrivals = mapping.build_board(here, rows, 'arrival', [])
        self.assertEqual([e['tripId'] for e in arrivals], ['IJPP:a', 'IJPP:ends'])
        self.assertEqual(arrivals[0]['destination'], 'Ljubljana')  # arrivals show where the trip comes from

    def test_realtime_scheduled_and_canceled_entries(self):
        live, planned, canceled = mapping.build_board('IJPP:s', [
            stoptime('IJPP:1', 'IJPP:x', 'IJPP:y', rt=36300), stoptime('IJPP:2', 'IJPP:x', 'IJPP:y'),
            stoptime('IJPP:3', 'IJPP:x', 'IJPP:y', rt=36000, state='CANCELED')], 'departure', [])
        self.assertEqual((live['scheduledAt'], live['effectiveAt'], live['quality']), ('2026-10-09T08:00:00Z', '2026-10-09T08:05:00Z', 'predicted'))
        self.assertEqual((planned['effectiveAt'], planned['quality'], planned['platform']), (None, None, '3'))
        self.assertTrue(canceled['canceled'])
        self.assertIsNone(canceled['effectiveAt'])

    def test_route_alerts_flag_entries_inside_their_validity(self):
        departs = 1791496800 + 36000
        current = {'id': 'alert:now', 'stopIds': [], 'routeIds': ['IJPP:r1'], '_from': departs - 60, '_to': None}
        later = {'id': 'alert:later', 'stopIds': [], 'routeIds': ['IJPP:r1'], '_from': departs + 86400, '_to': departs + 2 * 86400}
        [entry] = mapping.build_board('IJPP:s', [stoptime('IJPP:1', 'IJPP:x', 'IJPP:y')], 'departure', [current, later])
        self.assertEqual(entry['alertIds'], ['alert:now'])


def otp_alert(id_, translations, start=NOW - 100, end=NOW + 100, entities=None):
    return {'id': id_, 'feed': 'IJPP', 'alertUrl': 'https://potniski.sz.si/inf', 'effectiveStartDate': start, 'effectiveEndDate': end,
            'alertHeaderTextTranslations': translations, 'alertDescriptionTextTranslations': [], 'agency': None,
            'entities': entities if entities is not None else [{'__typename': 'Route', 'gtfsId': 'IJPP:r1', 'agency': {'gtfsId': 'IJPP:1161'}}]}


class AlertTests(SimpleTestCase):
    def test_language_twins_keep_requested_language_and_single_language_alerts_stay(self):
        raw = [otp_alert('en', [{'language': 'en', 'text': 'Buses replace trains'}]),
               otp_alert('sl', [{'language': 'sl', 'text': 'Nadomestni avtobusi'}]),
               otp_alert('only-sl', [{'language': 'sl', 'text': 'Dela na progi'}], start=NOW - 50),
               otp_alert('both', [{'language': 'sl', 'text': 'Obvoz'}, {'language': 'en', 'text': 'Detour'}], start=NOW - 10)]
        self.assertEqual([a['title'] for a in mapping.build_alerts(raw, 'en', NOW)], ['Buses replace trains', 'Dela na progi', 'Detour'])
        self.assertEqual([a['title'] for a in mapping.build_alerts(raw, 'sl', NOW)], ['Nadomestni avtobusi', 'Dela na progi', 'Obvoz'])

    def test_expired_alerts_drop_and_entities_resolve(self):
        raw = [otp_alert('old', [{'language': 'en', 'text': 'x'}], end=NOW - 1),
               otp_alert('stop', [{'language': 'en', 'text': 'y'}], entities=[
                   {'__typename': 'StopOnRoute', 'stop': {'gtfsId': 'LPP:s'}, 'route': {'gtfsId': 'LPP:r', 'agency': {'gtfsId': 'LPP:lpp'}}}])]
        [alert] = mapping.build_alerts(raw, 'en', NOW)
        # A stop-on-route entity concerns that stop only, not every stop of the route.
        self.assertEqual((alert['id'], alert['stopIds'], alert['routeIds'], alert['operatorId']), ('alert:stop', ['LPP:s'], [], 'LPP:lpp'))
        self.assertNotIn('_aliases', mapping.public_alert(alert))

    def test_the_same_notice_per_stop_becomes_one_alert(self):
        detour = lambda id_, stop: otp_alert(id_, [{'language': 'en', 'text': 'Stop on detour'}], entities=[
            {'__typename': 'StopOnRoute', 'stop': {'gtfsId': stop}, 'route': {'gtfsId': 'LPP:r', 'agency': {'gtfsId': 'LPP:lpp'}}}])
        [alert] = mapping.build_alerts([detour('1', 'LPP:a'), detour('2', 'LPP:b')], 'en', NOW)
        self.assertEqual((alert['id'], alert['stopIds'], alert['_aliases']), ('alert:1', ['LPP:a', 'LPP:b'], ['alert:1', 'alert:2']))


    def test_sz_notices_on_lines_without_a_feed_route_are_szs(self):
        # Sežana - Opčine, Ljubljana - Villach: OTP ties the notice to no route or agency; it is SŽ's all the same.
        import base64
        sz_id = base64.b64encode(b'Alert:IJPP:SZ-OVIRA-11300').decode().rstrip('=')
        other = base64.b64encode(b'Alert:IJPP:OTHER-1').decode().rstrip('=')
        raw = [otp_alert(sz_id, [{'language': 'sl', 'text': 'Sežana - Opčine'}], entities=[]),
               otp_alert(other, [{'language': 'sl', 'text': 'Nekaj'}], start=NOW - 50, entities=[])]
        sz, unknown = mapping.build_alerts(raw, 'sl', NOW)
        self.assertEqual(sz['operatorId'], 'IJPP:1161')
        self.assertEqual(unknown['operatorId'], 'IJPP:unknown')

class RentalTests(SimpleTestCase):
    def test_car_sharing_is_not_a_bike(self):
        stations = [{'stationId': 'sharengo:1', 'network': 'sharengo', 'name': 'Car', 'lat': 46, 'lon': 14, 'vehiclesAvailable': 2},
                    {'stationId': '17', 'network': 'jcdecaux_ljubljana', 'name': 'Prešernov trg', 'lat': 46, 'lon': 14, 'vehiclesAvailable': 4,
                     'allowPickupNow': True, 'allowDropoffNow': True, 'availableVehicles': {'byType': [{'count': 4, 'vehicleType': {'formFactor': 'BICYCLE'}}]}}]
        scooters = [{'vehicleId': 'kvik:9', 'lat': 46, 'lon': 14, 'vehicleType': {'formFactor': 'SCOOTER_STANDING'}, 'rentalNetwork': {'networkId': 'kvik'}}]
        result = mapping.build_rentals(stations, scooters, NOW)
        self.assertEqual([(r['id'], r['mode'], r['providerId']) for r in result],
                         [('jcdecaux_ljubljana:17', 'bike', 'jcdecaux_ljubljana:bike'), ('kvik:9', 'scooter', 'kvik:scooter')])
        self.assertEqual(mapping.provider_name('jcdecaux_ljubljana:bike'), 'BicikeLJ')

    def test_a_free_floating_systems_stations_are_parking_zones(self):
        # Bolt: e-bikes and scooters left in zones, scooters also anywhere; a dock system's racks stay docks.
        stations = [{'stationId': 'bolt_359:z1', 'network': 'bolt_359', 'name': 'MOL - Situla', 'lat': 46, 'lon': 14, 'vehiclesAvailable': 0,
                     'allowPickupNow': True, 'allowDropoffNow': True, 'availableSpaces': {'byType': [{'count': 5, 'vehicleType': {'formFactor': 'BICYCLE'}}]}},
                    {'stationId': '17', 'network': 'jcdecaux_ljubljana', 'name': 'Prešernov trg', 'lat': 46, 'lon': 14, 'vehiclesAvailable': 4,
                     'spacesAvailable': 3, 'capacity': 7, 'allowPickupNow': True, 'allowDropoffNow': True}]
        scooter = lambda id_, lat: {'vehicleId': id_, 'lat': lat, 'lon': 14, 'vehicleType': {'formFactor': 'SCOOTER_STANDING'}, 'rentalNetwork': {'networkId': 'bolt_359'}}
        # One scooter stands in the zone (already in its count), one out on the street.
        zone, dock, street = mapping.build_rentals(stations, [scooter('bolt_359:in', 46.0002), scooter('bolt_359:out', 46.01)], NOW)
        self.assertEqual((zone.get('zone'), zone['canReturn'], zone['canPickup']), (True, True, False))
        self.assertNotIn('zone', dock)
        self.assertEqual(street['id'], 'bolt_359:out')


class GeometryTests(SimpleTestCase):
    def test_polyline_decodes_to_lon_lat(self):
        self.assertEqual(mapping.decode_polyline('_p~iF~ps|U_ulLnnqC_mqNvxq`@'), [[-120.2, 38.5], [-120.95, 40.7], [-126.453, 43.252]])

    def test_thin_keeps_ends(self):
        line = [[i, i] for i in range(1000)]
        thinned = mapping.thin(line, 100)
        self.assertEqual((len(thinned), thinned[0], thinned[-1]), (100, [0, 0], [999, 999]))


def leg(mode, start, end, transit=True, trip=None, interline=False, est=None, state='SCHEDULED', duration=None, headsign=None):
    when = lambda t: f'2026-10-09T{t}+02:00'
    return {'mode': mode, 'transitLeg': transit, 'interlineWithPreviousLeg': interline, 'realtimeState': state if transit else None,
            'duration': duration, 'start': {'scheduledTime': when(start), 'estimated': {'time': when(est)} if est else None},
            'end': {'scheduledTime': when(end), 'estimated': None},
            'from': {'name': 'A', 'lat': 46.0, 'lon': 14.5, 'stop': {'gtfsId': 'IJPP:a', 'platformCode': '2'} if transit else None},
            'to': {'name': 'B', 'lat': 46.1, 'lon': 14.4, 'stop': {'gtfsId': 'IJPP:b', 'platformCode': None} if transit else None},
            'route': {'gtfsId': 'IJPP:r', 'shortName': 'RG 1', 'mode': mode, 'agency': {'gtfsId': 'IJPP:bus' if mode == 'BUS' else 'IJPP:1161'}} if transit else None,
            'headsign': headsign, 'trip': {'gtfsId': trip, 'tripHeadsign': headsign} if trip else None, 'intermediatePlaces': [{'name': 'M'}] if transit else None, 'legGeometry': {'points': '_p~iF~ps|U_ulLnnqC'}, 'alerts': [{'id': 'X'}] if transit else []}


PLACE = {'name': 'Home', 'latitude': 46.0, 'longitude': 14.5, 'kind': 'address'}


class JourneyTests(SimpleTestCase):
    def request(self, **overrides):
        body = {'origin': PLACE, 'destination': {**PLACE, 'name': 'Bled'}, 'via': [], 'dateTime': '2026-10-09T10:00:00Z',
                'timeMode': 'departAt', 'minTransferSeconds': 180, 'modes': ['walk', 'bus', 'rail'], 'searchScope': 'all', 'riskMode': 'normal', **overrides}
        return journeys.parse_request(body, insane_enabled=False)

    def test_a_town_starts_and_ends_at_the_station_used_without_the_walk_from_between(self):
        town = {'name': 'Kranj', 'latitude': 46.05, 'longitude': 14.45, 'kind': 'station', 'stopId': 'IJPP:a', 'stopIds': ['IJPP:a', 'IJPP:ap']}
        walk_in, walk_out = leg('WALK', '09:55:00', '10:00:00', transit=False, duration=300), leg('WALK', '10:30:00', '10:36:00', transit=False, duration=360)
        walk_in['to']['stop'] = {'gtfsId': 'IJPP:a'}
        walk_out['from']['stop'] = {'gtfsId': 'IJPP:b'}
        data = {'planConnection': {'edges': [{'node': {'walkTime': 660, 'legs': [walk_in, leg('BUS', '10:00:00', '10:30:00', trip='IJPP:1'), walk_out]}}]}}
        req = self.request(origin=town, destination={**town, 'name': 'Bled', 'stopId': 'IJPP:b', 'stopIds': ['IJPP:b', 'IJPP:bap']})
        with mock.patch.object(sources, 'stop_group', side_effect=lambda s: [s]):
            self.assertEqual(journeys.otp_variables(req)['origin']['location'], {'coordinate': {'latitude': 46.05, 'longitude': 14.45}})
            [j] = journeys.build_journeys(data, req, [])
        self.assertEqual([l['mode'] for l in j['legs']], ['bus'])
        self.assertEqual((j['legs'][0]['origin']['name'], j['legs'][0]['destination']['name'], j['walkSeconds']), ('A', 'B', 0))
        self.assertEqual(j['effectiveDeparture'], '2026-10-09T10:00:00+02:00')
        with self.assertRaises(journeys.RequestError):
            self.request(origin={**town, 'stopIds': 'IJPP:a'})

    def test_a_town_keeps_journeys_through_another_stop_only_when_none_uses_its_stations(self):
        town = {'name': 'Kranj', 'latitude': 46.05, 'longitude': 14.45, 'kind': 'station', 'stopId': 'IJPP:a', 'stopIds': ['IJPP:a', 'IJPP:ap']}
        def walk_to(stop_id, start='09:55:00'):
            walk = leg('WALK', start, '10:00:00', transit=False, duration=300)
            walk['to']['stop'] = {'gtfsId': stop_id}
            return walk
        station = {'node': {'walkTime': 300, 'legs': [walk_to('IJPP:ap'), leg('BUS', '10:00:00', '10:30:00', trip='IJPP:1')]}}
        elsewhere = {'node': {'walkTime': 300, 'legs': [walk_to('IJPP:globus', '09:50:00'), leg('BUS', '10:00:00', '10:20:00', trip='IJPP:2')]}}
        req = self.request(origin=town)
        with mock.patch.object(sources, 'stop_group', side_effect=lambda s: [s]):
            kept = journeys.build_journeys({'planConnection': {'edges': [elsewhere, station]}}, req, [])
            alone = journeys.build_journeys({'planConnection': {'edges': [elsewhere]}}, req, [])
        self.assertEqual([j['legs'][0]['tripId'] for j in kept], ['IJPP:1'])
        self.assertEqual([j['legs'][0]['mode'] for j in alone], ['walk'])

    def test_transfer_statuses_use_walking_plus_safety(self):
        data = {'planConnection': {'edges': [{'node': {'walkTime': 300, 'legs': [
            leg('RAIL', '10:00:00', '10:30:00', trip='IJPP:1'),
            leg('WALK', '10:30:00', '10:32:00', transit=False, duration=120),
            leg('BUS', '10:34:00', '10:50:00', trip='IJPP:2', est='10:34:00'),  # 240 s available, 120 walk + 180 safety
            leg('BUS', '10:50:00', '11:10:00', trip='IJPP:2', interline=True),   # OTP's interline alone: still a change
        ]}}]}}
        merged = [{'id': 'alert:W', 'title': 'Replacement buses', 'routeIds': [], 'stopIds': [], 'operatorId': 'IJPP:1161',
                   '_from': 0, '_to': None, '_aliases': ['alert:W', 'alert:X']}]
        [j] = journeys.build_journeys(data, self.request(), merged)
        self.assertEqual(j['legs'][0]['alertIds'], ['alert:W'])
        self.assertEqual(j['transferCount'], 2)
        self.assertEqual(j['transfers'][0], {'requiredSeconds': 120, 'safetySeconds': 180, 'availableSeconds': 240, 'platform': '2', 'meetsSafetyMargin': False, 'status': 'tight',
                                             'legId': j['legs'][2]['id'],  # the leg boarded
                                             'walkSeconds': 120, 'walkKind': 'walk', 'rating': 'tight'})
        # Staying seated counts only once the vehicles were seen to do it (stays.py), so the through-run is timed.
        self.assertEqual((j['transfers'][1]['status'], j['transfers'][1]['legId'], j['legs'][3]['stayLevel']), ('tight', j['legs'][3]['id'], None))
        self.assertEqual((j['freshness'], j['notices'], j['legs'][0]['origin']['name'], j['legs'][-1]['destination']['name']), ('live', ['Replacement buses'], 'Home', 'Bled'))
        self.assertEqual((j['legs'][2]['delaySeconds'], j['legs'][0]['delaySeconds']), (0, None))
        self.assertEqual(j['legs'][0]['stopCount'], 2)
        self.assertNotIn('stopCount', j['legs'][1])  # walking

    def test_missed_and_canceled_transfers(self):
        data = {'planConnection': {'edges': [{'node': {'walkTime': 0, 'legs': [
            leg('RAIL', '10:00:00', '10:30:00', trip='IJPP:1'), leg('WALK', '10:30:00', '10:33:00', transit=False, duration=180),
            leg('BUS', '10:32:00', '10:50:00', trip='IJPP:2'), leg('BUS', '10:55:00', '11:10:00', trip='IJPP:3', state='CANCELED')]}}]}}
        [j] = journeys.build_journeys(data, self.request(), [])
        self.assertEqual([t['status'] for t in j['transfers']], ['missed', 'unknown'])

    def test_request_validation_and_otp_variables(self):
        with self.assertRaises(journeys.RequestError) as e:
            self.request(modes=['walk', 'bike'])
        self.assertEqual(e.exception.code, 'NO_MODES')
        with self.assertRaises(journeys.RequestError) as e:
            self.request(riskMode='insane')
        self.assertEqual(e.exception.code, 'FEATURE_UNAVAILABLE')
        with self.assertRaises(journeys.RequestError):
            self.request(dateTime='2026-10-09T10:00:00')
        via = {'name': 'Kranj', 'latitude': 46.24, 'longitude': 14.35, 'kind': 'station', 'stopId': 'IJPP:1122811'}
        v = journeys.otp_variables(self.request(via=[via], timeMode='arriveBy', minTransferSeconds=300, modes=['rail', 'bike']))
        self.assertEqual(v['via'], [{'visit': {'label': 'Kranj', 'minimumWaitTime': 'PT0S', 'stopLocationIds': ['IJPP:1122811']}}])
        self.assertEqual((v['preferences']['transit']['transfer'], list(v['dateTime'])), ({'slack': 'PT300S'}, ['latestArrival']))
        self.assertEqual(v['modes']['transit']['access'], ['WALK', 'BICYCLE_RENTAL'])
        # Rail only also takes SŽ's replacement buses (see test_replacement).
        self.assertEqual({m['mode'] for m in v['modes']['transit']['transit']}, {'RAIL', 'TRAM', 'SUBWAY', 'MONORAIL', 'FUNICULAR', 'BUS', 'COACH'})

    def test_operator_filter_and_insane_preferences(self):
        with self.assertRaises(journeys.RequestError):
            self.request(operators=['LPP'])
        body = {'origin': PLACE, 'destination': {**PLACE, 'name': 'Bled'}, 'via': [], 'dateTime': '2026-10-09T10:00:00Z', 'timeMode': 'departAt',
                'minTransferSeconds': 300, 'modes': ['walk', 'bus'], 'riskMode': 'insane', 'operators': ['IJPP:1118', 'IJPP:1118']}
        v = journeys.otp_variables(journeys.parse_request(body, insane_enabled=True))
        self.assertEqual(v['preferences']['transit'], {'transfer': {'slack': 'PT0S', 'cost': 0, 'maximumTransfers': 29, 'maximumAdditionalTransfers': 30}, 'filters': [{'include': [{'agencies': ['IJPP:1118', 'LPP:lpp']}]}]})  # every feed's id of LPP (operator_aliases.csv)
        self.assertEqual(v['preferences']['street'], {'walk': {'speed': journeys.INSANE_WALK_SPEED}})

    def test_leg_carries_the_line_headsign(self):
        data = {'planConnection': {'edges': [{'node': {'walkTime': 0, 'legs': [leg('BUS', '10:00:00', '10:20:00', trip='LPP:1', headsign='Ljubljana Vižmarje')]}}]}}
        [j] = journeys.build_journeys(data, self.request(), [])
        self.assertEqual(j['legs'][0]['headsign'], 'Ljubljana Vižmarje')

    def test_headsign_falls_back_to_trip_headsign_then_none(self):
        raw = leg('BUS', '10:00:00', '10:20:00', trip='LPP:1')
        raw['trip']['tripHeadsign'] = 'Črnuče'
        [j] = journeys.build_journeys({'planConnection': {'edges': [{'node': {'walkTime': 0, 'legs': [raw]}}]}}, self.request(), [])
        self.assertEqual(j['legs'][0]['headsign'], 'Črnuče')
        raw['trip']['tripHeadsign'] = '  '
        [j] = journeys.build_journeys({'planConnection': {'edges': [{'node': {'walkTime': 0, 'legs': [raw]}}]}}, self.request(), [])
        self.assertIsNone(j['legs'][0]['headsign'])


class MotionStateTests(SimpleTestCase):
    def test_same_place_for_twenty_seconds_is_stopped(self):
        self.assertEqual(mapping.motion_state([(100, 46.05, 14.5), (120, 46.05001, 14.50001)], None, None), (True, 100))

    def test_duplicate_timestamp_is_not_evidence(self):
        self.assertEqual(mapping.motion_state([(100, 46.05, 14.5), (100, 46.05, 14.5)], None, None), (False, None))

    def test_moving_clears(self):
        self.assertEqual(mapping.motion_state([(100, 46.05, 14.5), (120, 46.05, 14.5), (140, 46.0505, 14.5)], None, None), (False, None))

    def test_feed_status_and_speed_win(self):
        self.assertEqual(mapping.motion_state([(100, 46.05, 14.5)], None, 'STOPPED_AT')[0], True)
        self.assertEqual(mapping.motion_state([(100, 46.05, 14.5)], 0.2, None)[0], True)

    def test_too_short_a_span_is_not_evidence(self):
        self.assertEqual(mapping.motion_state([(100, 46.05, 14.5), (110, 46.05, 14.5)], None, None), (False, None))

    def test_standing_since_the_first_report_in_place(self):
        history = [(60, 46.04, 14.5), (100, 46.05, 14.5), (120, 46.05, 14.5), (140, 46.05001, 14.5)]
        self.assertEqual(mapping.motion_state(history, None, None), (True, 100))


class VehicleHistoryTests(SimpleTestCase):
    def test_vehicles_carry_stopped_since_from_consecutive_reports(self):
        history = mapping.MotionHistory()
        infos = {'LPP:t1': {'routeId': 'LPP:r6'}}
        [first] = mapping.build_vehicles([position('LPP:t1', 'LPP:bus-1', stamp=NOW - 40)], {}, infos, ROUTES, {}, NOW - 30, history=history)
        self.assertEqual((first['stopped'], first.get('stoppedSince')), (False, None))
        [v] = mapping.build_vehicles([position('LPP:t1', 'LPP:bus-1', stamp=NOW - 20)], {}, infos, ROUTES, {}, NOW, history=history)
        self.assertEqual((v['stopped'], v['stoppedSince']), (True, mapping.iso(NOW - 40)))

    def test_history_forgets_old_reports(self):
        history = mapping.MotionHistory()
        history.observe('v', 100, 46.05, 14.5, now=100)
        self.assertEqual(history.observe('v', 500, 46.05, 14.5, now=500), [(500, 46.05, 14.5)])
