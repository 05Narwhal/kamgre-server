"""Operators' website notices (contract 6, source 'operator-site'): Arriva's posts as they read on 2026-10-14."""
from datetime import datetime

from django.test import SimpleTestCase

from prestop_api import operator_notices as notices
from prestop_api.operator_notices import LOCAL

NOW = datetime(2026, 10, 14, 15, 0, tzinfo=LOCAL).timestamp()


def post(pid, when, title, text):
    return {'id': pid, 'date': when, 'link': f'https://arriva.si/{pid}/', 'title': {'rendered': title}, 'content': {'rendered': f'<p>{text}</p>'}}


POSTS = [
    post(1, '2026-10-13T14:54:48', 'Popolna zapora ceste Zaboršt&#8211;Ihan, 16.–17. 10. 2026',
         'Spoštovani potniki, obveščamo vas, da bo zaradi gradbenih del od petka, 16. 10. 2026, od 7.00 do sobote, 17. 10. 2026, '
         'do 17.00 popolnoma zaprt del ceste Zaboršt – Ihan. Avtobusi bodo vozili po obvozu.'),
    post(2, '2026-10-14T13:42:15', 'Zapora ceste v Škofji Loki: spremembe avtobusnega prometa 15. oktobra 2026',
         'Spoštovani potniki, v četrtek, 15. oktobra 2026, med 13. in 22. uro bo cesta zaprta.'),
    post(3, '2026-10-09T16:01:30', 'Na Kostanov piknik v Besnico brezplačno z avtobusom', 'Tradicionalni piknik 11. in 18. oktobra 2026.'),
    post(4, '2026-10-01T10:00:00', 'Zapora ceste v Kamniku 3. 10. 2026', 'Zaprta cesta 3. 10. 2026.'),  # over
    post(5, '2026-10-14T09:00:00', 'Sprememba odhoda ob 5:55 na relaciji Koper–Ljubljana', 'Obveščamo vas o spremembi.'),
]
BY_PLACE = {'zaborst': {'IJPP:a1', 'IJPP:a2'}, 'ihan': {'IJPP:a1'}, 'koper': {'IJPP:k1'}, 'ljubljana': {f'IJPP:l{i}' for i in range(40)} | {'IJPP:k1'},
            'skofja': {'IJPP:s1', 'IJPP:s2'}}


class ArrivaTests(SimpleTestCase):
    def setUp(self):
        self.alerts = {a['id']: a for a in notices.arriva_alerts(POSTS, 'IJPP:arriva', BY_PLACE, now=NOW)}

    def test_notices_of_service_changes_are_kept_offers_and_past_ones_not(self):
        self.assertEqual(sorted(self.alerts), ['arriva:1', 'arriva:2', 'arriva:5'])

    def test_contract_6_fields(self):
        a = self.alerts['arriva:1']
        self.assertEqual((a['source'], a['kind'], a['operatorId'], a['sourceUrl']), ('operator-site', 'detour', 'IJPP:arriva', 'https://arriva.si/1/'))
        self.assertEqual(a['title'], 'Popolna zapora ceste Zaboršt–Ihan, 16.–17. 10. 2026')
        self.assertEqual((a['from'], a['to']), ('2026-10-15T22:00:00Z', '2026-10-17T21:59:00Z'))
        self.assertNotIn('<', a['message'])
        self.assertEqual(self.alerts['arriva:2']['kind'], 'closure')
        self.assertEqual(self.alerts['arriva:2']['from'], '2026-10-14T22:00:00Z')  # 15 October, written out

    def test_routes_from_the_places_the_title_names(self):
        self.assertEqual(self.alerts['arriva:1']['routeIds'], ['IJPP:a1'])  # passes both Zaboršt and Ihan
        self.assertEqual(self.alerts['arriva:5']['routeIds'], ['IJPP:k1'])
        self.assertEqual(self.alerts['arriva:2']['routeIds'], ['IJPP:s1', 'IJPP:s2'])
        self.assertEqual(notices.match_routes('Ljubljanski maraton v Ljubljana', BY_PLACE), [])  # a hub alone picks nothing

    def test_a_notice_without_a_day_lasts_a_week_from_posting(self):
        start, end = notices.window('Sprememba odhoda', 'Obveščamo vas.', datetime(2026, 10, 14, 9, tzinfo=LOCAL))
        self.assertEqual(round((end - start) / 86400), 7)
