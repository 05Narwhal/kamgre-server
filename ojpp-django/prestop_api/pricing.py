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
from datetime import date, datetime
from functools import lru_cache
from typing import Optional

from . import driving, geometry, sharing

REGULATED = ('petrol', 'diesel')  # fuels with a government price (gov.si); LPG: the usual station price (goriva.si)
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
TEXT = {
    'en': {'unknown': 'Price unknown', 'covered': 'Covered by your {card}', 'routeBound': 'Covered by your pass, if it is for this route',
           'ijpp': 'Integrated ticket (IJPP), {km} km', 'sz': 'SŽ train ticket, {km} km', 'szRank': 'SŽ train ticket, {km} km, with the {rank} supplement',
           'supplement': '{rank} supplement', 'sameTicket': 'On the same ticket', 'city': '{name} single fare, changes free for {minutes} min',
           'cityDay': '{name} day ticket', 'cityChange': 'Free change on the same ticket', 'rideMember': '{name} with your membership',
           'rideJoin': '{name}: membership needed (from {cents}), then the ride', 'rideUnknown': '{name}: price list incomplete',
           'scooter': '{name}: unlock {unlock} + {minutes} min × {perMinute}', 'ridePass': '{name} with your {card}: {minutes} min × {perMinute}',
           'lowestRate': 'lowest rate',
           'note': "Estimate from the operators' price lists, checked {date}",
           'fuel': 'Fuel ≈ {amount} {unit} ({fuel})', 'fuelPrice': '{perLitre} €/l from {date}',
           'lpg': 'LPG, {perLitre} €/l, median of {stations} stations',
           'defaultCar': 'an average petrol car, {per100} l/100 km', 'vignette': '7-day vignette',
           'parking': 'parking {name}', 'parkingUnknown': 'parking {name} (fee unknown)', 'parkingFree': 'parking {name} (free)',
           'parkingHour': 'parking {name}, first hour', 'parkRide': 'Included in the P+R parking ticket',
           'fuels': {'petrol': 'petrol', 'diesel': 'diesel', 'lpg': 'LPG, price unknown', 'electric': 'public charging, estimate'}},
    'sl': {'unknown': 'Cena ni znana', 'covered': 'Velja tvoja vozovnica: {card}', 'routeBound': 'Velja tvoja vozovnica, če je za to relacijo',
           'ijpp': 'Enotna vozovnica IJPP, {km} km', 'sz': 'Vozovnica SŽ, {km} km', 'szRank': 'Vozovnica SŽ, {km} km, z doplačilom za {rank}',
           'supplement': 'Doplačilo za {rank}', 'sameTicket': 'Na isti vozovnici', 'city': '{name}, enkratna vožnja, prestopi brezplačni {minutes} min',
           'cityDay': '{name}, dnevna vozovnica', 'cityChange': 'Brezplačen prestop na isti vozovnici', 'rideMember': '{name} z naročnino',
           'rideJoin': '{name}: potrebna je naročnina (od {cents}), nato vožnja', 'rideUnknown': '{name}: cenik ni popoln',
           'scooter': '{name}: odklep {unlock} + {minutes} min × {perMinute}', 'ridePass': '{name}, velja tvoj paket {card}: {minutes} min × {perMinute}',
           'lowestRate': 'najnižja cena',
           'note': 'Ocena po cenikih prevoznikov, preverjeno {date}',
           'fuel': 'Gorivo ≈ {amount} {unit} ({fuel})', 'fuelPrice': '{perLitre} €/l od {date}',
           'lpg': 'avtoplin, {perLitre} €/l, srednja cena {stations} črpalk', 'defaultCar': 'povprečen bencinski avto, {per100} l/100 km', 'vignette': 'tedenska vinjeta',
           'parking': 'parkiranje {name}', 'parkingUnknown': 'parkiranje {name} (cena ni znana)', 'parkingFree': 'parkiranje {name} (brezplačno)',
           'parkingHour': 'parkiranje {name}, prva ura', 'parkRide': 'Vključeno v parkirni listek P+R',
           'fuels': {'petrol': 'bencin', 'diesel': 'dizel', 'lpg': 'avtoplin, cena ni znana', 'electric': 'javne polnilnice, ocena'}},
}


