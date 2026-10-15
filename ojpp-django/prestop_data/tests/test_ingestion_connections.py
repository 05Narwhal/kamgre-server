"""A6: each ingestion job run checks Django's database connection first, like a request (run_ingestion.py)."""
import asyncio
from unittest import mock

from django.test import SimpleTestCase

from prestop_data.management.commands import run_ingestion


class FreshConnectionTests(SimpleTestCase):
    def test_sync_and_async_jobs_check_the_connection_around_each_run(self):
        calls = []
        with mock.patch.object(run_ingestion, 'close_old_connections', side_effect=lambda: calls.append('check')):
            run_ingestion.fresh_connection(lambda: calls.append('job'))()

            async def job():
                calls.append('async job')
            wrapped = run_ingestion.fresh_connection(job)
            self.assertTrue(asyncio.iscoroutinefunction(wrapped))
            asyncio.run(wrapped())
        self.assertEqual(calls, ['check', 'job', 'check', 'check', 'async job', 'check'])

    def test_a_failing_run_still_leaves_the_connection_checked(self):
        calls = []
        with mock.patch.object(run_ingestion, 'close_old_connections', side_effect=lambda: calls.append('check')):
            with self.assertRaises(RuntimeError):
                run_ingestion.fresh_connection(mock.Mock(side_effect=RuntimeError('db')))()
        self.assertEqual(calls, ['check', 'check'])
