"""Staying on the same vehicle, learned from the recorder (stays.py): the gate, origins, levels, the live check."""
from datetime import date, datetime, timedelta, timezone as tz

from django.test import TestCase
from django.utils import timezone

from prestop_statistics import stays
from prestop_statistics.models import RecorderDay, StayCheck, StayDeparture, VehicleGap, VehicleTrip

TODAY = date(2026, 10, 23)  # a Friday
H = 3600
A, B = 7 * H, 7 * H + 50 * 60  # line A's 07:00 (ends 07:40), then line B's 07:50 from the same stop
TERMINUS = (46.05, 14.50)
DEPOT = (46.08, 14.55)


def workdays(n: int, before: date = TODAY) -> list[date]:
    out, day = [], before
    while len(out) < n:
        day -= timedelta(days=1)
        if day.weekday() < 5:
            out.append(day)
    return sorted(out)


def complete(*days: date, feed: str = 'IJPP', seconds: int = 86000):
    for day in days:
        RecorderDay.objects.update_or_create(day=day, feed='*', defaults={'seconds': seconds, 'version': 2})
        RecorderDay.objects.update_or_create(day=day, feed=feed, defaults={'seconds': 50000, 'version': 2})


def trip(day, trip_id, vehicle, route, start, end, pattern='p1', start_delay=None, end_delay=None):
    seen = timezone.now()
    return VehicleTrip.objects.create(service_date=day, trip_id=trip_id, vehicle_id=vehicle, route_id=route, start=start, end=end,
                                      end_delay=end_delay, start_delay=start_delay, pattern=pattern, version=2, first_seen=seen, last_seen=seen)


def gap(day, vehicle, after, before, far=50, unseen=0, seen=10, idle=()):
    return VehicleGap.objects.create(service_date=day, vehicle_id=vehicle, after_trip_id=after, before_trip_id=before,
                                     ended=datetime(2026, 10, 1, tzinfo=tz.utc), max_distance=far, unseen_polls=unseen, seen_polls=seen, idle=list(idle))


def day_of(day, vehicle='IJPP:v1', b_vehicle=None, b_pattern='p1', fresh=None, b_start_delay=None, a_end_delay=None):
    """Line A's 07:00 then line B's 07:50 on `day`; B on the same vehicle unless `b_vehicle`; `fresh`: the gap's GPS."""
    a = trip(day, f'IJPP:a-{day}', vehicle, 'IJPP:A', A, A + 40 * 60, end_delay=a_end_delay)
    b = trip(day, f'IJPP:b-{day}', b_vehicle or vehicle, 'IJPP:B', B, B + 40 * 60, pattern=b_pattern, start_delay=b_start_delay)
    if not b_vehicle:
        gap(day, vehicle, a.trip_id, b.trip_id, **(fresh or {}))


def learned(day=TODAY) -> dict:
    stays.learn(day)
    return {(r.route_id, r.start): r for r in StayDeparture.objects.filter(kind='workday')}


class GateTests(TestCase):
    def test_nothing_before_seven_consecutive_complete_days(self):
        days = [TODAY - timedelta(days=i) for i in range(1, 15)]
        for d in days:
            if d.weekday() < 5:
                day_of(d)
        complete(*days[:6])
        self.assertEqual(learned(), {})  # six full days: nothing at all, not even "likely"
        complete(days[6])
        self.assertEqual(learned()[('IJPP:B', B)].level, 'sure')

    def test_a_day_the_collector_ran_under_95_percent_does_not_count(self):
        days = [TODAY - timedelta(days=i) for i in range(1, 8)]
        complete(*days)
        complete(days[3], seconds=80000)
        self.assertIsNone(stays.gate_opens(stays.complete_days(days[-1], days[0])['IJPP']))
        complete(days[3])
        self.assertEqual(stays.gate_opens(stays.complete_days(days[-1], days[0])['IJPP']), TODAY)

    def test_a_feed_without_its_own_complete_days_stays_closed(self):
        days = [TODAY - timedelta(days=i) for i in range(1, 8)]
        complete(*days)
        self.assertNotIn('MARPROM', stays.complete_days(days[-1], days[0]))


