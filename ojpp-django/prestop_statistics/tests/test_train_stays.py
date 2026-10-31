"""Staying on the train (train_stays.py, spec 2026-10-31 H5–H7): candidates, what a day says, levels, the gate, the
nightly record and relearn, and joined trains from SŽ's notices. A synthetic week: a real pair, a coincidence, a class
mismatch and a replaced day."""
from datetime import date, timedelta
from unittest import mock

from django.test import TestCase

from prestop_statistics import train_stays as ts
from prestop_statistics.models import RecorderDay, TrainCoverDay, TrainDay, TrainLinkDay, TrainStay

TODAY = date(2026, 11, 6)
H = 3600


def run(number, *stops, name=None):
    """stops: (name, arrival, departure) in s after midnight."""
    return {'number': number, 'name': name or f'RG {number}', 'trip': f'IJPP:{number}',
            'stops': [{'id': f'IJPP:{n.lower().replace(" ", "")}', 'name': n, 'arr': a, 'dep': d} for n, a, d in stops]}


RUNS = {r['number']: r for r in (
    # the real pair: 3295 ends at Ivančna Gorica 08:00, 3294 leaves from there 08:10
    run('3295', ('Ljubljana', 7 * H, 7 * H), ('Grosuplje', 7 * H + 1200, 7 * H + 1260), ('Ivančna Gorica', 8 * H, 8 * H)),
    run('3294', ('Ivančna Gorica', 8 * H + 600, 8 * H + 600), ('Grosuplje', 8 * H + 1800, 8 * H + 1860), ('Ljubljana', 9 * H, 9 * H)),
    # a coincidence: 500 ends at Maribor 10:00, 501 leaves at 10:15 with another set
    run('500', ('Celje', 9 * H, 9 * H), ('Maribor', 10 * H, 10 * H)),
    run('501', ('Maribor', 10 * H + 900, 10 * H + 900), ('Ptuj', 11 * H, 11 * H)),
    # a class mismatch: 700 ends at Jesenice 12:00, 701 leaves 12:08
    run('700', ('Kranj', 11 * H, 11 * H), ('Jesenice', 12 * H, 12 * H)),
    run('701', ('Jesenice', 12 * H + 480, 12 * H + 480), ('Kranj', 13 * H, 13 * H)),
    # too long a wait to be a candidate
    run('800', ('Koper', 6 * H, 6 * H), ('Divača', 7 * H, 7 * H)),
    run('801', ('Divača', 9 * H, 9 * H), ('Koper', 10 * H, 10 * H)),
)}


def stops(delays: list):
    return [{'id': 'x', 'name': 'x', 'delay': d} for d in delays]


def rollup(day, number, delays, **extra):
    TrainDay.objects.create(service_date=day, number=number, route_id='IJPP:r', trip_id=f'IJPP:{number}', stops=stops(delays), **extra)


class Candidates(TestCase):
    def test_turn_arounds_within_90_min(self):
        found = {(c['from'], c['to']) for c in ts.candidates(RUNS)}
        self.assertIn(('3295', '3294'), found)
        self.assertIn(('500', '501'), found)
        self.assertIn(('700', '701'), found)
        self.assertNotIn(('800', '801'), found)  # 2 h
        c = next(c for c in ts.candidates(RUNS) if c['from'] == '3295')
        self.assertEqual((c['arrival'], c['departure'], c['station_name']), (8 * H, 8 * H + 600, 'Ivančna Gorica'))

    def test_delays_near_the_ends(self):
        self.assertEqual(ts.end_delay(stops([60, 300, None])), 300)  # its last reported of the last three
        self.assertEqual(ts.start_delay(stops([None, 420, 480])), 420)  # SŽ rarely reports a train at its origin
        self.assertIsNone(ts.start_delay(stops([None, None, None, 300])))