@lru_cache(maxsize=1)
def tariffs() -> dict:
    return json.loads(sharing.TARIFFS.read_text(encoding='utf-8'))


def _ts(value: str) -> float:
    return datetime.fromisoformat(value).timestamp()


def _euro(cents: int) -> str:
    return f'{cents / 100:.2f} €'.replace('.', ',') if cents % 100 else f'{cents // 100} €'


def _day(iso: str, language: str) -> str:
    d = date.fromisoformat(iso)
    return f'{d.day}. {d.month}.' if language == 'sl' else f'{d.day} {MONTHS[d.month - 1]}'


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
    included: dict[str, list] = {}  # city system -> [bus rides left on a P+R parking ticket, the car park's tariff]

    def put(leg, cents, basis, source, **extra):
        leg['price'] = {'amountCents': cents, 'currency': 'EUR', 'basis': basis, 'source': source['source'], 'checked': data['checked'],
                        **({'sourceUrl': source['sourceUrl']} if source.get('sourceUrl') else {}), **extra}

    # Driving: fuel, the 7-day vignette once when motorways are used without one, and the car park's fee.
    rules = data['driving']
    car = profile.get('car') or rules['defaultCar']
    vignette_due = not car['vignette']
    for leg in legs:
        if leg.get('mode') != 'car' or 'car' not in leg:
            continue
        due = vignette_due and leg['car']['motorway']
        vignette_due = vignette_due and not due
        day = datetime.fromtimestamp(_ts(leg['effectiveDeparture']), driving.LOCAL).date()
        prices = driving.fuel(day) if car['fuel'] in REGULATED else driving.lpg() if car['fuel'] == 'lpg' else None
        cents, leg['car'] = driving.cost(leg['car'], car, rules, due, prices)
        amount = leg['car'].get('energyKwh') if car['fuel'] == 'electric' else leg['car']['fuelLitres']
        number = lambda value, digits: f'{value:.{digits}f}'.replace('.', ',') if language == 'sl' else f'{value:.{digits}f}'
        kind = text['fuels'][car['fuel']]
        if prices and car['fuel'] == 'lpg':
            kind = text['lpg'].format(perLitre=number(prices['lpg'], 3), stations=prices['stations'])
        elif prices:
            kind += ', ' + text['fuelPrice'].format(perLitre=number(prices[car['fuel']], 3), date=_day(prices['from'], language))
        parts = [text['fuel'].format(amount=number(amount, 1), unit='kWh' if car['fuel'] == 'electric' else 'l', fuel=kind)]
        if not profile.get('car'):
            parts[0] += f" · {text['defaultCar'].format(per100=car['litresPer100km'])}"
        if due:
            parts.append(text['vignette'])
        park = leg['car'].get('parking')
        if park:
            hourly = driving.parking_fee(park, rules)['basis'] == 'hourly'
            key = 'parkingUnknown' if park['feeCents'] is None else 'parkingFree' if not park['feeCents'] else 'parkingHour' if hourly else 'parking'
            parts.append(text[key].format(name=park['name']))
            known = driving.parking(park['name'], rules)
            if known and known.get('includesRides'):
                included[known['system']] = [known['includesRides'], known]
        source = rules['electric'] if car['fuel'] == 'electric' else rules['lpg'] if car['fuel'] == 'lpg' else rules['fuel']
        checked = prices['checked'] if prices else source.get('checked') or datetime.now(driving.LOCAL).date().isoformat()
        leg['price'] = {'amountCents': cents, 'currency': 'EUR', 'basis': ' + '.join(parts), 'source': source['source'],
                        'sourceUrl': source['sourceUrl'], 'checked': checked}

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
        if included.get(system) and included[system][0] > 0:
            included[system][0] -= 1
            put(leg, 0, text['parkRide'], included[system][1])
            continue
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
    passes = set(profile.get('scooterPasses') or [])
    for leg in legs:
        rental = leg.get('rental')
        if not rental:
            continue
        rule = networks.get(rental['network'])
        if rule and rental.get('formFactor') not in rule.get('formFactors', [rental.get('formFactor')]):
            rule = None  # e.g. Bolt's e-bikes: only its scooter prices are published
        name = rental.get('operator') or rental['network']
        seconds = _ts(leg['effectiveArrival']) - _ts(leg['effectiveDeparture'])
        ride = sharing.ride_cents(rule, seconds) if rule else None
        # A scooter pass the rider holds, when it makes this ride cheaper (or known: it may waive an unpublished unlock).
        held = [(sharing.ride_cents(rule, seconds, p), p) for p in (rule or {}).get('passes') or [] if p['id'] in passes]
        held = min(((c, p) for c, p in held if c is not None and (ride is None or c < ride)), key=lambda h: h[0], default=None)
        minutes = math.ceil(seconds / 60)
        lowest = f" ({text['lowestRate']})" if (rule or {}).get('perMinuteFrom') else ''
        if held:
            cents, card = held
            put(leg, cents, text['ridePass'].format(name=name, card=_name(card, language), minutes=minutes,
                                                    perMinute=_euro(card.get('perMinuteCents', rule['perMinuteCents']))) + lowest,
                rule, **({'coveredBy': card['id']} if cents == 0 else {}))
            continue
        if rule is None or ride is None:
            leg['price'] = {'amountCents': None, 'currency': 'EUR', 'basis': text['rideUnknown'].format(name=name),
                            'source': (rule or {}).get('source', '—'), 'checked': data['checked'], **({'sourceUrl': rule['sourceUrl']} if rule and rule.get('sourceUrl') else {})}
            continue
        if 'perMinuteCents' in rule:
            put(leg, ride, text['scooter'].format(name=name, unlock=_euro(rule['unlockCents']), minutes=minutes, perMinute=_euro(rule['perMinuteCents'])) + lowest, rule)
            continue
        if rental['network'] in members or not rule.get('membership'):
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