class LevelTests(TestCase):
    def setUp(self):
        complete(*[TODAY - timedelta(days=i) for i in range(1, 30)])

    def test_sure_after_four_agreeing_days_and_its_delay_absorption(self):
        for d in workdays(5):
            day_of(d, a_end_delay=600, b_start_delay=180)  # 10 min late at the end, 3 min late at the start
        m = learned()
        b = m[('IJPP:B', B)]
        self.assertEqual((b.level, b.origin, b.prev_route_id, b.prev_start, b.prev_end, b.days), ('sure', 'continues', 'IJPP:A', A, A + 40 * 60, 5))
        self.assertEqual(b.absorb, 420)
        self.assertEqual(m[('IJPP:A', A)].origin, 'depot')  # nothing before line A's 07:00

    def test_two_or_three_days_is_likely(self):
        for d in workdays(3):
            day_of(d)
        self.assertEqual(learned()[('IJPP:B', B)].level, 'likely')

    def test_a_contradiction_ends_sure_until_it_is_earned_again(self):
        prev = ('IJPP:A', A, 'p1')

        def record(outcomes):
            return [stays.Obs(TODAY - timedelta(days=len(outcomes) - i), 'IJPP', ('IJPP:B', B, 'p1'),
                              stays.CONTINUES if o else stays.DEPOT, prev if o else None) for i, o in enumerate(outcomes)]
        twenty = [True] * 20
        self.assertEqual(stays.level(stays.stats(record(twenty)), 4), 'sure')
        self.assertEqual(stays.level(stays.stats(record(twenty + [False] + [True] * 3)), 4), 'likely')  # 96 %, 3 since
        self.assertEqual(stays.level(stays.stats(record(twenty + [False] + [True] * 4)), 4), 'sure')    # earned again
        self.assertEqual(stays.level(stays.stats(record([True] * 6 + [False] + [True] * 6)), 4), 'likely')  # 92 %
        self.assertEqual(stays.level(stays.stats(record(twenty)), None), 'likely')  # the feed gets no "sure"

    def test_a_depot_visit_or_switching_off_is_a_fresh_start(self):
        parked = {'far': 3000, 'idle': [[DEPOT[0], DEPOT[1], 3 * H]]}
        for i, d in enumerate(workdays(6)):
            day_of(d, fresh=parked)
            # Another two vehicles park at the depot overnight: that's how the depot is learned.
            for v in ('IJPP:v2', 'IJPP:v3'):
                gap(d, v, f'IJPP:x-{v}-{d}', '', far=4000, idle=[[DEPOT[0] + 0.001, DEPOT[1], 8 * H]])
        b = learned()[('IJPP:B', B)]
        self.assertEqual((b.level, b.origin), ('', 'depot'))
        StayDeparture.objects.all().delete()
        VehicleTrip.objects.all().delete()
        VehicleGap.objects.all().delete()
        for d in workdays(6):
            day_of(d, fresh={'unseen': 12, 'seen': 0})  # gone from the feed for 12 polls ...
            gap(d, 'IJPP:v5', 'IJPP:p', 'IJPP:q', seen=30)  # ... in a feed that shows its vehicles between trips
        self.assertEqual(learned()[('IJPP:B', B)].origin, 'depot')

    def test_a_feed_that_drops_vehicles_between_trips_still_learns(self):
        for d in workdays(5):
            day_of(d, fresh={'unseen': 12, 'seen': 0})
        self.assertEqual(learned()[('IJPP:B', B)].level, 'sure')

    def test_a_timetable_change_starts_a_fresh_history(self):
        days = workdays(8)
        for i, d in enumerate(days):
            day_of(d, b_pattern='p1' if i < 6 else 'p2')
        b = learned()[('IJPP:B', B)]
        self.assertEqual((b.pattern, b.days, b.level), ('p2', 2, 'likely'))

    def test_a_weekend_departure_seen_once_is_never_sure(self):
        saturday = TODAY + timedelta(days=-6)  # 2026-10-17
        self.assertEqual(saturday.weekday(), 5)
        day_of(saturday)
        stays.learn(TODAY)
        self.assertFalse(StayDeparture.objects.filter(kind='saturday', level='sure').exists())
        self.assertFalse(StayDeparture.objects.filter(kind='saturday').exclude(level='').exists())

    def test_depot_starts_keep_their_own_usual_delay(self):
        for i, d in enumerate(workdays(4)):
            trip(d, f'IJPP:a-{d}', 'IJPP:v1', 'IJPP:A', A, A + 40 * 60, start_delay=60 * (i + 1))
        a = learned()[('IJPP:A', A)]
        self.assertEqual((a.origin, a.depot_delay), ('depot', 150))


class CheckTests(TestCase):
    def setUp(self):
        complete(*[TODAY - timedelta(days=i) for i in range(0, 30)])
        for d in workdays(6):
            day_of(d)
        stays.learn(TODAY)

    def test_a_sure_miss_is_logged_and_caps_the_feed_at_likely_for_a_week(self):
        day_of(TODAY, b_vehicle='IJPP:v9')
        self.assertEqual(stays.check(TODAY), {'IJPP sure': '0/1'})
        self.assertEqual(StayCheck.objects.get().misses, 1)
        VehicleTrip.objects.filter(service_date=TODAY).delete()  # so only the demotion is left to change it
        tomorrow = TODAY + timedelta(days=3)  # Monday
        self.assertEqual(stays.demoted(tomorrow), {'IJPP'})
        stays.learn(tomorrow)
        self.assertEqual(StayDeparture.objects.get(route_id='IJPP:B', kind='workday').level, 'likely')
        self.assertEqual(stays.demoted(TODAY + timedelta(days=9)), set())

    def test_a_hit_is_counted(self):
        day_of(TODAY)
        self.assertEqual(stays.check(TODAY), {'IJPP sure': '1/1'})


class BacktestTests(TestCase):
    def test_tuning_raises_min_days_until_sure_never_missed(self):
        complete(*[TODAY - timedelta(days=i) for i in range(1, 40)])
        days = workdays(14)
        for i, d in enumerate(days):
            day_of(d, b_vehicle='IJPP:v9' if i == 6 else None)  # after six agreeing days, a different bus
        days_, opens, groups = stays.gather(TODAY)
        self.assertEqual(stays.tune(groups), {'IJPP': 7})  # with 4, 5 or 6 the miss on day 7 would have been "sure"
        table = stays.backtest(groups, opens, {'IJPP': 7})
        sure = table[('sure', 'IJPP', 'workday')]
        self.assertEqual(sure['predicted'], sure['hits'])

    def test_no_prediction_before_the_gate_opens(self):
        days = workdays(10)
        for d in days:
            day_of(d)
        complete(*days[-5:])
        _, opens, groups = stays.gather(TODAY)
        self.assertTrue(groups)
        self.assertEqual(stays.backtest(groups, opens, {}), {})