class Outcome(TestCase):
    LINK = {'arrival': 8 * H, 'departure': 8 * H + 600}  # 10 min gap: slack 6 min with the 4 min turn

    def judge(self, a, b, **extra):
        return ts.outcome({**self.LINK, 'from_delay': a, 'to_delay': b, **extra})

    def test_cases(self):
        self.assertEqual(self.judge(900, 540), ts.AGREE)          # 15 min late - 6 slack = 9 expected, 9 seen
        self.assertEqual(self.judge(900, 0), ts.CONTRADICT)       # B left on time
        self.assertEqual(self.judge(900, 300), ts.CONTRADICT)     # clearly less late
        self.assertEqual(self.judge(900, 1500), ts.LATER)         # much later: its own reasons, says neither
        self.assertEqual(self.judge(0, 0), ts.SILENT)             # A on time says nothing
        self.assertEqual(self.judge(480, 0), ts.SILENT)           # slack absorbs a small delay: 2 min expected
        self.assertEqual(self.judge(None, 0), ts.NODATA)
        self.assertEqual(self.judge(900, 540, skipped='replaced'), ts.SKIPPED)

    def test_levels(self):
        self.assertEqual(ts.level([ts.AGREE] * 4, 4), 'sure')
        self.assertEqual(ts.level([ts.AGREE] * 3, 4), 'likely')
        self.assertEqual(ts.level([ts.AGREE] * 4 + [ts.CONTRADICT], 4), '')
        self.assertEqual(ts.level([ts.AGREE, ts.LATER, ts.LATER, ts.LATER], 4), '')  # later days are no evidence
        self.assertEqual(ts.level([ts.AGREE] * 6, None), 'likely')

    def test_tune_raises_min_days_until_no_sure_miss(self):
        d = [TODAY - timedelta(days=k) for k in range(10, 0, -1)]
        groups = {('1', '2'): [(d[i], ts.AGREE) for i in range(4)] + [(d[4], ts.CONTRADICT)],
                  ('3', '4'): [(d[i], ts.AGREE) for i in range(6)]}
        self.assertEqual(ts.tune(groups), 5)  # 4 agreeing days would have said `sure` before the contradiction
        self.assertEqual(ts.backtest(groups, 5)['sure'], {'predicted': 1, 'hits': 1})

    def test_a_train_going_on_as_two_gets_none(self):
        self.assertEqual(ts.unique({('1', '2'): 'sure', ('1', '3'): 'likely', ('4', '5'): 'likely'}), {('4', '5'): 'likely'})