# Who may buy a card (catalog `subsidy`), from the tariff file's eligibility.
SUBSIDY = {'all': 'none', 'pupil': 'pupil', 'student': 'student', 'senior': 'senior', 'disabled': 'other'}


@lru_cache(maxsize=1)
def catalog() -> dict:
    """GET /pricing/catalog (contract pricingCatalogSchema): transit cards, bike memberships and scooter passes with their
    regions; system: the ticket system each belongs to (onboarding asks one question per system), a bike membership's or
    scooter pass's is its network."""
    data = tariffs()
    cards = [{k: c[k] for k in ('id', 'name', 'system', 'regions', 'eligibility', 'period', 'priceCents', 'source', 'sourceUrl') if k in c}
             | {'kind': 'transit', 'subsidy': SUBSIDY[c.get('eligibility', 'all')]} for c in data['transit']['cards']]
    for network, rule in data['sharing']['networks'].items():
        for p in rule.get('passes') or []:
            cards.append({'id': p['id'], 'kind': 'scooter', 'name': p['name'], 'system': network, 'regions': rule.get('regions', []),
                          'eligibility': 'all', 'subsidy': 'none', 'period': p['period'], 'priceCents': p['cents'], 'networks': [network],
                          'source': rule['source'], **({'sourceUrl': rule['sourceUrl']} if rule.get('sourceUrl') else {})})
        if not rule.get('membership'):
            continue
        yearly = next((m for m in rule['membership'] if m['period'] == 'year'), rule['membership'][0])
        cards.append({'id': network, 'kind': 'bike', 'name': {'sl': rule['name'], 'en': rule['name']}, 'system': network, 'regions': rule.get('regions', []),
                      'eligibility': 'all', 'subsidy': 'none', 'period': yearly['period'], 'priceCents': yearly['cents'], 'networks': [network],
                      'source': rule['source'], **({'sourceUrl': rule['sourceUrl']} if rule.get('sourceUrl') else {})})
    return {'checked': data['checked'], 'regions': data['transit']['regions'], 'cards': cards}


