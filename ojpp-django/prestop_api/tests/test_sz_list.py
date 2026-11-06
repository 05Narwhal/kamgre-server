import json
import tempfile
from datetime import date, datetime
from io import StringIO
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from prestop_api import closures, mapping, operator_notices, sz_list, views, zamudil

LOCAL = ZoneInfo('Europe/Ljubljana')


def item(number: int, days: str, title: str, body: str) -> str:
    """One notice as SŽ's page has it (2026-11-01)."""
    return f"""<div class="accordion-item rounded-bottom-1 border-0">
    <h3 class="accordion-header position-relative p-0" id="heading-{number}">
        <button class="accordion-button collapsed shadow-none pe-5" type="button" data-bs-toggle="collapse" data-bs-target="#collapse-{number}" aria-expanded="false" aria-controls="collapse-{number}">
            <span class="me-2 fw-semibold">
                {days}                                                </span>
            {title}                                             </button>
    </h3>
    <div class="accordion-collapse collapse rounded-bottom-1" id="collapse-{number}" data-bs-parent="#accordion-1-2" aria-labelledby="heading-{number}" aria-expanded="false">
        <div class="accordion-body p-2 rounded-bottom-1">
            <div><br>{body}</div>
        </div>
    </div>
</div>"""


ENDING = """<br>
<br>
Potnikom se opravičujemo in zahvaljujemo za razumevanje.<br>
<br>
<strong><a href="https://potniski.sz.si/info">potniski.sz.si/info</a></strong><br>
<br>
Na portalu <strong><a href="https://potnik.sz.si">MOJ VLAK</a></strong> se lahko naročite na samodejno obveščanje."""
PDF = 'https://potniski.sz.si/wp-content/uploads/2026/10/Kopija-datoteke-Divaca-Koper-november-2026-1-1.pdf'
TIMETABLE = item(11285, '09.11.2026-30.11.2026', 'Vozni red nadomestnega prevoza: Divača - Koper in obratno (9. in 30. november).',
                 f"""<strong>Povezava: <a href="{PDF}">Vozni red nadomestnega prevoza</a></strong><br>
<br>
Zaradi del na progi Divača - Koper je za v zgornji povezavi omenjene vlake 9. in 30. novembra organiziran nadomestni prevoz.{ENDING}""")
UNTIL = item(9459, '14.12.2025-12.12.2026', 'Vozni red nadomestnega prevoza: Divača - Koper in obratno (do 12. decembra).',
             f"""<strong>Povezava: <a href="https://potniski.sz.si/wp-content/uploads/2026/06/Nova.pdf">Vozni red nadomestnega prevoza</a></strong><br>Zaradi del.{ENDING}""")
FOOTNOTE = item(11268, '02.11.2026-06.11.2026', 'Vozni red nadomestnega prevoza: Ljubljana - Jesenice / Beljak (A) in obratno ((!*)2. - 6. november).',
                f"""<strong>Povezava: <a href="https://potniski.sz.si/wp-content/uploads/2026/10/Ljubljana-Jesenice.pdf">Vozni red nadomestnega prevoza</a></strong><br>Zaradi del.{ENDING}""")
WORKS = item(11291, '09.11.2026-18.11.2026', 'DELA NA PROGI: Zapora enega tira na dvotirni progi Postojna - Prestranek - Pivka.',
             f'Na progi Postojna - Prestranek - Pivka (9. - 13. in 16. - 18. november, 7.00 - 15.00) poteka zapora enega tira.{ENDING}')
CAR_TRAINS = item(11341, '16.11.2026-19.11.2026', 'OBVESTILO: Skrajšana relacija avtovlakov: Bohinjska Bistrica - Podbrdo (16. - 19. november).',
                  f'Potnike obveščamo, da bodo od 16. do 19. novembra avtovlaki št. 853, 854, 857 in 858 vozili na skrajšani relaciji.{ENDING}')