class Week(TestCase):
    """Nine days before TODAY: 3295 is late on five of them and 3294 leaves late by that less the slack; 500 and 501
    are both late once for the same storm and otherwise 501 leaves on time; 700/701 agree but are planned in two
    series; one day 3294 was replaced by buses."""

    def setUp(self):
        self.days = [TODAY - timedelta(days=k) for k in range(9, 0, -1)]
        for i, day in enumerate(self.days):
            self.roll(day, i)

    @staticmethod
    def roll(day, i, late=None):
        RecorderDay.objects.create(day=day, feed='*', seconds=86000, version=2)
        late = i % 2 == 0 if late is None else late  # five late days for 3295
        rollup(day, '3295', [0, 300, 900 if late else 0])
        rollup(day, '3294', [None, 540 if late else 0, 560 if late else 0], replaced='part' if i == 2 else 'none')
        rollup(day, '500', [600, 1200])
        rollup(day, '501', [600 if i == 3 else 0, 600 if i == 3 else 0])
        rollup(day, '700', [0, 900])
        rollup(day, '701', [480, 480])
        rollup(day, '800', [0, 0])
        rollup(day, '801', [0, 0])

    def record_all(self, classes=None):
        for day in self.days:
            ts.record(day, RUNS, ts.rollups(day), classes)

    def test_learns_the_real_pair_only(self):
        classes = {'700': {'series': '312'}, '701': {'series': '813'}}
        self.record_all(classes)
        self.assertEqual(TrainCoverDay.objects.count(), 9)
        self.assertEqual(TrainLinkDay.objects.filter(skipped='class').count(), 9)
        self.assertEqual(TrainLinkDay.objects.filter(skipped='replaced', from_number='3295').count(), 1)
        summary = ts.learn(TODAY)
        stays = {(s.from_number, s.to_number): s for s in TrainStay.objects.all()}
        self.assertEqual(set(stays), {('3295', '3294')}, summary)
        stay = stays[('3295', '3294')]
        # 5 late days, one replaced: 4 agreeing days
        self.assertEqual((stay.level, stay.agree_days, stay.slack, stay.station_name), ('sure', 4, 360, 'Ivančna Gorica'))
        self.assertEqual(summary['backtest']['sure'], {'predicted': 0, 'hits': 0})

    def test_a_coincidence_is_not_learned(self):
        self.record_all()
        ts.learn(TODAY)
        self.assertFalse(TrainStay.objects.filter(from_number='500').exists())  # one storm day, then on time

    def test_gate_closed_learns_nothing(self):
        RecorderDay.objects.filter(day=self.days[4]).update(seconds=40000)  # a day the collector was down
        self.record_all()
        summary = ts.learn(TODAY)
        self.assertFalse(TrainStay.objects.exists())
        self.assertIsNone(summary['gate'])

    def test_a_sure_miss_is_logged_and_caps_the_pair(self):
        self.record_all()
        ts.learn(TODAY)
        self.assertEqual(TrainStay.objects.get(from_number='3295').level, 'sure')
        self.roll(TODAY, 1)
        TrainDay.objects.filter(service_date=TODAY, number__in=('3295', '3294')).delete()
        rollup(TODAY, '3295', [0, 0, 1200])
        rollup(TODAY, '3294', [0, 0, 0])
        with self.assertLogs('prestop_statistics.train_stays', 'WARNING'):
            check = ts.record(TODAY, RUNS, ts.rollups(TODAY))
        self.assertEqual(check['check']['sure'][1], 1)  # 3295/3294 missed (700/701, sure here too without classes, hit)
        ts.learn(TODAY + timedelta(days=1))
        self.assertFalse(TrainStay.objects.filter(from_number='3295').exists())  # a contradiction: none at all

    def test_nightly_backfills_the_stored_days_then_learns(self):
        from datetime import datetime
        at = datetime(TODAY.year, TODAY.month, TODAY.day, 5, 0, tzinfo=ts.blocks._tz()).timestamp()
        ts._nightly['day'] = None
        classes = {'700': {'series': '312'}, '701': {'series': '813'}}
        with mock.patch.object(ts, 'timetable', return_value=RUNS), mock.patch('prestop_api.zamudil.classes', return_value=classes),                 mock.patch.object(ts, 'joined_pairs', return_value=frozenset()):
            out = ts.nightly(at)
            self.assertIsNone(ts.nightly(at))  # once a night
        # yesterday, plus 7 of the 8 days before (BACKFILL a night): the gate opens on the 8 days in a row
        self.assertEqual(TrainCoverDay.objects.count(), 8)
        self.assertEqual(out['gate'], (TODAY - timedelta(days=1)).isoformat())
        # 3295/3294: 3 agreeing days stored so far. 700/701: zamudil keeps no class for past dates, so the backfilled
        # days count for it (holds() refuses it while today's classes differ).
        self.assertEqual({(s.from_number, s.level) for s in TrainStay.objects.all()}, {('3295', 'likely'), ('700', 'sure')})


NOTICE = ('Garnitura vlaka RG 619 iz Maribora se v Zidanem Mostu združi z garnituro vlaka RG 630 iz Dobove in nadaljuje vožnjo '
          'proti Ljubljani. Prestop potnikov iz vlaka RG 619 na vlak RG 630 za potovanje v smeri Ljubljane tako ni potreben.\n\n'
          'Garnitura vlaka RG 618 iz Ljubljane do Zidanega Mosta vozi združeno z garnituro vlaka RG 631 (Ljubljana - Zidani Most - '
          'Dobova). Na postaji Zidani Most se obe omenjeni garnituri ločita. Prva potuje v smeri Dobove (vlak RG 631), druga pa '
          'nadaljuje vožnjo v smeri Maribora (vlak RG 618). Prestop potnikov tako ni potreben, bodite pa pozorni na izbiro '
          'ustrezne garniture za želeno smer potovanja (prva garnitura: Smer Dobova, druga garnitura: Smer Maribor).\n\n'
          'Hvala za razumevanje.')
