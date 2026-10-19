from unittest import mock

from django.test import SimpleTestCase

from prestop_api import places, scheduled, stopgroups, sz


def stop(id_, name, lat, lon, modes=('bus',), operators=('X:1',)):
    return {'id': id_, 'name': name, 'latitude': lat, 'longitude': lon, 'modes': list(modes), 'operatorId': operators[0],
            'operatorIds': list(operators), 'parentId': None, 'platform': None}


class StopGroupTests(SimpleTestCase):
    def test_the_same_stop_from_two_feeds_becomes_one(self):
        merged, groups = stopgroups.merge([
            stop('IJPP:1121237', 'Kranj AP', 46.24597, 14.35471, operators=('IJPP:arriva',)),
            stop('MOKranj:112', 'Kranj AP', 46.24597, 14.35471, operators=('MOKranj:mp',)),
            stop('IJPP:1121246', 'Kranj Globus', 46.24197, 14.35546),
        ])
        self.assertEqual([s['id'] for s in merged], ['IJPP:1121237', 'IJPP:1121246'])
        self.assertEqual(merged[0]['memberIds'], ['IJPP:1121237', 'MOKranj:112'])
        self.assertEqual(merged[0]['operatorIds'], ['IJPP:arriva', 'MOKranj:mp'])
        self.assertEqual(groups['MOKranj:112'], ['IJPP:1121237', 'MOKranj:112'])

    def test_opposite_sides_of_one_feed_and_far_namesakes_stay_apart(self):
        merged, groups = stopgroups.merge([
            stop('IJPP:a', 'Kranj Primskovo', 46.24654, 14.36373),
            stop('IJPP:b', 'Kranj Primskovo', 46.24600, 14.36439),   # other side, ~80 m
            stop('MOKranj:c', 'Kranj Primskovo', 46.2500, 14.3700),  # same name, ~500 m away
        ])
        self.assertEqual(len(merged), 3)
        self.assertEqual(groups, {})

    def test_both_sides_of_a_road_with_city_twins_stay_two_stops(self):
        merged, _ = stopgroups.merge([
            stop('IJPP:1', 'Kranj AP', 46.24597, 14.35471), stop('IJPP:2', 'Kranj AP', 46.24582, 14.35453),
            stop('MOKranj:112', 'Kranj AP', 46.24597, 14.35471), stop('MOKranj:81', 'Kranj AP', 46.24582, 14.35453),
        ])
        self.assertEqual(sorted(len(s.get('memberIds', [s['id']])) for s in merged), [2, 2])

    def test_a_rail_station_heads_its_group(self):
        merged, _ = stopgroups.merge([stop('X:bus', 'Lesce-Bled', 46.3601, 14.1503), stop('IJPP:rail', 'Lesce-Bled', 46.3602, 14.1503, modes=('rail',))])
        self.assertEqual(merged[0]['id'], 'IJPP:rail')
        self.assertEqual(merged[0]['modes'], ['bus', 'rail'])


class PlaceSearchTests(SimpleTestCase):
    def photon(self, name, key, value, street=None, number=None, city='Kranj', lat=46.24, lon=14.35, osm_id=1):
        return {'geometry': {'coordinates': [lon, lat]}, 'properties': {'name': name, 'osm_key': key, 'osm_value': value, 'street': street,
                                                                        'housenumber': number, 'city': city, 'osm_type': 'N', 'osm_id': osm_id, 'countrycode': 'SI'}}

    def test_categories_from_tags_and_brands(self):
        self.assertEqual(places.category_for('shop', 'supermarket', 'Hofer'), 'supermarket')
        self.assertEqual(places.category_for('building', 'yes', 'Hofer'), 'supermarket')
        self.assertEqual(places.category_for('amenity', 'fuel', 'Petrol'), 'fuel')
        self.assertEqual(places.category_for(None, None, 'Lekarna Bavarski dvor'), 'pharmacy')
        self.assertIsNone(places.category_for(None, None, 'Something'))

    def test_photon_results_carry_a_detail_line_and_skip_transit_stops(self):
        hofer = places.from_photon(self.photon('Hofer', 'shop', 'supermarket', 'Smledniška cesta', '27h'))
        self.assertEqual((hofer['name'], hofer['detail'], hofer['category'], hofer['kind']), ('Hofer', 'Smledniška cesta 27h, Kranj', 'supermarket', 'poi'))
        self.assertIsNone(places.from_photon(self.photon('Bolnišnica', 'highway', 'bus_stop')))
        house = places.from_photon(self.photon(None, 'place', 'house', 'Prešernova ulica', '5'))
        self.assertEqual((house['name'], house['kind']), ('Prešernova ulica 5', 'address'))

    def test_merge_drops_duplicates_and_ranks_nearer_matches_first(self):
        far = places.from_photon(self.photon('Hofer', 'shop', 'supermarket', city='Maribor', lat=46.55, lon=15.64, osm_id=2))
        near = places.from_photon(self.photon('Hofer', 'shop', 'supermarket', 'Žitna ulica', '1', osm_id=3))
        dup = {**near, 'id': 'pelias:x', 'detail': 'Kranj'}
        result = places.merge('hofer', [far, near], [dup], near=(46.24, 14.35), limit=5)
        self.assertEqual([p['id'] for p in result], [near['id'], far['id']])

    def test_one_geocoder_failing_still_answers(self):
        with mock.patch.object(places, '_photon', side_effect=places.UpstreamError('down')), \
                mock.patch.object(places, '_pelias', return_value=[{'id': 'pelias:1', 'name': 'Bled', 'detail': None, 'category': 'town', 'kind': 'address', 'latitude': 46.37, 'longitude': 14.11}]):
            self.assertEqual([p['name'] for p in places.geocode('bled', 5, 'sl')], ['Bled'])


