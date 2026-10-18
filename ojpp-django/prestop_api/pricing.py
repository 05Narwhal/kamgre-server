"""Price estimates for planned journeys, and the catalog of tickets onboarding asks about (GET /pricing/catalog).

One engine over one dated data file (data/tariffs.json, every number with its source). Prices are estimates: a leg
whose price the lists do not give is "price unknown" (amountCents None), never 0. The rider's cards come in the
plan request's body only (journeys.parse_request); they are used for that answer and never stored or logged.

Tickets: consecutive intercity legs (IJPP feed and SŽ replacement buses) share one ticket, priced by their length:
train only at SŽ's own tariff (plus the higher-rank supplement), otherwise the integrated IJPP tariff. City buses
(LPP, Marprom, Kranj) charge one fare with free changes within their window.
"""
import json
import math
from datetime import datetime
from functools import lru_cache
from typing import Optional

from . import geometry, sharing

TEXT = {
    'en': {'unknown': 'Price unknown', 'covered': 'Covered by your {card}', 'routeBound': 'Covered by your pass, if it is for this route',
           'ijpp': 'Integrated ticket (IJPP), {km} km', 'sz': 'SŽ train ticket, {km} km', 'szRank': 'SŽ train ticket, {km} km, with the {rank} supplement',
           'supplement': '{rank} supplement', 'sameTicket': 'On the same ticket', 'city': '{name} single fare, changes free for {minutes} min',
           'cityDay': '{name} day ticket', 'cityChange': 'Free change on the same ticket', 'rideMember': '{name} with your membership',
           'rideJoin': '{name}: membership needed (from {cents}), then the ride', 'rideUnknown': '{name}: price list incomplete',
           'note': "Estimate from the operators' price lists, checked {date}"},
    'sl': {'unknown': 'Cena ni znana', 'covered': 'Velja tvoja vozovnica: {card}', 'routeBound': 'Velja tvoja vozovnica, če je za to relacijo',
           'ijpp': 'Enotna vozovnica IJPP, {km} km', 'sz': 'Vozovnica SŽ, {km} km', 'szRank': 'Vozovnica SŽ, {km} km, z doplačilom za {rank}',
           'supplement': 'Doplačilo za {rank}', 'sameTicket': 'Na isti vozovnici', 'city': '{name}, enkratna vožnja, prestopi brezplačni {minutes} min',
           'cityDay': '{name}, dnevna vozovnica', 'cityChange': 'Brezplačen prestop na isti vozovnici', 'rideMember': '{name} z naročnino',
           'rideJoin': '{name}: potrebna je naročnina (od {cents}), nato vožnja', 'rideUnknown': '{name}: cenik ni popoln',
           'note': 'Ocena po cenikih prevoznikov, preverjeno {date}'},
}


@lru_cache(maxsize=1)
def tariffs() -> dict:
    return json.loads(sharing.TARIFFS.read_text(encoding='utf-8'))


