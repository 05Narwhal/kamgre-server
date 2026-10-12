"""One operator per company (operators.py): normalized names, the alias table, ids rewritten at the API boundary."""
from unittest import mock

from django.test import SimpleTestCase

from prestop_api import operators, views

KNOWN = {
    'LPP:lpp': ('Ljubljanski Potniški Promet', 120), 'IJPP:1118': ('Ljubljanski potniški promet, d.o.o.', 30),
    'IJPP:1119': ('Nomago d.o.o.', 400), 'Postojna:Postojna': ('NOMAGO d.o.o.', 3),
    'IJPP:1121': ('AP Murska Sobota, d.d.', 50), 'MOMS:1121': ('Avtobusni promet Murska Sobota d.d.', 8),
    'IJPP:1161': ('SŽ - Potniški promet, d.o.o.', 700), 'bolt_359:bike': ('Bolt', 0), 'bolt_359:scooter': ('Bolt', 0),
}
ALIASES = {'MOMS:1121': ('IJPP:1121', 'AP Murska Sobota'), 'IJPP:1118': ('LPP:lpp', 'LPP')}


class NormalizeTests(SimpleTestCase):
    def test_names_lose_case_diacritics_and_legal_suffixes(self):
        self.assertEqual(operators.normalize('Ljubljanski potniški promet, d.o.o.'), 'ljubljanski potniski promet')
        self.assertEqual(operators.normalize('Ljubljanski Potniški Promet'), 'ljubljanski potniski promet')
        self.assertEqual(operators.normalize('NOMAGO d.o.o.'), 'nomago')
        self.assertEqual(operators.normalize('AP Murska Sobota, d.d.'), 'ap murska sobota')
        self.assertEqual(operators.normalize('SŽ - Potniški promet, d.o.o.'), 'sz potniski promet')
        self.assertEqual(operators.normalize('Arriva  d. o. o.'), 'arriva')


class BuildTests(SimpleTestCase):
    def test_same_names_merge_and_the_busiest_id_leads(self):
        t = operators.build(KNOWN, {})
        self.assertEqual(t['canonical']['Postojna:Postojna'], 'IJPP:1119')
        self.assertEqual(t['canonical']['IJPP:1118'], 'LPP:lpp')
        self.assertEqual(t['canonical']['MOMS:1121'], 'MOMS:1121')  # different names: only the alias table joins them
        self.assertEqual(t['sources']['IJPP:1119'], ['IJPP:1119', 'Postojna:Postojna'])

    def test_aliases_join_companies_and_pick_the_id_and_name(self):
        t = operators.build(KNOWN, ALIASES)
        self.assertEqual(t['canonical']['MOMS:1121'], 'IJPP:1121')
        self.assertEqual(t['names']['IJPP:1121'], 'AP Murska Sobota')
        # The target leads the merged group even when another id has more routes.
        t = operators.build({**KNOWN, 'IJPP:1118': ('Ljubljanski potniški promet, d.o.o.', 999)}, ALIASES)
        self.assertEqual((t['canonical']['IJPP:1118'], t['canonical']['LPP:lpp']), ('LPP:lpp', 'LPP:lpp'))

    def test_no_two_operators_share_a_normalized_name(self):
        t = operators.build(KNOWN, ALIASES)
        heads = set(t['canonical'].values())
        names = [operators.normalize(KNOWN[h][0]) for h in heads if h in KNOWN]
        self.assertEqual(len(names), len(set(names)))

    def test_the_alias_file_parses(self):
        rows = operators.read_aliases()
        self.assertEqual(rows['IJPP:1118'][0], 'LPP:lpp')
        self.assertTrue(all(':' in target for target, _ in rows.values()))


class ApiTests(SimpleTestCase):
    def setUp(self):
        self.patch = mock.patch.object(operators, 'table', return_value=operators.build(KNOWN, ALIASES))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_every_operator_id_in_a_payload_becomes_canonical(self):
        payload = {'items': [{'operatorId': 'IJPP:1118', 'geometry': [[14.5, 46.0]], 'stops': [{'operatorIds': ['IJPP:1118', 'LPP:lpp']}]},
                             {'providerId': 'bolt_359:bike'}, {'operatorId': 'IJPP:1161'}]}
        out = operators.rewrite(payload)
        self.assertEqual(out['items'][0]['operatorId'], 'LPP:lpp')
        self.assertEqual(out['items'][0]['stops'][0]['operatorIds'], ['LPP:lpp'])
        self.assertEqual(out['items'][1]['providerId'], 'bolt_359:bike')  # same name: Bolt's rows merge, the first id leads
        self.assertIs(out['items'][2], payload['items'][2])  # unchanged parts are not copied
        self.assertEqual(payload['items'][0]['operatorId'], 'IJPP:1118')  # cached values stay as they are

    def test_old_and_new_ids_filter_the_same_vehicles(self):
        vehicles = [{'operatorId': 'LPP:lpp'}, {'operatorId': 'IJPP:1118'}, {'operatorId': 'IJPP:1161'}]
        for op_id in ('LPP:lpp', 'IJPP:1118'):
            run_by = views.operator_filter(op_id)
            self.assertEqual(sum(run_by(v['operatorId']) for v in vehicles), 2)

    def test_capability_rows_merge_with_their_source_ids(self):
        rows = [{'id': 'LPP:lpp', 'name': 'Ljubljanski Potniški Promet', 'modes': ['bus']},
                {'id': 'IJPP:1118', 'name': 'Ljubljanski potniški promet, d.o.o.', 'modes': ['bus']},
                {'id': 'bolt_359:bike', 'name': 'Bolt', 'modes': ['bike']}, {'id': 'bolt_359:scooter', 'name': 'Bolt', 'modes': ['scooter']}]
        merged = {r['id']: r for r in operators.merge_rows(rows)}
        self.assertEqual(merged['LPP:lpp']['sourceIds'], ['IJPP:1118', 'LPP:lpp'])
        self.assertEqual(merged['LPP:lpp']['name'], 'LPP')
        self.assertEqual(len(merged), 2)
        bolt = next(r for r in merged.values() if r['name'] == 'Bolt')
        self.assertEqual(bolt['modes'], ['bike', 'scooter'])

    def test_journey_filters_reach_every_feed_of_the_company(self):
        self.assertEqual(sorted(operators.expand(['LPP:lpp'])), ['IJPP:1118', 'LPP:lpp'])