class SzLiveTests(SimpleTestCase):
    T0 = 1_760_000_000

    def test_train_numbers_and_categories(self):
        self.assertEqual(sz.train_parts('LPV 2904'), ('LPV', '2904'))
        self.assertEqual(sz.train_parts('ICS 503'), ('ICS', '503'))
        self.assertEqual(sz.train_parts('4292'), (None, '4292'))
        self.assertEqual(sz.train_parts('N5'), ('N', '5'))

    def test_feed_records_are_normalized_with_or_without_coordinates(self):
        plain = sz.normalize({'st_vlaka': '2904', 'rang_vlaka': 'LPV', 'naslednja_postaja': 'Kranj', 'zamuda_min': 4}, self.T0)
        self.assertEqual((plain['number'], plain['category'], plain['delay'], plain['coords']), ('2904', 'LPV', 240, None))
        placed = sz.normalize({'st_vlaka': 503, 'zamuda_min': '0', 'Koordinate': ['14.51', '46.06']}, self.T0)
        self.assertEqual(placed['coords'], (46.06, 14.51))
        self.assertIsNone(sz.normalize({'zamuda_min': 3}, self.T0))

    def test_a_late_train_moves_by_its_delay_but_never_past_its_next_station(self):
        trip = {'arrivals': [self.T0, self.T0 + 600, self.T0 + 1200], 'departures': [self.T0, self.T0 + 660, self.T0 + 1200],
                'stops': [{'name': 'A'}, {'name': 'B'}, {'name': 'C'}]}
        shape = {'distances': [0.0, 5000.0, 9000.0]}
        # 5 min late, half-way to B by its shifted timetable.
        at = scheduled.live_locate(trip, shape, {'delay': 300, 'next': 'B'}, self.T0 + 600)
        self.assertAlmostEqual(at['distance'], 2500)
        # The shifted timetable says it passed B, but the feed says B is still next: wait before B.
        at = scheduled.live_locate(trip, shape, {'delay': 0, 'next': 'B'}, self.T0 + 900)
        self.assertEqual((at['distance'], at['stop']), (5000.0, 1))

    def test_vehicles_use_live_reports_and_label_them(self):
        trip = {'id': 'IJPP:t1', 'pattern': 'p', 'headsign': None, 'delays': [None, None, None],
                'arrivals': [self.T0, self.T0 + 600, self.T0 + 1200], 'departures': [self.T0, self.T0 + 660, self.T0 + 1200],
                'route': {'gtfsId': 'IJPP:r1', 'shortName': 'LPV 2904', 'agency': {'gtfsId': 'IJPP:1161'}},
                'stops': [{'gtfsId': f'IJPP:s{i}', 'name': f'S{i}', 'lat': 46.05, 'lon': 14.5 + i * 0.05} for i in range(3)]}
        from prestop_api import geometry
        coords = [[14.5, 46.05], [14.6, 46.05]]
        shape = {'coords': coords, 'cum': geometry.cumulative(coords), 'distances': [0.0, 3850.0, 7700.0]}
        with mock.patch.object(scheduled.timetable, 'get', return_value=mock.Mock(value=[trip])), \
                mock.patch.object(scheduled.shapes, 'get', return_value=mock.Mock(value={'p': shape})), \
                mock.patch.object(scheduled.tracks.tracks, 'track', return_value=('3', True)) as track:
            [train] = scheduled.vehicles(self.T0 + 300, live={'2904': {'number': '2904', 'category': 'LPV', 'delay': 120, 'next': 'S1', 'coords': None, 'at': self.T0 + 290}})
            [timetable] = scheduled.vehicles(self.T0 + 300, live={})
            trip['delays'] = [60, 60, 60]  # OTP realtime from the feed
            [realtime] = scheduled.vehicles(self.T0 + 300, live={})
        self.assertEqual((train['quality'], train['delaySeconds'], train['trainCategory'], train['trainNumber']), ('inferred', 120, 'LPV', '2904'))
        # C0: where the delay comes from, and the track at the next station (S1, at its timetable departure).
        self.assertEqual((train['delaySource'], train['nextPlatform'], train['nextPlatformUsual']), ('sz', '3', True))
        track.assert_called_with('LPV 2904', 'IJPP:s1', self.T0 + 660)
        self.assertEqual((timetable['quality'], timetable['delaySeconds'], 'delaySource' in timetable), ('scheduled', None, False))
        self.assertEqual((realtime['quality'], realtime['delaySeconds'], realtime['delaySource']), ('scheduled', 60, 'gtfs-rt'))
