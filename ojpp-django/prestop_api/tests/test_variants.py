"""Route variants (contract 4): same operator, ends and direction -> one group; `via` tells the variants apart."""
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import variants

# Tržič - Ljubljana as IJPP had it on 2026-10-14 (A6260 via Kovor, A6261 also via Naklo, A6265 via Duplje).
KOVOR = ['Tržič', 'Tržič Peko', 'Bistrica pri Tržiču', 'Bistrica pri Trž.bloki', 'Loka/Tržiču', 'Kovor', 'Zvirče',
         'Ljubljana Šentvid', 'Ljubljana Trata', 'Ljubljana Slovenija avto', 'Ljubljana Kino Šiška', 'Ljubljana Tivoli', 'Ljubljana AP']
NAKLO = ['Ljubljana AP', 'Ljubljana Tivoli', 'Ljubljana Kino Šiška', 'Ljubljana Remiza', 'Ljubljana Trata', 'Ljubljana Šentvid',
         'Naklo/Kr.', 'Zvirče', 'Kovor', 'Loka/Tržiču', 'Bistrica pri Trž.bloki', 'Bistrica pri Tržiču', 'Tržič Peko', 'Tržič']
DUPLJE = ['Ljubljana AP', 'Ljubljana Tivoli', 'Ljubljana Kino Šiška', 'Ljubljana Remiza', 'Ljubljana Trata', 'Ljubljana Šentvid',
          'Naklo/Kr.', 'Strahinj posestvo', 'Žeje', 'Duplje/Trž.', 'Zadraga', 'Žiganja vas', 'Sebenje/Trž.', 'Križe/Trž.K',
          'Pristava/Trž.', 'Preska pri Tržiču', 'Tržič']
ELSEWHERE = ['Kranj AP', 'Kranj Primskovo', 'Šenčur']


def network():
    routes, patterns, names = {}, [], {}
    for rid, stops, op in (('IJPP:65303', KOVOR, 'arriva'), ('IJPP:66508', NAKLO, 'arriva'), ('IJPP:66536', DUPLJE, 'arriva'),
                           ('IJPP:67010', list(reversed(DUPLJE)), 'arriva'),  # the same variant, the other way
                           ('IJPP:9', KOVOR, 'nomago'), ('IJPP:10', ELSEWHERE, 'arriva')):
        routes[rid] = {'gtfsId': rid, 'agencyId': op, 'mode': 'BUS'}
        ids = [f'{rid}:{i}' for i in range(len(stops))]
        names.update(zip(ids, stops))
        patterns.append({'routeId': rid, 'stops': ids})
    return routes, patterns, names


class VariantTests(SimpleTestCase):
    def test_trzic_ljubljana_variants_are_one_group_per_direction_told_apart_by_via(self):
        out = variants.build(*network())
        to_ljubljana = {out[r]['groupId'] for r in ('IJPP:65303', 'IJPP:67010')}
        to_trzic = {out[r]['groupId'] for r in ('IJPP:66508', 'IJPP:66536')}
        self.assertEqual(len(to_ljubljana), 1)
        self.assertEqual(len(to_trzic), 1)
        self.assertNotEqual(to_ljubljana, to_trzic)  # opposite directions never merge
        self.assertEqual(out['IJPP:66536']['via'], 'Žeje')
        self.assertEqual(out['IJPP:67010']['via'], 'Žeje')
        self.assertEqual(out['IJPP:65303']['via'], 'Zvirče')
        self.assertEqual(out['IJPP:66508']['via'], 'Zvirče')
        self.assertTrue(out['IJPP:66536']['groupId'].startswith('g:'))

    def test_another_operator_or_other_ends_are_another_group_without_via(self):
        out = variants.build(*network())
        self.assertNotEqual(out['IJPP:9']['groupId'], out['IJPP:65303']['groupId'])
        self.assertIsNone(out['IJPP:9']['via'])
        self.assertIsNone(out['IJPP:10']['via'])

    def test_siblings_list_the_group(self):
        routes, patterns, names = network()
        table = variants.build(routes, patterns, names)
        with mock.patch.object(variants, 'table', return_value=table), \
                mock.patch('prestop_api.sources.routes.peek', return_value=mock.Mock(value={r: {**v, 'shortName': r[-2:]} for r, v in routes.items()})):
            rows = variants.siblings('IJPP:66536')
            self.assertEqual([r['routeId'] for r in rows], ['IJPP:66508', 'IJPP:66536'])
            self.assertEqual(rows[1], {'routeId': 'IJPP:66536', 'via': 'Žeje', 'name': '36'})
            self.assertEqual(variants.siblings('IJPP:unknown'), [])
            self.assertIsNone(variants.of('IJPP:unknown')['via'])

    def test_variants_with_different_stops_never_share_a_label(self):
        # Ljubljana - Bohinj as IJPP had it on 2026-10-14: A6346 is A6345 plus one school stop, A6345 listed twice.
        way = ['Ljubljana AP', 'Medvode', 'Meja/Kr.', 'Kranj AP', 'Bled', 'Bohinjska Bistrica', 'Bohinj Ukanc']
        school = way[:6] + ['Bohinjska Bistrica OŠ'] + way[6:]
        polica = ['Ljubljana AP', 'Polica', 'Kranj AP', 'Bled', 'Bohinjska Bistrica', 'Bohinj Ukanc']
        routes, patterns, names = {}, [], {}
        for rid, stops in (('IJPP:66503', way), ('IJPP:67004', way), ('IJPP:66504', school), ('IJPP:66513', polica)):
            routes[rid] = {'gtfsId': rid, 'agencyId': 'arriva', 'mode': 'BUS'}
            ids = [f'{rid}:{i}' for i in range(len(stops))]
            names.update(zip(ids, stops))
            patterns.append({'routeId': rid, 'stops': ids})
        out = variants.build(routes, patterns, names)
        self.assertEqual(out['IJPP:66503']['via'], out['IJPP:67004']['via'])  # the same variant listed twice
        labels = [out[r]['via'] for r in ('IJPP:66503', 'IJPP:66504', 'IJPP:66513')]
        self.assertEqual(len(set(labels)), 3, labels)
        self.assertEqual(out['IJPP:66504']['via'], f"{out['IJPP:66503']['via']}, Bohinjska Bistrica OŠ")
