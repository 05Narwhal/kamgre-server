"""Arriva's site blocks the server at times: the posts read on the deployer's PC and uploaded (`yarn server:update`)."""
import io
import json
import os
import tempfile
import time
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from prestop_api import operator_notices as notices, views
from prestop_api.tests.test_operator_notices import POSTS
from prestop_api.upstream import Snapshot

NOW = time.time()


class Stdin:
    def __init__(self, body: bytes):
        self.buffer = io.BytesIO(body)


class ArrivaUploadTests(SimpleTestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.file = Path(folder.name) / 'arriva-posts.json'
        for patcher in (self.settings(PRESTOP_ARRIVA_UPLOAD_FILE=str(self.file)), mock.patch.object(notices.arriva, '_snap', None),
                        mock.patch.dict(notices._uploaded, stamp=None, value=None)):
            patcher.enable() if hasattr(patcher, 'enable') else patcher.start()
            self.addCleanup(patcher.disable if hasattr(patcher, 'disable') else patcher.stop)

    def run_import(self, body: bytes) -> str:
        out = io.StringIO()
        with mock.patch('sys.stdin', Stdin(body)):
            call_command('arriva_notices', '--import', stdout=out)
        return out.getvalue()

    def test_an_import_reaches_the_notices_without_a_restart(self):
        self.assertIsNone(notices._arriva_posts())
        said = self.run_import(json.dumps(POSTS).encode())
        self.assertEqual(notices._arriva_posts(), POSTS)
        self.assertIn(f'{len(POSTS)} posts', said)
        self.assertEqual([p.name for p in self.file.parent.iterdir()], [self.file.name])  # no .tmp left behind

    def test_a_new_upload_is_noticed_and_an_unchanged_one_is_not_read_again(self):
        notices.save_arriva_upload(POSTS, NOW)
        first = notices.arriva_upload()
        self.assertIs(notices.arriva_upload(), first)
        notices.save_arriva_upload(POSTS[:1], NOW + 60)
        os.utime(self.file, ns=(time.time_ns() + 10 ** 9, time.time_ns() + 10 ** 9))
        self.assertEqual(notices.arriva_upload()['posts'], POSTS[:1])

    def test_anything_but_the_list_of_posts_leaves_the_notices_as_they_were(self):
        notices.save_arriva_upload(POSTS, NOW)
        for body in (b'<html>blocked</html>', b'{"code": "rest_forbidden"}', b'[]', b'[{"id": 1}]', b'[1, 2]'):
            with self.subTest(body), self.assertRaises(CommandError):
                self.run_import(body)
            self.assertEqual(notices.arriva_upload()['posts'], POSTS)
        with self.assertRaises(CommandError):
            self.run_import(b' ' * (notices.ARRIVA_LIMIT + 1))
        self.assertEqual(notices.arriva_upload()['posts'], POSTS)

    def test_a_broken_file_counts_as_no_upload(self):
        self.file.write_text('{"uploadedAt": ', encoding='utf-8')
        with self.assertLogs('prestop_api.operator_notices', 'WARNING'):
            self.assertIsNone(notices.arriva_upload())

    def test_the_newest_read_wins_whichever_it_came_from(self):
        live = [{**POSTS[0], 'id': 999}]
        notices.save_arriva_upload(POSTS, NOW)
        with mock.patch.object(notices.arriva, '_snap', Snapshot(live, NOW - 60)):
            self.assertEqual(notices._arriva_posts(), POSTS)  # the server's last read is older: blocked since
        with mock.patch.object(notices.arriva, '_snap', Snapshot(live, NOW + 60)):
            self.assertEqual(notices._arriva_posts(), live)  # the server reads the site again

    def source(self):
        with mock.patch.object(notices.arriva, 'peek', wraps=notices.arriva.peek):
            return views._arriva_source()

    def test_health_says_how_fresh_the_upload_is(self):
        self.assertEqual(self.source()['status'], 'unavailable')
        notices.save_arriva_upload(POSTS, NOW)
        self.assertEqual(self.source()['status'], 'live')
        notices.save_arriva_upload(POSTS, NOW - views.ARRIVA_UPLOAD_LIVE - 60)
        os.utime(self.file, ns=(time.time_ns() + 10 ** 9, time.time_ns() + 10 ** 9))
        entry = self.source()
        self.assertEqual(entry['status'], 'stale')  # shown all the same, and /health says so

    def test_the_status_command_without_an_upload_says_what_to_run(self):
        out = io.StringIO()
        call_command('arriva_notices', stdout=out)
        self.assertIn('yarn server:update', out.getvalue())