CONNECTION = item(11277, '02.11.2026-08.11.2026', 'DODATNO: Avtobusni prevoz za vezo (NG - LJ): Lesce Bled - Bled Jezero in obratno (2. - 8. november).',
                  f'<strong>Povezava: <a href="https://potniski.sz.si/wp-content/uploads/2026/10/Lesce-Bled.pdf">Vozni red</a></strong><br>Uvajamo povezovalno linijo.{ENDING}')
LOADING = item(9903, '14.12.2025-12.12.2026', 'OPOZORILO: Nakladanje vozil se zaključi vsaj 10 minut pred rednim odhodom avtovlaka.',
               'Nakladanje vozil na postaji <strong>Nova Gorica je končano 15 minut pred odhodom avtovlaka</strong>, na ostalih postajah pa 10 minut.<br><br>Hvala za razumevanje.')
PAGE = f'<html><body><div id="accordion-2">{TIMETABLE}{UNTIL}{FOOTNOTE}{WORKS}{CAR_TRAINS}{CONNECTION}{LOADING}</div></body></html>'
NOW = datetime(2026, 11, 1, 20, tzinfo=LOCAL).timestamp()


def by_id(notices):
    return {n['id']: n for n in notices}


class ParseTests(SimpleTestCase):
    def test_every_notice_with_its_days_title_and_timetable(self):
        notices = by_id(sz_list.parse(PAGE))
        self.assertEqual(len(notices), 7)
        n = notices['11285']
        self.assertEqual((n['from'], n['to']), ('2026-11-09', '2026-11-30'))
        self.assertEqual(n['title'], 'Vozni red nadomestnega prevoza: Divača - Koper in obratno (9. in 30. november).')
        self.assertEqual(n['pdf'], PDF)
        self.assertIsNone(notices['11291']['pdf'])

    def test_the_lines_every_notice_ends_with_are_left_out(self):
        n = by_id(sz_list.parse(PAGE))['11285']
        self.assertTrue(n['text'].startswith('Zaradi del na progi'))
        self.assertTrue(n['text'].endswith('nadomestni prevoz.'))
        self.assertNotIn('Povezava', n['text'])

    def test_only_a_timetable_on_szs_own_site_is_followed(self):
        page = item(1, '01.11.2026-02.11.2026', 'Vozni red nadomestnega prevoza: A - B (1. - 2. november).', '<a href="https://example.com/x.pdf">x</a>')
        self.assertIsNone(sz_list.parse(page)[0]['pdf'])

    def test_a_page_without_the_list_has_none(self):
        self.assertEqual(sz_list.parse('<html><title>Just a moment...</title></html>'), [])
        with self.assertRaises(ValueError):
            sz_list.check([])

    def test_a_notice_without_its_days_is_named_as_not_read(self):
        page = PAGE.replace('16.11.2026-19.11.2026', '')
        self.assertEqual(sz_list.left_out(page, sz_list.parse(page)), ['11341 OBVESTILO: Skrajšana relacija avtovlakov: Bohinjska Bistrica - Podbrdo (16. - 19. november).'])
        self.assertEqual(sz_list.left_out(PAGE, sz_list.parse(PAGE)), [])

    def test_the_import_names_the_notices_it_could_not_read(self):
        page = PAGE.replace('16.11.2026-19.11.2026', '')
        out = StringIO()
        with tempfile.TemporaryDirectory() as tmp, override_settings(PRESTOP_SZ_LIST_FILE=str(Path(tmp) / 'sz-list.json')), \
                mock.patch('sys.stdin', mock.Mock(buffer=mock.Mock(read=lambda n: page.encode()))):
            call_command('sz_notices', '--import', stdout=out)
        self.assertIn('Not read (no dates or no heading): 11341 OBVESTILO', out.getvalue())