ZM = {r['number']: r for r in (
    run('619', ('Maribor', 4 * H, 4 * H), ('Celje', 5 * H, 5 * H), ('Zidani Most', 5 * H + 1620, 5 * H + 1620)),
    run('630', ('Dobova', 4 * H, 4 * H), ('Zidani Most', 5 * H + 1920, 5 * H + 2280), ('Ljubljana', 6 * H + 2100, 6 * H + 2100)),
    run('631', ('Ljubljana', 15 * H, 15 * H), ('Zidani Most', 16 * H + 1920, 16 * H + 2040), ('Dobova', 17 * H, 17 * H)),
    run('618', ('Zidani Most', 16 * H + 2400, 16 * H + 2400), ('Celje', 17 * H, 17 * H), ('Maribor', 17 * H + 3120, 17 * H + 3120)),
)}


class Joined(TestCase):
    def notices(self):
        data = {'notices': [{'summary': 'OBVESTILO: Združeni vlaki iz/do Zidanega Mosta (do nadaljnjega).', 'body': None, 'source': 'sz',
                             'trainNumbers': [619, 631, 632]},
                            {'summary': 'ZIDANI MOST - LJUBLJANA:', 'body': NOTICE, 'source': 'sz', 'trainNumbers': [619, 631, 632]}]}
        return mock.patch('prestop_api.zamudil.copy', return_value={'data': data}), mock.patch('prestop_api.zamudil.enabled', return_value=True)

    def test_parses_two_trains_per_paragraph_and_the_sets(self):
        from prestop_api import zamudil
        a, b = self.notices()
        with a, b:
            found = zamudil.joined_trains(TODAY)
        self.assertEqual([x['trains'] for x in found], [('619', '630'), ('618', '631')])
        self.assertEqual(found[0]['sets'], {})
        self.assertEqual(found[1]['sets'], {'dobova': 1, 'maribor': 2})

    def test_placed_on_the_timetable(self):
        a, b = self.notices()
        with a, b:
            links = ts.notice_links(TODAY, ZM)
        join, split = links
        self.assertEqual((join['from'], join['to'], join['kind'], join['station_name'], join['stretch']),
                         ('619', '630', 'join', 'Zidani Most', ('Zidani Most', 'Ljubljana')))
        self.assertEqual(join['part'], {})
        self.assertEqual((split['from'], split['to'], split['kind'], split['stretch']), ('631', '618', 'split', ('Ljubljana', 'Zidani Most')))
        self.assertEqual(split['part'], {'631': 1, '618': 2})  # only because the notice says so

    def test_train_page_and_journey(self):
        a, b = self.notices()
        with a, b, mock.patch.object(ts, '_runs', return_value=ZM), mock.patch.object(ts, 'table', return_value={'from': {}, 'to': {}}):
            page = ts.links_of('619', TODAY)
            split = ts.links_of('618', TODAY)
            self.assertEqual(ts.journey_level('619', '630', None, TODAY), 'sure')  # SŽ: no change needed
            self.assertIsNone(ts.journey_level('631', '618', None, TODAY))  # a split: the rider picks the set
        self.assertEqual(page['continuesAs'], {'number': '630', 'name': 'RG 630', 'station': 'Zidani Most', 'departure': 5 * H + 2280,
                                               'destination': 'Ljubljana', 'level': 'sure', 'kind': 'coupled'})
        self.assertEqual(page['coupledWith'], [{'number': '630', 'name': 'RG 630', 'from': 'Zidani Most', 'to': 'Ljubljana', 'source': 'notice'}])
        self.assertEqual(split['coupledWith'], [{'number': '631', 'name': 'RG 631', 'from': 'Ljubljana', 'to': 'Zidani Most', 'source': 'notice', 'part': 2}])
        self.assertNotIn('continuesAs', split)

    def test_timetable_coupling(self):
        runs = {'1': run('1', ('A', 0, 0), ('B', 600, 660), ('C', 1200, 1200)), '2': run('2', ('A', 30, 30), ('B', 630, 680), ('D', 1300, 1300))}
        self.assertEqual(ts.timetable_coupled(runs), [{'trains': ('1', '2'), 'from': 'A', 'to': 'B', 'source': 'timetable'}])