# ---------------------------------------------------------------- cheaper first (A6)

BALANCED_MINUTES = 10   # Balanced takes a journey this many minutes later ...
BALANCED_CENTS = 150    # ... for every this much it saves (about 9 € an hour)
CHEAPEST_WINDOW = 45    # min: Cheapest is the cheapest journey arriving within this of the fastest


def is_drive(journey: dict) -> bool:
    """Driven all the way (walks to and from the car aside)."""
    modes = {l['mode'] for l in journey['legs']} - {'walk'}
    return modes == {'car'}


def _minutes(req: dict):
    """Minutes a journey takes from the asked time: to its arrival, or arriving by a time, from its departure."""
    asked = req['dateTime'].timestamp()
    if req['timeMode'] == 'arriveBy':
        return lambda j: (asked - _ts(j['effectiveDeparture'])) / 60
    return lambda j: (_ts(j['effectiveArrival']) - asked) / 60


MEMBER_SLOWER = 5    # min: with Bike off, a ride on the rider's own bike network stays this much behind the quickest other
MEMBER_CHEAPER = 10  # min: ... or this much when it costs less than that one


def member_rides(journeys: list[dict], req: dict) -> list[dict]:
    """With Bike off, the rider's bike networks are searched too (journeys.extra_searches): their rides stay only when
    they compete, at most MEMBER_SLOWER minutes behind the quickest journey without a shared bike, or MEMBER_CHEAPER
    when cheaper than it (a BicikeLJ member's first hour is free; the bus is 1.30 €). With Bike on, every ride stays."""
    if 'bike' in req['modes']:
        return journeys
    ridden = lambda j: any(l['mode'] == 'bike' and l.get('rental') for l in j['legs'])
    others = [j for j in journeys if not ridden(j)]
    if not others:
        return journeys
    minutes, total = _minutes(req), lambda j: (j.get('price') or {}).get('totalCents')
    best = min(others, key=minutes)

    def competes(j: dict) -> bool:
        behind = minutes(j) - minutes(best)
        cheaper = total(j) is not None and total(best) is not None and total(j) < total(best)
        return behind <= MEMBER_SLOWER or (cheaper and behind <= MEMBER_CHEAPER)
    return [j for j in journeys if not ridden(j) or competes(j)]


def rank(journeys: list[dict], req: dict) -> list[dict]:
    """Journeys in the order of the rider's cost preset; `fastest` keeps the planner's own order untouched. Time is
    the arrival after the asked-for time (arrive-by: how early it leaves). An unknown price ranks as the dearest known
    one, so it never wins on price. Each journey's price says how much it saves against driving (when a drive-only
    journey is among them, whatever the preset), else against the fastest."""
    total = lambda j: (j.get('price') or {}).get('totalCents')
    drive = next((j for j in journeys if is_drive(j) and total(j) is not None), None)
    if drive:
        for j in journeys:
            if j is not drive and total(j) is not None:
                j['price'].update(savedCents=total(drive) - total(j), comparedTo='car')
    preset = req.get('costPreset', 'fastest')
    if preset == 'fastest' or len(journeys) < 2:
        return journeys
    minutes = _minutes(req)
    known = [total(j) for j in journeys if total(j) is not None]
    cost = lambda j: total(j) if total(j) is not None else max(known, default=0)
    fastest = min(journeys, key=minutes)
    if preset == 'balanced':
        key = lambda j: (minutes(j) + cost(j) / BALANCED_CENTS * BALANCED_MINUTES, minutes(j))
    else:
        within = lambda j: minutes(j) - minutes(fastest) <= CHEAPEST_WINDOW
        key = lambda j: (not within(j), cost(j) if within(j) else minutes(j), minutes(j))
    if not drive:
        for j in journeys:
            if j is not fastest and total(j) is not None and total(fastest) is not None and j.get('price'):
                j['price'].update(savedCents=total(fastest) - total(j), comparedTo='fastest')
    return sorted(journeys, key=key)