def _ts(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def _euro(cents: int) -> str:
    return f'{cents / 100:.2f} €'.replace('.', ',') if cents % 100 else f'{cents // 100} €'


def _name(card: dict, language: str) -> str:
    return card['name'].get(language) or card['name']['en']


def _km(leg: dict) -> float:
    return geometry.cumulative(leg['geometry'])[-1] / 1000 if len(leg.get('geometry') or []) > 1 else 0.0


def ijpp_cents(km: float) -> int:
    """Integrated single ticket: base fare for the first step, then per further started step; flat beyond 150 km."""
    t = tariffs()['transit']['ijpp']
    if km > 150:
        return t['over150Cents']
    steps = max(1, math.ceil(km / t['stepKm']))
    return t['baseCents'] + t['stepCents'] * (steps - 1)


def sz_cents(km: float) -> int:
    """SŽ train-only single, 2nd class, by distance band."""
    t = tariffs()['transit']['sz']
    for upto, cents in t['bands']:
        if km <= upto:
            return cents
    return t['over150Cents']


def system_of(leg: dict) -> Optional[str]:
    """'ijpp', a city feed with a known fare, 'unknown' for other public transport, None for walking, riding, driving."""
    if not leg.get('tripId'):
        return None
    if leg.get('replacement'):
        return 'ijpp'  # SŽ's replacement bus: the train's ticket
    city = tariffs()['transit']['city']
    by_operator = next((name for name, c in city.items() if leg.get('operatorId') in c.get('operators', ())), None)
    if by_operator:
        return by_operator  # LPP's city lines also come in the IJPP feed
    feed = (leg.get('routeId') or '').split(':')[0]
    if feed == 'IJPP':
        return 'ijpp'
    return feed if feed in city else 'unknown'


def city_fare(city: dict, leg: dict) -> int:
    """The city fare; by zone where the system has zones (the ride's furthest point from the centre)."""
    zones = city.get('zones')
    if not zones or len(leg.get('geometry') or []) < 1:
        return city['fareCents']
    far = max(geometry.distance(zones['center'], p) for p in leg['geometry']) / 1000
    return next(cents for upto, cents in zones['steps'] if upto is None or far <= upto)


def _rank(leg: dict) -> Optional[str]:
    """IC / ICS / EC / EN / MV when the leg is a higher-rank train."""
    if leg.get('mode') != 'rail':
        return None
    first = (leg.get('routeName') or '').split(' ')[0].upper()
    return first if first in tariffs()['transit']['sz']['higherRank'] else None


def price_journey(journey: dict, profile: Optional[dict], language: str = 'en') -> dict:
    """Adds `price` to every leg that costs something and the journey's `price` (contract legPriceSchema,
    journeyPriceSchema)."""
    text = TEXT.get(language, TEXT['en'])
    data = tariffs()
    profile = profile or {}
    cards = {c['id']: c for c in data['transit']['cards'] if c['id'] in set(profile.get('cards') or [])}
    covering = lambda system: next((c for c in cards.values() if system in c['covers']), None)
    legs = journey['legs']

    def put(leg, cents, basis, source, **extra):
        leg['price'] = {'amountCents': cents, 'currency': 'EUR', 'basis': basis, 'source': source['source'], 'checked': data['checked'],
                        **({'sourceUrl': source['sourceUrl']} if source.get('sourceUrl') else {}), **extra}

    # Intercity tickets: consecutive IJPP legs (walks between them do not break a ticket).
    groups, current = [], []
    for leg in legs:
        system = system_of(leg)
        if system == 'ijpp':
            current.append(leg)
        elif system is not None and current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    for n, group in enumerate(groups):
        ticket = f'ijpp-{n}'
        km = sum(_km(l) for l in group)
        ranks = [r for r in map(_rank, group) if r]
        sz = data['transit']['sz']
        card = covering('ijpp')
        if card:
            # A pass covers the ride; a higher-rank train still costs its supplement, once per ticket.
            first_rank = next((l for l in group if _rank(l)), None)
            for leg in group:
                if leg is first_rank:
                    put(leg, sz['supplementCents'], text['supplement'].format(rank=_rank(leg)), sz, coveredBy=card['id'])
                else:
                    put(leg, 0, text['routeBound'] if card.get('routeBound') else text['covered'].format(card=_name(card, language)), card, coveredBy=card['id'])
            continue
        rail_only = all(l.get('mode') == 'rail' or l.get('replacement') for l in group)
        if rail_only:
            cents = sz_cents(km) + (sz['supplementCents'] if ranks else 0)
            basis = (text['szRank'].format(km=round(km), rank=ranks[0]) if ranks else text['sz'].format(km=round(km)))
            source = sz
        else:
            cents = ijpp_cents(km) + (sz['supplementCents'] if ranks else 0)
            basis = text['ijpp'].format(km=round(km)) + (f" + {text['supplement'].format(rank=ranks[0])}" if ranks else '')
            source = data['transit']['ijpp']
        put(group[0], cents, basis, source, ticket=ticket)
        for leg in group[1:]:
            put(leg, 0, text['sameTicket'], source, ticket=ticket)

    # City buses: one fare, free changes within the window from the first boarding.
    windows: dict[str, tuple[float, str, int]] = {}
    for i, leg in enumerate(legs):
        system = system_of(leg)
        if system in (None, 'ijpp'):
            continue
        if system == 'unknown':
            leg['price'] = {'amountCents': None, 'currency': 'EUR', 'basis': text['unknown'], 'source': '—', 'checked': data['checked']}
            continue
        city = data['transit']['city'][system]
        card = covering(system)
        if card:
            put(leg, 0, text['covered'].format(card=_name(card, language)), card, coveredBy=card['id'])
            continue
        start, fare = _ts(leg['effectiveDeparture']), city_fare(city, leg)
        open_ticket = windows.get(system)
        if open_ticket and start <= open_ticket[0]:
            # A change on the same ticket; riding into more zones pays the difference.
            until, ticket, paid = open_ticket
            put(leg, max(0, fare - paid), text['cityChange'], city, ticket=ticket)
            windows[system] = (until, ticket, max(fare, paid))
            continue
        ticket = f'{system.lower()}-{i}'
        windows[system] = (start + city['transferMinutes'] * 60, ticket, fare)
        basis = text['cityDay'] if city['transferMinutes'] >= 1440 else text['city']
        put(leg, fare, basis.format(name=city['name'], minutes=city['transferMinutes']), city, ticket=ticket)

    # Shared bikes and scooters.
    networks = sharing.rules()
    members = set(profile.get('bikeMemberships') or [])
    for leg in legs:
        rental = leg.get('rental')
        if not rental:
            continue
        rule = networks.get(rental['network'])
        name = rental.get('operator') or rental['network']
        seconds = _ts(leg['effectiveArrival']) - _ts(leg['effectiveDeparture'])
        ride = sharing.ride_cents(rule, seconds) if rule else None
        if rule is None or ride is None:
            leg['price'] = {'amountCents': None, 'currency': 'EUR', 'basis': text['rideUnknown'].format(name=name),
                            'source': (rule or {}).get('source', '—'), 'checked': data['checked'], **({'sourceUrl': rule['sourceUrl']} if rule and rule.get('sourceUrl') else {})}
            continue
        if 'perMinuteCents' in rule or rental['network'] in members or not rule.get('membership'):
            put(leg, ride, text['rideMember'].format(name=name), rule, **({'coveredBy': rental['network']} if ride == 0 and rental['network'] in members else {}))
            continue
        # Not a member: the cheapest way in, a starter pack whose minutes cover the ride or a membership plus the ride.
        join = min(m['cents'] for m in rule['membership'])
        cost = min(m['cents'] if seconds <= (m.get('includesMinutes') or -1) * 60 else m['cents'] + ride for m in rule['membership'])
        put(leg, cost, text['rideJoin'].format(name=name, cents=_euro(join)), rule)

    priced = [l['price']['amountCents'] for l in legs if 'price' in l]
    total = None if any(c is None for c in priced) else sum(priced)
    journey['price'] = {'totalCents': total, 'note': text['note'].format(date=data['checked'])}
    return journey


@lru_cache(maxsize=1)
def catalog() -> dict:
    """GET /pricing/catalog (contract pricingCatalogSchema): transit cards and bike memberships with their regions."""
    data = tariffs()
    cards = [{k: c[k] for k in ('id', 'name', 'regions', 'eligibility', 'period', 'priceCents', 'source', 'sourceUrl') if k in c} | {'kind': 'transit'}
             for c in data['transit']['cards']]
    for network, rule in data['sharing']['networks'].items():
        if not rule.get('membership'):
            continue
        yearly = next((m for m in rule['membership'] if m['period'] == 'year'), rule['membership'][0])
        cards.append({'id': network, 'kind': 'bike', 'name': {'sl': rule['name'], 'en': rule['name']}, 'regions': rule.get('regions', []),
                      'eligibility': 'all', 'period': yearly['period'], 'priceCents': yearly['cents'], 'networks': [network],
                      'source': rule['source'], **({'sourceUrl': rule['sourceUrl']} if rule.get('sourceUrl') else {})})
    return {'checked': data['checked'], 'regions': data['transit']['regions'], 'cards': cards}


# ---------------------------------------------------------------- cheaper first (A6)

BALANCED_MINUTES = 10   # Balanced takes a journey this many minutes later ...
BALANCED_CENTS = 150    # ... for every this much it saves (about 9 € an hour)
CHEAPEST_WINDOW = 45    # min: Cheapest is the cheapest journey arriving within this of the fastest


def rank(journeys: list[dict], req: dict) -> list[dict]:
    """Journeys in the order of the rider's cost preset; `fastest` keeps the planner's own order untouched. Time is
    the arrival after the asked-for time (arrive-by: how early it leaves). An unknown price ranks as the dearest known
    one, so it never wins on price. Each journey's price says how much it saves against the fastest."""
    preset = req.get('costPreset', 'fastest')
    if preset == 'fastest' or len(journeys) < 2:
        return journeys
    asked = req['dateTime'].timestamp()
    if req['timeMode'] == 'arriveBy':
        minutes = lambda j: (asked - _ts(j['effectiveDeparture'])) / 60
    else:
        minutes = lambda j: (_ts(j['effectiveArrival']) - asked) / 60
    total = lambda j: (j.get('price') or {}).get('totalCents')
    known = [total(j) for j in journeys if total(j) is not None]
    cost = lambda j: total(j) if total(j) is not None else max(known, default=0)
    fastest = min(journeys, key=minutes)
    if preset == 'balanced':
        key = lambda j: (minutes(j) + cost(j) / BALANCED_CENTS * BALANCED_MINUTES, minutes(j))
    else:
        within = lambda j: minutes(j) - minutes(fastest) <= CHEAPEST_WINDOW
        key = lambda j: (not within(j), cost(j) if within(j) else minutes(j), minutes(j))
    for j in journeys:
        if j is not fastest and total(j) is not None and total(fastest) is not None and j.get('price'):
            j['price'].update(savedCents=total(fastest) - total(j), comparedTo='fastest')
    return sorted(journeys, key=key)
