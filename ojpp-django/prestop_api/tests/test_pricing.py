from unittest import mock

from django.test import SimpleTestCase
from django.test.client import Client

from prestop_api import mapping, pricing, sharing

START = sharing._ts('2026-10-19T08:00:00+02:00')
KM = 1 / 77.3  # degrees of longitude per km at 46° N


def leg(feed, minute, km=5.0, mode='bus', name='1', route=None, minutes=20, **extra):
    """A ride east from 14.5° E: `km` long, leaving `minute` after 8:00."""
    at = lambda m: mapping.iso(START + m * 60)
    return {'id': f'leg:{feed}-{minute}', 'mode': mode, 'tripId': f'{feed}:t{minute}', 'routeId': route or f'{feed}:r', 'routeName': name,
            'geometry': [[14.5, 46.0], [14.5 + km * KM, 46.0]], 'effectiveDeparture': at(minute), 'effectiveArrival': at(minute + minutes),
            'scheduledDeparture': at(minute), 'scheduledArrival': at(minute + minutes), **extra}


def walk(minute):
    at = lambda m: mapping.iso(START + m * 60)
    return {'id': f'leg:w-{minute}', 'mode': 'walk', 'tripId': None, 'geometry': [], 'effectiveDeparture': at(minute), 'effectiveArrival': at(minute + 5)}


def price(*legs, cards=(), bikes=(), passes=(), language='en'):
    j = pricing.price_journey({'legs': list(legs)}, {'cards': list(cards), 'bikeMemberships': list(bikes), 'scooterPasses': list(passes)}, language)
    return [l.get('price', {}).get('amountCents', '-') for l in j['legs']], j['price']['totalCents'], j


class TariffTests(SimpleTestCase):
    """Worked examples from the price lists in data/tariffs.json."""

    def test_ijpp_1_50_up_to_5_km_then_50_cents_per_started_5_km_and_16_50_beyond_150(self):
        self.assertEqual([pricing.ijpp_cents(km) for km in (3, 5, 5.1, 25, 150, 151)], [150, 150, 200, 350, 1600, 1650])

    def test_sz_bands(self):
        # SŽ ST 700.04 (1. 7. 2026): up to 5 km 1.40, 45–50 km 5.50, 115–120 km 11.60, over 150 km 14.40.
        self.assertEqual([pricing.sz_cents(km) for km in (3, 50, 120, 156)], [140, 550, 1160, 1440])


class JourneyPriceTests(SimpleTestCase):
    def test_lpp_changes_are_free_within_90_minutes(self):
        cents, total, j = price(leg('LPP', 0), walk(20), leg('LPP', 40), leg('LPP', 120))
        self.assertEqual(cents, [150, '-', 0, 150])
        self.assertEqual(total, 300)
        self.assertEqual(j['legs'][0]['price']['ticket'], j['legs'][2]['price']['ticket'])
        self.assertEqual(j['legs'][0]['price']['checked'], '2026-10-18')

    def test_lpp_lines_in_the_ijpp_feed_pay_lpp_zone_fares(self):
        city = leg('IJPP', 0, km=6, operatorId='IJPP:1118', name='6B')          # within Ljubljana: zone 1
        suburb = leg('IJPP', 30, km=14, operatorId='IJPP:1118', name='51')      # out to 14 km from the centre: two zones
        cents, total, j = price(city, suburb)
        self.assertEqual(cents, [150, 100])  # the change pays the difference to the 2-zone fare
        self.assertTrue(j['legs'][0]['price']['basis'].startswith('LPP'))

    def test_marprom_window_is_75_minutes(self):
        self.assertEqual(price(leg('MARPROM', 0), leg('MARPROM', 70), leg('MARPROM', 80))[0], [150, 0, 150])

    def test_bus_and_train_on_one_integrated_ticket_priced_by_their_length(self):
        cents, total, j = price(leg('IJPP', 0, km=12), walk(20), leg('IJPP', 30, km=20, mode='rail', name='RG 2410'))
        self.assertEqual(cents, [pricing.ijpp_cents(32), '-', 0])  # 32 km: 1.50 + 6 × 0.50 = 4.50
        self.assertEqual(total, 450)

    def test_train_only_uses_sz_tariff_plus_the_ics_supplement(self):
        cents, total, j = price(leg('IJPP', 0, km=98, mode='rail', name='ICS 20'))
        self.assertEqual(total, 990 + 200)
        self.assertIn('ICS', j['legs'][0]['price']['basis'])

    def test_free_card_covers_buses_and_trains_but_not_the_ics_supplement(self):
        cents, total, j = price(leg('IJPP', 0, km=30), leg('LPP', 40), leg('IJPP', 70, km=100, mode='rail', name='ICS 20'), cards=['slovenia-free'])
        self.assertEqual(cents, [0, 0, 200])
        self.assertEqual({l['price'].get('coveredBy') for l in j['legs']}, {'slovenia-free'})

    def test_urbana_monthly_covers_lpp_only(self):
        self.assertEqual(price(leg('LPP', 0), leg('IJPP', 30, km=8), cards=['urbana-monthly'])[0], [0, 200])

    def test_unknown_fares_make_the_total_unknown_never_zero(self):
        cents, total, j = price(leg('MOKoper', 0), leg('LPP', 30))
        self.assertEqual(cents, [None, 150])
        self.assertIsNone(total)
        self.assertEqual(j['legs'][0]['price']['basis'], 'Price unknown')

    def test_slovene_basis(self):
        self.assertIn('prestopi', price(leg('LPP', 0), language='sl')[2]['legs'][0]['price']['basis'])


