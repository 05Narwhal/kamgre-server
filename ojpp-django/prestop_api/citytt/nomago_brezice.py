"""Brežice's city buses (Nomago for the municipality): two posters with no text layer, so their times are typed in here.

Nomago's page links the school-year poster ("ZIMSKI VOZNI RED 2023_2024", printed 1. 9. 2023 – 30. 6. 2024, still the one
the page offers for 1. 9. – 30. 6., 2026-11-05) and the summer one ("Poletni režim", printed 1. 7. – 31. 8. 2020, offered for
1. 7. – 30. 8.). Both: no buses on Sundays and public holidays. The page also prints the same times as text.

Modra loops from Brežice AP through Trnje and back (Mon–Fri); Zelena loops from Intermarket through AP, Trnje and the old
town (Mon–Sat mornings, Mon–Fri afternoons), a half-day's last run ending at Občina and its first leaving AP (but the
summer afternoon's, from Intermarket). Every
run keeps the same minutes between stops (the posters' columns), so a run is its start, first and last stop. Stop names
are OTP's (`Brezice` feed), whose ids are the posters' stop numbers; stadion and gimnazija have a pole each way.

A poster whose bytes change is a ValueError (the build keeps the last good folder): read it and type its times again.
"""
import hashlib

MODRA = ('Brežice AP', 'Murnova', 'Kregarjeva', 'Prežihova 1', 'Prežihova 2', 'Brežice Market', 'Brežice Občina',
         'Brežice gimnazija', 'Brežice stadion', 'Cesta bratov Milavcev', 'Brežice stadion', 'Brežice gimnazija',
         'Brežice Zdravstveni dom', 'Maistrova', 'Brežice AP')
MODRA_AT = (0, 2, 3, 4, 5, 7, 8, 10, 11, 13, 14, 15, 16, 17, 19)
ZELENA = ('Brežice Intermarket', 'Cesta bratov Milavcev', 'Brežice stadion', 'Brežice gimnazija', 'Brežice Zdravstveni dom',
          'Maistrova', 'Brežice AP', 'Murnova', 'Kregarjeva', 'Prežihova 1', 'Prežihova 2', 'Trdinova', 'Pokopališče',
          'Cankarjeva', 'Brežice Market', 'Brežice Občina', 'Brežice gimnazija', 'Brežice stadion', 'Brežice Intermarket')
ZELENA_AT = (0, 2, 3, 4, 5, 6, 8, 10, 11, 12, 13, 15, 17, 18, 19, 20, 22, 23, 27)
AP, OBCINA, END = 6, 15, 18  # Zelena: the first half-day run starts at AP, the last ends at Občina


def _every20(first: str, n: int) -> tuple:
    h, m = map(int, first.split(':'))
    return tuple(f'{(h * 60 + m + 20 * i) // 60:02d}:{(h * 60 + m + 20 * i) % 60:02d}' for i in range(n))


def _zelena(starts: tuple) -> tuple:
    """(departure, first stop, last stop): the first from AP, the middle ones whole loops, the last to Občina."""
    return tuple((t, AP if i == 0 else 0, OBCINA if i == len(starts) - 1 else END) for i, t in enumerate(starts))


# sha256 of the poster -> (OTP's route id, service, runs as (departure from the first stop, first, last stop index))
# D / DS: Mon–Fri / Mon–Sat, 1 Sep – 30 Jun; PD / PDS: the same in July and August.
POSTERS = {
    'bf312f43d70481ffe20f93f8577c8e9dcc99fd5c1da9d9ce3581dadf3f0babd1': (  # ZIMSKI VOZNI RED 2023_2024
        ('1', 'D', tuple((t, 0, 14) for t in _every20('06:20', 7) + _every20('13:00', 8))),
        ('2', 'DS', _zelena(('09:00', '10:00', '11:00', '12:00'))),
        ('2', 'D', _zelena(('16:00', '17:00', '18:00', '19:00'))),
    ),
    '9a10910d137da23a4e52aeaf09e2f014ff674fcac711a934d8830ae91b9b0756': (  # Poletni režim, 2020
        ('1', 'PD', tuple((t, 0, 14) for t in ('06:40', '07:40', '15:00', '15:20', '16:00', '16:20'))),
        ('2', 'PDS', _zelena(('09:00', '10:00', '11:00', '12:00'))),
        ('2', 'PD', (('17:00', 0, END), ('18:00', 0, OBCINA))),  # both from Intermarket
    ),
}


def _at(start: str, minutes: int) -> str:
    t = int(start[:2]) * 60 + int(start[3:]) + minutes
    return f'{t // 60:02d}:{t % 60:02d}'


def table(line: str, service: str, runs: tuple) -> dict:
    stops, at = (MODRA, MODRA_AT) if line == '1' else (ZELENA, ZELENA_AT)
    rows = [[_at(dep, at[i] - at[first]) if first <= i <= last else None for i in range(len(stops))] for dep, first, last in runs]
    return {'line': line, 'title': 'Modra' if line == '1' else 'Zelena', 'stops': list(stops), 'runs': rows,
            'direction': 0, 'service': service, 'notes': []}


def parse(path) -> list[dict]:
    with open(path, 'rb') as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest not in POSTERS:
        raise ValueError(f'the poster changed (sha256 {digest[:12]}…): read it and type its times into nomago_brezice.POSTERS')
    return [table(*t) for t in POSTERS[digest]]