class SpanTests(SimpleTestCase):
    def days(self, html):
        return sz_list.spans(sz_list.parse(html)[0])

    def test_days_listed_in_the_title_are_those_days_not_the_weeks_between(self):
        self.assertEqual(self.days(TIMETABLE), [(date(2026, 11, 9), date(2026, 11, 9)), (date(2026, 11, 30), date(2026, 11, 30))])

    def test_until_a_day_takes_the_lists_dates(self):
        self.assertEqual(self.days(UNTIL), [(date(2025, 12, 14), date(2026, 12, 12))])

    def test_a_title_with_a_footnote_mark_takes_the_lists_dates(self):
        self.assertEqual(self.days(FOOTNOTE), [(date(2026, 11, 2), date(2026, 11, 6))])

    def test_a_title_without_days_takes_the_lists_dates(self):
        self.assertEqual(self.days(WORKS), [(date(2026, 11, 9), date(2026, 11, 18))])

    def test_every_dated_title_of_the_list_saved_on_5_november_is_read(self):
        # Titles of SŽ's list saved 5 Nov 2026 (sz-download-3.html, 49 notices): their days come from the title.
        cases = {
            ('26.10.2026-06.11.2026', 'Vozni red nadomestnega prevoza: Ptuj / Moškanjci - Ormož in obratno (26. - 30. 10. in 3. - 6. 11.).'):
                [(date(2026, 10, 26), date(2026, 10, 30)), (date(2026, 11, 3), date(2026, 11, 6))],
            ('15.11.2026-30.11.2026', 'Vozni red nadomestnega prevoza: Divača - Koper in obratno (15., 16. ter 29. in 30. november).'):
                [(date(2026, 11, d), date(2026, 11, d)) for d in (15, 16, 29, 30)],
            ('15.11.2026-17.11.2026', 'Vozni red nadomestnega prevoza: Ivanjkovci - Ljutomer / Murska Sobota in obratno (15. in 17. 11.).'):
                [(date(2026, 11, 15), date(2026, 11, 15)), (date(2026, 11, 17), date(2026, 11, 17))],
            ('14.11.2026-15.11.2026', 'Vozni red nadomestnega prevoza: Maribor - Špilje (A) in obratno (14. - 15. november).'):
                [(date(2026, 11, 14), date(2026, 11, 15))],
            ('07.11.2026-11.11.2026', 'Vozni red nadomestnega prevoza: Ljubljana – Jesenice – Beljak (A) in obratno (7. – 11. november).'):
                [(date(2026, 11, 7), date(2026, 11, 11))],
        }
        for (days, title), spans in cases.items():
            self.assertEqual(self.days(item(1, days, title, 'x')), spans, title)