class RentalPriceTests(SimpleTestCase):
    def rental(self, network, minutes, mode='bike', form=None):
        form = form or ('scooter' if mode == 'scooter' else 'bicycle')
        r = leg('x', 0, mode=mode, minutes=minutes, rental={'network': network, 'operator': 'X', 'formFactor': form})
        r['tripId'] = None
        return r

    def test_bicikelj_member_rides_free_for_an_hour_others_pay_the_weekly_membership(self):
        self.assertEqual(price(self.rental('jcdecaux_ljubljana', 30), bikes=['jcdecaux_ljubljana'])[0], [0])
        self.assertEqual(price(self.rental('jcdecaux_ljubljana', 90), bikes=['jcdecaux_ljubljana'])[0], [100])
        self.assertEqual(price(self.rental('jcdecaux_ljubljana', 30))[0], [100])  # 1 € week

    def test_nomago_starter_pack_covers_a_ride_up_to_200_minutes(self):
        self.assertEqual(price(self.rental('nextbike_cn', 40))[0], [500])
        self.assertEqual(price(self.rental('nextbike_cn', 40), bikes=['nextbike_cn'])[0], [50])  # member: 30 free, then 0.50

    def test_scooter_without_a_published_unlock_fee_has_no_price(self):
        self.assertEqual(price(self.rental('bolt_359', 10, mode='scooter'))[1], None)

    def test_bolt_unlimited_unlocks_pass_prices_the_ride_by_its_minutes(self):
        # Bolt: "Od 0,15 € na minuto" plus an unpublished unlock fee; the pass waives the unlock: 12 min × 0.15 = 1.80.
        cents, total, j = price(self.rental('bolt_359', 12, mode='scooter'), passes=['bolt-unlimited-unlocks'])
        self.assertEqual((cents, total), ([180], 180))
        basis = j['legs'][0]['price']
        self.assertEqual(basis['basis'], 'X with your Bolt unlimited unlocks: 12 min × 0,15 € (lowest rate)')
        self.assertNotIn('coveredBy', basis)
        self.assertIn('najnižja cena', price(self.rental('bolt_359', 12, mode='scooter'), passes=['bolt-unlimited-unlocks'], language='sl')[2]['legs'][0]['price']['basis'])

    def test_bolt_e_bikes_and_kvik_have_no_published_price(self):
        self.assertEqual(price(self.rental('bolt_359', 12, form='bicycle'), passes=['bolt-unlimited-unlocks'])[:2], ([None], None))
        self.assertEqual(price(self.rental('kvik', 12, mode='scooter'))[:2], ([None], None))

    def test_scooter_unlock_plus_every_started_minute_and_a_cheaper_pass(self):
        rule = {'name': 'Demo', 'unlockCents': 100, 'perMinuteCents': 20, 'source': 'Demo list', 'formFactors': ['scooter'],
                'passes': [{'id': 'demo-day', 'name': {'en': 'Demo day', 'sl': 'Demo dan'}, 'cents': 500, 'period': 'day', 'freeUnlocks': True, 'perMinuteCents': 15}]}
        self.assertEqual(sharing.ride_cents(rule, 9.5 * 60), 100 + 20 * 10)
        with mock.patch.object(sharing, 'rules', return_value={'demo': rule}):
            cents, _, j = price(self.rental('demo', 10, mode='scooter'))
            self.assertEqual((cents, j['legs'][0]['price']['basis']), ([300], 'X: unlock 1 € + 10 min × 0,20 €'))
            self.assertEqual(price(self.rental('demo', 10, mode='scooter'), passes=['demo-day'])[0], [150])
            # A pass that would cost more than paying as you go is not used.
            rule['passes'][0].update(freeUnlocks=False, perMinuteCents=30)
            self.assertEqual(price(self.rental('demo', 10, mode='scooter'), passes=['demo-day'])[0], [300])


class CatalogTests(SimpleTestCase):
    def test_catalog_lists_cards_and_bike_memberships_by_region(self):
        response = Client().get('/api/v1/pricing/catalog')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'public, max-age=86400')
        data = response.json()['data']
        by_id = {c['id']: c for c in data['cards']}
        self.assertEqual(by_id['urbana-monthly']['regions'], ['ljubljana'])
        self.assertEqual((by_id['jcdecaux_ljubljana']['kind'], by_id['jcdecaux_ljubljana']['priceCents']), ('bike', 300))
        self.assertIn('ljubljana', {r['id'] for r in data['regions']})
        # One onboarding question per ticket system; who may buy each card.
        self.assertEqual({c['system'] for c in data['cards'] if c['kind'] == 'transit'}, {'ijpp', 'urbana', 'marprom', 'kranj'})
        self.assertEqual((by_id['ijpp-pupil-student']['system'], by_id['ijpp-pupil-student']['subsidy']), ('ijpp', 'student'))
        self.assertEqual((by_id['urbana-monthly']['subsidy'], by_id['slovenia-free']['subsidy']), ('none', 'senior'))
        self.assertEqual((by_id['jcdecaux_ljubljana']['system'], by_id['jcdecaux_ljubljana']['subsidy']), ('jcdecaux_ljubljana', 'none'))
        bolt = by_id['bolt-unlimited-unlocks']
        self.assertEqual((bolt['kind'], bolt['system'], bolt['networks'], bolt['period'], bolt['priceCents'], bolt['regions']),
                         ('scooter', 'bolt_359', ['bolt_359'], 'month', 99, ['ljubljana']))
