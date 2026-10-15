"""Places abroad: never a stop, line, vehicle or shape, only the text of where a trip really starts or ends.

KamGre shows Slovenia only. A trip that runs abroad ends (or starts) at its last stop in Slovenia and shows
the place abroad as its destination (or origin) text: the RG train to Villach is "→ Beljak / Villach" at
Jesenice, BUS 415 reads "from Beljak / Villach". Where the real end comes from, most trustworthy first:
- the trip's own stops abroad (the IJPP feed marks them with their country: "Gorizia Corso Italia 85/89 (I)");
- for SŽ's replacement buses, the station abroad in SŽ's timetable column (sztimetables.Stations.resolve);
- for trains, `data/international_trains.csv`: the feed's international trains end at the border station
  ("EC 115 Jesenice - Dobova") and SŽ's live feed has no relation, so the train's real route is kept there.
"""
import csv
import os
import re
from functools import lru_cache
from typing import Callable, Optional, Sequence, TypeVar

from .mapping import fold

T = TypeVar('T')
TRAINS_CSV = os.path.join(os.path.dirname(__file__), 'data', 'international_trains.csv')
# The IJPP feed's stops abroad end in their country: "Tarvisio autostazione (I)", "Bleiburg Bahnhof (A)".
_MARK = re.compile(r'\((?:I|A|HR|H|D|CH|SRB|BIH)\)\s*$')
# A place abroad as riders read it: Slovenian name / local name, the way SŽ and the stations sign it.
PLACES = {
    'beljak': 'Beljak / Villach', 'villach': 'Beljak / Villach',
    'opcine': 'Opčine', 'villa opicina': 'Opčine',
    'trst': 'Trst / Trieste', 'trieste': 'Trst / Trieste',
    'gorizia': 'Gorica / Gorizia', 'gorica': 'Gorica / Gorizia',
    'tarvisio': 'Trbiž / Tarvisio', 'trbiz': 'Trbiž / Tarvisio',
    'cividale': 'Čedad / Cividale', 'cedad': 'Čedad / Cividale',
    'lavamund': 'Labot / Lavamünd', 'labot': 'Labot / Lavamünd',
    'bleiburg': 'Pliberk / Bleiburg', 'pliberk': 'Pliberk / Bleiburg',
    'spielfeld': 'Špilje / Spielfeld', 'spilje': 'Špilje / Spielfeld',
    'graz': 'Gradec / Graz', 'gradec': 'Gradec / Graz',
    'wien': 'Dunaj / Wien', 'dunaj': 'Dunaj / Wien',
    'munchen': 'München', 'monakovo': 'München', 'salzburg': 'Salzburg', 'zurich': 'Zürich',
    'zagreb': 'Zagreb', 'rijeka': 'Reka / Rijeka', 'reka': 'Reka / Rijeka', 'pula': 'Pulj / Pula', 'pulj': 'Pulj / Pula',
    'split': 'Split', 'buzet': 'Buzet', 'cakovec': 'Čakovec', 'durmanec': 'Durmanec',
    'budapest': 'Budimpešta / Budapest', 'budimpesta': 'Budimpešta / Budapest',
}


def _words(name: str) -> list[str]:
    return re.findall(r'[a-z0-9]+', fold(_MARK.sub('', name or '')))


def is_abroad_stop(name: Optional[str]) -> bool:
    """A feed stop abroad, by the country the feed puts after its name."""
    return bool(_MARK.search(name or ''))


def place(name: Optional[str]) -> str:
    """The place a stop or station abroad lies in, as riders read it ('Gorizia Corso Italia 85/89 (I)' ->
    'Gorica / Gorizia', 'BELJAK' -> 'Beljak / Villach'); an unknown one keeps its own name."""
    words = _words(name or '')
    for n in (2, 1):
        for i in range(len(words) - n + 1):
            found = PLACES.get(' '.join(words[i:i + n]))
            if found:
                return found
    return _MARK.sub('', name or '').strip()


def trim(items: Sequence[T], name_of: Callable[[T], Optional[str]]) -> tuple[int, int, Optional[str], Optional[str]]:
    """The stretch of `items` (a trip's stops, in order) in Slovenia, as (start, end) slice bounds, with the place
    abroad the trip comes from and goes to (None where it starts or ends in Slovenia). No stop in Slovenia: (0, 0)."""
    inside = [i for i, s in enumerate(items) if not is_abroad_stop(name_of(s))]
    if not inside:
        return 0, 0, None, None
    a, b = inside[0], inside[-1] + 1
    return a, b, place(name_of(items[0])) if a > 0 else None, place(name_of(items[-1])) if b < len(items) else None


@lru_cache(maxsize=1)
def _trains() -> dict[str, tuple[str, str]]:
    out = {}
    try:
        with open(TRAINS_CSV, encoding='utf-8') as f:
            for row in csv.DictReader(r for r in f if not r.startswith('#')):
                out[re.sub(r'\s+', ' ', row['train'].strip().upper())] = (row['from'].strip(), row['to'].strip())
    except OSError:
        pass
    return out


def train_ends(route_name: Optional[str], first: Optional[str] = None, last: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    """An international train's places abroad: (where it comes from, where it goes), each None in Slovenia.
    'EC 115' -> ('München', 'Zagreb'). `first`/`last`: the trip's own end stations in the feed; a start or end
    the table puts in Slovenia, or at a station the feed has, is no place abroad."""
    found = _trains().get(re.sub(r'\s+', ' ', (route_name or '').strip().upper()))
    if not found:
        return None, None
    ends = []
    for real, own in zip(found, (first, last)):
        label = place(real) if real else ''
        ends.append(label if label and label in PLACES.values() and fold(real) not in fold(own or '') else None)
    return ends[0], ends[1]


def scheduled_ends(trip: dict) -> tuple[Optional[str], Optional[str]]:
    """A scheduled.py run's places abroad (where it comes from, where it goes): a replacement bus's from SŽ's
    timetable (closures._timetable_bus), a train's from the table of international trains."""
    if trip.get('synthetic'):
        return trip.get('comesFrom'), trip.get('goesTo')
    from .mapping import route_name
    stops = trip.get('stops') or [{}]
    return train_ends(route_name(trip.get('route') or {}), stops[0].get('name'), stops[-1].get('name'))
