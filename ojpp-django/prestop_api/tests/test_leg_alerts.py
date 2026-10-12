from datetime import date

from django.test import SimpleTestCase

from prestop_api import leg_alerts

T0 = 1_792_000_000


def alert(id, title='Notice', routes=(), stops=(), operator='IJPP:1161', start=T0 - 3600, end=T0 + 3600):
    return {'id': id, 'title': title, 'routeIds': list(routes), 'stopIds': list(stops), 'operatorId': operator, '_from': start, '_to': end}


LEG = {'routeId': 'IJPP:65041', 'operatorId': 'IJPP:1161', 'mode': 'rail', '_start': T0, '_end': T0 + 1800}
NAMES = {'ljubljana', 'ljubljana tivoli', 'medvode'}


class LegAlertTests(SimpleTestCase):
    def test_route_and_stop_entities_match(self):
        a = [alert('alert:r', routes=['IJPP:65041']), alert('alert:s', stops=['IJPP:medvode']), alert('alert:x', routes=['IJPP:1'])]
        self.assertEqual(leg_alerts.match(LEG, {'IJPP:medvode'}, NAMES, a), ['alert:r', 'alert:s'])

    def test_alert_outside_leg_time_is_ignored(self):
        a = [alert('alert:later', routes=['IJPP:65041'], start=T0 + 86400, end=T0 + 2 * 86400)]
        self.assertEqual(leg_alerts.match(LEG, set(), NAMES, a), [])

    def test_unknown_entity_alert_matches_by_station_names(self):
        a = [alert('alert:u', operator='IJPP:unknown', title='Vozni red nadomestnega prevoza: Ljubljana - Ljubljana Šiška in obratno.')]
        self.assertEqual(leg_alerts.match(LEG, set(), NAMES | {'ljubljana siska'}, a), ['alert:u'])
        self.assertEqual(leg_alerts.match(LEG, set(), {'celje', 'zidani most'}, a), [])

    def test_unknown_entity_alert_needs_the_leg_on_the_named_section(self):
        # Ljubljana → Borovnica only shares Ljubljana with "Ljubljana - Ljubljana Šiška": not on that section.
        a = [alert('alert:u', operator='IJPP:unknown', title='Vozni red nadomestnega prevoza: Ljubljana - Ljubljana Šiška in obratno.')]
        self.assertEqual(leg_alerts.match(LEG, set(), {'ljubljana', 'brezovica', 'borovnica'}, a), [])
        # "A / B - C / D": one station from each side is enough.
        b = [alert('alert:b', operator='IJPP:unknown', title='Vozni red nad. prevoza: Ljubljana / Lesce Bled - Jesenice / Beljak (A) in obratno.')]
        self.assertEqual(leg_alerts.match(LEG, set(), {'kranj', 'lesce bled', 'zirovnica', 'jesenice'}, b), ['alert:b'])
        self.assertEqual(leg_alerts.match(LEG, set(), {'ljubljana', 'kranj', 'lesce bled'}, b), [])

    def test_unknown_entity_alert_skips_other_operators_buses(self):
        a = [alert('alert:u', operator='IJPP:unknown', title='Vozni red nadomestnega prevoza: Ljubljana - Ljubljana Šiška in obratno.')]
        names = NAMES | {'ljubljana siska'}
        lpp = {**LEG, 'operatorId': 'LPP:lpp', 'mode': 'bus'}
        self.assertEqual(leg_alerts.match(lpp, set(), names, a), [])
        self.assertEqual(leg_alerts.match({**lpp, 'operatorId': 'IJPP:1161', 'replacement': True}, set(), names, a), ['alert:u'])

    def test_listed_days_limit_a_longer_validity(self):
        # T0 is 2026-10-14 19:46 in Ljubljana. The provider window spans the month; the title names the days.
        days = alert('alert:d', routes=['IJPP:65041'], title='Vozni red nadomestnega prevoza: Ljubljana - Borovnica in obratno (10., 11., 17., 24., 25. oktober).',
                     start=T0 - 6 * 86400, end=T0 + 11 * 86400)
        self.assertEqual(leg_alerts.match(LEG, set(), NAMES, [days]), [])
        one = {**days, 'id': 'alert:one', 'title': 'Vozni red nadomestnega prevoza: Ljubljana - Borovnica in obratno (14. oktober).'}
        self.assertEqual(leg_alerts.match(LEG, set(), NAMES, [one]), ['alert:one'])
        ranged = {**days, 'id': 'alert:r', 'title': 'Vozni red nad. prevoza: Ljubljana / Lesce Bled - Jesenice / Beljak (A) in obratno (12. - 18. 10.).'}
        self.assertEqual(leg_alerts.match(LEG, set(), NAMES, [ranged]), ['alert:r'])

    def test_title_days(self):
        self.assertEqual(leg_alerts.title_days('X: A - B in obratno (10., 11., 17., 24., 25. oktober).', 2026),
                         {date(2026, 10, d) for d in (10, 11, 17, 24, 25)})
        self.assertEqual(leg_alerts.title_days('X: A - B in obratno (22. oktober).', 2026), {date(2026, 10, 22)})
        self.assertEqual(leg_alerts.title_days('X: A - B in obratno (5. - 6. in 19. - 20. oktober).', 2026),
                         {date(2026, 10, d) for d in (5, 6, 19, 20)})
        self.assertIsNone(leg_alerts.title_days('X: A - B in obratno (12. - 18. 10.).', 2026))
        self.assertIsNone(leg_alerts.title_days('X: A - B in obratno (do 12. decembra).', 2026))

    def test_title_stations(self):
        self.assertEqual(leg_alerts.title_stations('Vozni red nad. prevoza: Ljubljana / Lesce Bled - Jesenice / Beljak (A) in obratno (12. - 18. 10.).'),
                         ['ljubljana', 'lesce bled', 'jesenice', 'beljak'])
        self.assertEqual(leg_alerts.title_stations('Zapora ceste'), [])

    def test_title_stations_after_the_last_colon(self):
        self.assertEqual(leg_alerts.title_stations('DODATNO: Avtobusni prevoz za vezo (NG-LJ): Lesce Bled - Bled Jezero in obratno (26.9. - 25.10.).'),
                         ['lesce bled', 'bled jezero'])

    def test_route_notice_for_another_section_of_the_line_is_ignored(self):
        # IC 509 runs Ljubljana - Koper; a rider to Borovnica is not concerned by Divača - Koper buses.
        far = alert('alert:far', routes=['IJPP:65041'], title='Vozni red nadomestnega prevoza: Divača - Koper in obratno (do 12. decembra).')
        near = alert('alert:near', routes=['IJPP:65041'], title='Vozni red nadomestnega prevoza: Ljubljana - Logatec in obratno (do 12. decembra).')
        plain = alert('alert:plain', routes=['IJPP:65041'], title='DELA NA PROGI: Prenova postaj Brezovica in Preserje.')
        self.assertEqual(leg_alerts.match(LEG, set(), {'ljubljana', 'brezovica', 'borovnica'}, [far, near, plain]), ['alert:near', 'alert:plain'])

    def test_english_titles_are_read_like_slovenian_ones(self):
        # Notices come in the rider's language (Accept-Language: en): sections, listed days and the replacement bus.
        far = alert('alert:far', routes=['IJPP:65041'], title='Buses replace trains: Divača - Koper and vice versa (14/12/2025 - 12/12/2026).')
        near = alert('alert:near', routes=['IJPP:65041'], title='Buses replace trains: Ljubljana - Logatec and vice versa (until 12 December).')
        days = alert('alert:d', routes=['IJPP:65041'], title='Buses replace trains: Ljubljana - Borovnica and vice versa (5 - 6 and 19 - 20 October).',
                     start=T0 - 13 * 86400, end=T0 + 11 * 86400)
        names = {'ljubljana', 'brezovica', 'borovnica'}
        self.assertEqual(leg_alerts.match(LEG, set(), names, [far, near, days]), ['alert:near'])
        bus = {'routeId': 'IJPP:bus', 'operatorId': 'IJPP:1161', 'mode': 'bus', 'replacement': True, '_start': T0, '_end': T0 + 1800}
        replacement = {**near, 'id': 'alert:bus', 'kind': 'replacement'}
        self.assertEqual(leg_alerts.match(bus, set(), names | {'logatec'}, [replacement]), ['alert:bus'])

    def test_english_title_days(self):
        self.assertEqual(leg_alerts.title_days('X: A - B and vice versa (10, 11, 17, 24, 25 October).', 2026),
                         {date(2026, 10, d) for d in (10, 11, 17, 24, 25)})
        self.assertEqual(leg_alerts.title_days('X: A - B and vice versa (5 - 6 and 19 - 20 October).', 2026),
                         {date(2026, 10, d) for d in (5, 6, 19, 20)})
        self.assertEqual(leg_alerts.title_days('X: A - B and vice versa (3 May).', 2026), {date(2026, 5, 3)})
        self.assertIsNone(leg_alerts.title_days('X: A - B and vice versa (until 12 December).', 2026))
        self.assertIsNone(leg_alerts.title_days('X: A - B and vice versa (14/12/2025 - 12/12/2026).', 2026))