class Uploaded(SimpleTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.file = Path(self.dir.name) / 'sz-list.json'
        override = override_settings(PRESTOP_SZ_LIST_FILE=str(self.file))
        override.enable()
        self.addCleanup(override.disable)
        sz_list._loaded.update(stamp=None, value=None)
        self.addCleanup(sz_list._loaded.update, stamp=None, value=None)

    def upload(self, page=PAGE, at=NOW):
        sz_list.save(sz_list.parse(page), at)


class RecordTests(Uploaded):
    def test_each_replacement_timetable_in_effect_is_a_record_with_szs_own_number(self):
        self.upload()
        records = {r['ID_ovire'][0]: r for r in sz_list.records(date(2026, 11, 1))}
        self.assertEqual(sorted(records), ['11268', '11285', '9459'])  # works, notices and the extra connecting bus are none
        r = records['11285']
        self.assertEqual(r['Relacija'], ['Divača - Koper'])
        self.assertEqual(r['Cas'], ['09.11.2026-09.11.2026, 30.11.2026-30.11.2026'])
        self.assertEqual(r['CasVir'], ['title'])

    def test_a_timetable_read_by_the_sync_is_the_one_linked(self):
        from prestop_api.szpdf import sync
        self.upload()
        self.assertEqual(sync.notice_pdfs(sz_list.records(date(2026, 11, 1)))['11285']['urls'], [PDF])

    def test_a_timetable_past_its_last_day_is_none(self):
        self.upload()
        self.assertEqual([r['ID_ovire'][0] for r in sz_list.records(date(2026, 12, 1))], ['9459'])

    def test_no_upload_no_records(self):
        self.assertEqual(sz_list.records(date(2026, 11, 1)), [])


class FirstOfNovember(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 11, 1, 12, tzinfo=tz or LOCAL)


class ReadNoticesTests(Uploaded):
    POST = {'ID_ovire': ['1000000001'], 'Naslov': ['Post'], 'Relacija': ['X'], 'Cas': ['02.11.2026-06.11.2026'], 'Opis': ['<p><a href="https://potniski.sz.si/wp-content/uploads/2026/10/Ljubljana-Jesenice.pdf">x</a></p>'],
            'CasVir': ['title'], 'Povezava': ['https://potniski.sz.si/wp-content/uploads/2026/10/Ljubljana-Jesenice.pdf'], 'Vir': ['potniski.sz.si']}

    def read(self, raw):
        with (mock.patch.object(closures.operator_notices.sz_news, 'peek', return_value=mock.Mock(value=[])),
              mock.patch.object(closures, 'datetime', FirstOfNovember),
              mock.patch.object(closures.operator_notices, 'sz_timetable_records', return_value=[self.POST])):
            return {r['ID_ovire'][0] for r in closures._with_posted_timetables(raw)}

    def test_the_list_is_a_better_record_than_a_post_linking_the_same_pdf(self):
        self.upload()
        self.assertEqual(self.read([]), {'11268', '11285', '9459'})

    def test_a_notice_naming_its_trains_is_a_better_record_than_the_list(self):
        self.upload()
        known = {'ID_ovire': ['5'], 'Naslov': ['z'], 'Opis': [f'<p><a href="{PDF}">z</a></p>']}
        self.assertEqual(self.read([known]), {'5', '11268', '9459'})

    def test_without_an_upload_the_posts_are_read_as_before(self):
        self.assertEqual(self.read([]), {'1000000001'})

    def leading(self, theirs, at=None):
        self.upload(at=at or datetime.now().timestamp())
        with (override_settings(PRESTOP_SZSITE_NOTICES=True), mock.patch.object(closures.zamudil, 'notice_records', return_value=theirs),
              mock.patch.object(closures.operator_notices.sz_news, 'peek', return_value=None), mock.patch.object(closures, 'datetime', FirstOfNovember)):
            return closures.read_notices()

    def test_with_the_reader_on_szs_list_leads_and_takes_zamudils_trains(self):
        known = {'ID_ovire': ['5'], 'Naslov': ['z'], 'Opis': [f'<p><a href="{PDF}">z</a></p>'], 'Vlaki': [['2418', '2424']], 'VlakiPoDnevih': [{'2026-11-09': ['2418']}]}
        other = {'ID_ovire': ['6'], 'Naslov': ['only zamudil'], 'Opis': ['<p>no timetable</p>'], 'Vlaki': [['640']]}
        raw, source = self.leading([known, other])
        self.assertEqual(source, 'szsite')
        records = {r['ID_ovire'][0]: r for r in raw}
        self.assertEqual(sorted(records), ['11268', '11285', '6', '9459'])  # SŽ's number, not zamudil's, for the same PDF
        self.assertEqual(records['11285']['Vlaki'], [['2418', '2424']])
        self.assertEqual(records['11285']['VlakiPoDnevih'], [{'2026-11-09': ['2418']}])
        self.assertEqual(records['11285']['CasVir'], ['title'])
        self.assertNotIn('Vlaki', records['11268'])

    def test_a_stale_list_or_the_switch_off_puts_zamudil_first_again(self):
        known = {'ID_ovire': ['5'], 'Naslov': ['z'], 'Opis': [f'<p><a href="{PDF}">z</a></p>']}
        stale = datetime.now().timestamp() - closures.READER_FRESH - 60
        self.assertEqual(self.leading([known], at=stale)[1], 'zamudil')
        self.upload(at=datetime.now().timestamp())
        with mock.patch.object(closures.zamudil, 'notice_records', return_value=[known]), mock.patch.object(closures.operator_notices.sz_news, 'peek', return_value=None):
            self.assertEqual(closures.read_notices()[1], 'zamudil')  # PRESTOP_SZSITE_NOTICES off (tests' default)

    def test_with_zamudil_off_the_list_alone_is_an_answer(self):
        raw, source = self.leading([])
        self.assertEqual((source, sorted(r['ID_ovire'][0] for r in raw)), ('szsite', ['11268', '11285', '9459']))

    def test_an_upload_changes_the_version_the_notices_are_read_again_by(self):
        with mock.patch.object(closures.zamudil, 'version', return_value=()), mock.patch.object(closures.operator_notices.sz_news, 'peek', return_value=None):
            before = closures._notices_version()
            self.upload()
            self.assertNotEqual(closures._notices_version(), before)


class AlertTests(Uploaded):
    def alerts(self, known=None):
        with mock.patch.object(closures, 'train_routes', side_effect=lambda numbers: sorted(f'r{n}' for n in numbers)):
            return by_id_of(sz_list.alerts(known if known is not None else [], NOW))

    def test_every_notice_still_to_come_is_an_alert_in_the_list(self):
        self.upload()
        found = self.alerts()
        self.assertEqual(len(found), 7)
        n = found['sz-list:11291']
        self.assertEqual(n['operatorId'], 'IJPP:1161')
        self.assertEqual(n['source'], 'sz')
        self.assertTrue(n['validFrom'].startswith('2026-11-0'))
        self.assertIn('7.00 - 15.00', n['message'])

    def test_a_notice_past_its_last_day_is_none(self):
        page = item(1, '24.10.2026-31.10.2026', 'OBVESTILO: Konec (24. 10. - 31. 10.).', 'Konec.')
        self.upload(page + LOADING)
        self.assertEqual(sorted(self.alerts()), ['sz-list:9903'])

    def test_works_on_the_line_stay_in_the_list_and_off_the_trains(self):
        self.upload()
        n = self.alerts()['sz-list:11291']
        self.assertEqual(n['routeIds'], [])
        self.assertEqual(n['kind'], 'delay')
        self.assertNotIn('_leg_notice', n)

    def test_a_notice_naming_its_trains_reaches_those_trains_journeys(self):
        self.upload()
        n = self.alerts()['sz-list:11341']
        self.assertEqual(n['routeIds'], ['r853', 'r854', 'r857', 'r858'])
        self.assertTrue(n['_leg_notice'])

    def test_a_timetables_days_are_its_only_days(self):
        self.upload()
        n = self.alerts()['sz-list:11285']
        self.assertEqual(n['_dates'], frozenset({'20261109', '20261130'}))
        self.assertEqual(n['sourceUrl'], PDF)
        self.assertEqual(n['kind'], 'replacement')

    def test_a_notice_known_by_title_is_not_shown_twice(self):
        self.upload()
        known = [{'id': 'alert:x', 'title': 'Vozni red nadomestnega prevoza: Divača - Koper in obratno (9. in 30. november).', 'source': 'sz'}]
        self.assertNotIn('sz-list:11285', self.alerts(known))

    def zamudils(self, title, text='x'):
        return {'id': closures.ZAMUDIL_PREFIX + title[:9], 'title': title, 'message': text, 'source': 'sz', 'sourceUrl': 'u', 'routeIds': ['r1'],
                '_to': NOW + 86400, 'validTo': 'v', 'to': 'v'}

    def test_zamudils_copy_gets_the_lists_days_and_keeps_its_trains(self):
        self.upload()
        known = [self.zamudils('OPOZORILO: Nakladanje vozil se zaključi vsaj 10 minut pred rednim odhodom avtovlaka.')]
        self.assertNotIn('sz-list:9903', self.alerts(known))
        self.assertTrue(known[0]['validTo'].startswith('2026-12-12'))
        self.assertEqual(known[0]['routeIds'], ['r1'])

    def test_zamudils_second_item_of_one_notice_goes(self):
        self.upload()
        known = [self.zamudils('Nakladanje vozil na postaji Nova Gorica je končano 15 minut pred odhodom avtovlaka'),
                 self.zamudils('OPOZORILO: Nakladanje vozil se zaključi vsaj 10 minut pred rednim odhodom avtovlaka.')]
        self.alerts(known)
        self.assertEqual([a['title'] for a in known], ['OPOZORILO: Nakladanje vozil se zaključi vsaj 10 minut pred rednim odhodom avtovlaka.'])

    def test_zamudils_item_titled_by_its_text_gets_the_lists_title(self):
        self.upload()
        known = [self.zamudils('Nakladanje vozil na postaji Nova Gorica je končano 15 minut pred odhodom avtovlaka')]
        self.alerts(known)
        self.assertTrue(known[0]['title'].startswith('OPOZORILO'))

    def test_a_short_title_is_no_proof_of_the_same_notice(self):
        self.upload()
        self.assertIn('sz-list:9903', self.alerts([self.zamudils('Nakladanje vozil')]))

    def test_the_operators_notices_include_the_list_and_posts_do_not_repeat_it(self):
        self.upload()
        with (mock.patch.object(operator_notices, 'arriva_site_alerts', return_value=[]),
              mock.patch.object(operator_notices, 'sz_alerts', side_effect=lambda known: [known[-1]['id']]) as posts,
              mock.patch.object(closures, 'train_routes', return_value=[]), mock.patch.object(sz_list.time, 'time', return_value=NOW)):
            found = operator_notices.alerts([])
        self.assertEqual(len(found), 8)
        posts.assert_called_once()


def by_id_of(alerts):
    return {a['id']: a for a in alerts}


class CommandTests(Uploaded):
    def run_import(self, body: bytes):
        out = StringIO()
        with mock.patch('sys.stdin', mock.Mock(buffer=mock.Mock(read=lambda n: body))):
            call_command('sz_notices', '--import', stdout=out)
        return out.getvalue()

    def test_import_saves_it_and_says_what_it_has(self):
        self.assertIn('7 notices', self.run_import(PAGE.encode()))
        self.assertEqual(len(json.loads(self.file.read_text(encoding='utf-8'))['notices']), 7)

    def test_a_page_without_notices_leaves_the_old_ones(self):
        self.upload()
        before = self.file.read_bytes()
        with self.assertRaises(CommandError):
            self.run_import(b'<html><title>Just a moment...</title></html>')
        self.assertEqual(self.file.read_bytes(), before)

    def test_too_much_is_refused(self):
        with self.assertRaises(CommandError):
            self.run_import(b'x' * (sz_list.LIMIT + 1))


class HealthTests(Uploaded):
    def test_nothing_before_the_first_upload(self):
        self.assertEqual(sz_list.health(), [])

    def test_fresh_then_stale_and_never_unavailable(self):
        self.upload(at=NOW)
        with mock.patch.object(sz_list.time, 'time', return_value=NOW + 3600):
            self.assertEqual(sz_list.health()[0]['status'], 'live')
        with mock.patch.object(sz_list.time, 'time', return_value=NOW + sz_list.LIVE_FOR + 1):
            self.assertEqual(sz_list.health()[0]['status'], 'stale')


class HorizonTests(SimpleTestCase):
    def test_the_whole_list_reaches_weeks_ahead_and_a_station_only_days(self):
        self.assertGreaterEqual(views.ALERT_LIST_HORIZON, 30 * 86400)
        self.assertLessEqual(views.ALERT_HORIZON, 3 * 86400)
