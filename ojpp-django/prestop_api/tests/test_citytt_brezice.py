"""Brežice's posters (prestop_api/citytt/nomago_brezice.py): times typed from the two image-only posters, checked by hash."""
import tempfile

from django.test import SimpleTestCase

from prestop_api.citytt import CITIES, build, nomago_brezice

WINTER, SUMMER = list(nomago_brezice.POSTERS)


def tables(digest: str) -> dict:
    return {(t['line'], t['service']): t for t in (nomago_brezice.table(*x) for x in nomago_brezice.POSTERS[digest])}


class PosterTests(SimpleTestCase):
    def test_winter_runs_match_the_poster(self):
        t = tables(WINTER)
        modra = t[('1', 'D')]
        self.assertEqual([r[0] for r in modra['runs']], ['06:20', '06:40', '07:00', '07:20', '07:40', '08:00', '08:20', '13:00',
                                                          '13:20', '13:40', '14:00', '14:20', '14:40', '15:00', '15:20'])
        self.assertEqual(modra['runs'][0][-1], '06:39')
        self.assertEqual(modra['runs'][-1][9], '15:33')  # Cesta bratov Milavcev
        morning = t[('2', 'DS')]['runs']
        self.assertEqual(morning[0][:7], [None] * 6 + ['09:00'])  # the first from AP
        self.assertEqual(morning[0][-1], '09:19')
        self.assertEqual(morning[1][0], '10:00')
        self.assertEqual(morning[1][6], '10:08')
        self.assertEqual(morning[1][-1], '10:27')
        self.assertEqual(morning[3][15:], ['12:20', None, None, None])  # the last ends at Občina
        afternoon = t[('2', 'D')]['runs']
        self.assertEqual([r[6] for r in afternoon], ['16:00', '17:08', '18:08', '19:08'])
        self.assertEqual(afternoon[3][15], '19:20')

    def test_summer_runs_match_the_poster(self):
        t = tables(SUMMER)
        self.assertEqual([r[0] for r in t[('1', 'PD')]['runs']], ['06:40', '07:40', '15:00', '15:20', '16:00', '16:20'])
        self.assertEqual(len(t[('2', 'PDS')]['runs']), 4)
        self.assertEqual([(r[0], r[-1], r[15]) for r in t[('2', 'PD')]['runs']], [('17:00', '17:27', '17:20'), ('18:00', None, '18:20')])

    def test_a_changed_poster_is_a_problem(self):
        with tempfile.NamedTemporaryFile(suffix='.pdf') as f:
            f.write(b'%PDF-1.4 new poster')
            f.flush()
            with self.assertRaisesRegex(ValueError, 'the poster changed'):
                nomago_brezice.parse(f.name)


class CorrectionTests(SimpleTestCase):
    city = CITIES['Brezice']

    def test_both_lines_replace_otps(self):
        read = [nomago_brezice.table(*x) for d in (WINTER, SUMMER) for x in nomago_brezice.POSTERS[d]]
        out, problems = build.corrected(self.city, read)
        self.assertEqual(problems, [])
        self.assertEqual(len(out), 6)

    def test_school_year_and_summer_services_never_on_sundays(self):
        rows, _ = build.calendar(self.city, {'D', 'DS', 'PD', 'PDS'})
        self.assertEqual(sorted(r['service_id'] for r in rows), ['D', 'DS', 'PD', 'PDS'])
        self.assertTrue(all(r['sunday'] == '0' for r in rows))

    def test_printed_poles_outweigh_otps_patterns(self):
        """The posters number their stops (OTP's ids): Modra's return takes stadion 15 / gimnazija 16, though OTP's
        Zelena patterns (two runs) take 12 / 11 on the same road."""
        from prestop_api.citytt import poles
        self.assertEqual([len(p) for p in nomago_brezice.POLES], [len(nomago_brezice.MODRA), len(nomago_brezice.ZELENA)])
        at = lambda i, n: {'id': f'Brezice:{i}', 'name': n, 'lat': 45.9, 'lon': 15.59}  # noqa: E731
        all_poles, _ = poles.unify([at(14, 'Cesta bratov Milavcev'), at(12, 'Brežice stadion'), at(15, 'Brežice stadion'),
                                    at(11, 'Brežice gimnazija'), at(16, 'Brežice gimnazija'),
                                    at(17, 'Brežice Zdravstveni dom')], [])
        otp = [['Brezice:14', 'Brezice:12', 'Brezice:11', 'Brezice:17']] * 2 + [['Brezice:14', 'Brezice:15', 'Brezice:16', 'Brezice:17']]
        printed = poles.adjacent([[f'Brezice:{s}' for s in run] for run in nomago_brezice.POLES])
        pairs = poles.merged(poles.adjacent(otp), {k: build.PRINTED * v for k, v in printed.items()})
        chosen, problems = poles.choose(['Cesta bratov Milavcev', 'Brežice stadion', 'Brežice gimnazija',
                                         'Brežice Zdravstveni dom'], all_poles, pairs)
        self.assertEqual((chosen, problems), (['Brezice:14', 'Brezice:15', 'Brezice:16', 'Brezice:17'], []))
