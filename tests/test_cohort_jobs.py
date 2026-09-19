import fcntl
import os
import tempfile
import unittest
from unittest.mock import patch, Mock

import app
import cohort_jobs as jobs
from db import get_db, init_db
from scripts import trigger_cohort_refresh as trigger


class TestCohortJobs(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, 'cache.db')
        conn = get_db(self.path)
        init_db(conn)
        conn.close()
        self.patches = [patch.object(jobs, 'DB_PATH', self.path),
                        patch.object(jobs, 'get_db', side_effect=lambda: get_db(self.path))]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def test_live_lock_prevents_duplicate_job_and_stale_state_is_detected(self):
        jobs.save_refresh_status({'run_id': 'one', 'state': 'running'})
        with open(self.path + '.refresh.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with patch.object(jobs.subprocess, 'Popen') as spawn:
                self.assertTrue(jobs.start_refresh_job()['already_running'])
                self.assertEqual(jobs.refresh_status()['state'], 'running')
                spawn.assert_not_called()
        self.assertEqual(jobs.refresh_status()['state'], 'failed')

    def test_launcher_passes_locked_descriptor_to_child(self):
        inherited = []
        def spawn(*args, **kwargs):
            fd = kwargs['pass_fds'][0]
            self.assertEqual(kwargs['env']['RYSK_REFRESH_LOCK_FD'], str(fd))
            inherited.append(os.dup(fd))
            return Mock()
        try:
            with patch.object(jobs.subprocess, 'Popen', side_effect=spawn):
                status = jobs.start_refresh_job()
            self.assertEqual(status['state'], 'queued')
            with open(self.path + '.refresh.lock', 'a') as other:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(jobs.refresh_status()['run_id'], status['run_id'])
        finally:
            for fd in inherited:
                os.close(fd)

    def test_authentication_guards_get_and_post(self):
        client = app.app.test_client()
        with patch.object(app, 'ADMIN_BACKFILL_TOKEN', 'test-token'):
            for method in (client.get, client.post):
                self.assertEqual(method('/api/admin/cohort-refresh').status_code, 401)
            with patch.object(jobs, 'start_refresh_job', return_value={'run_id': 'one'}) as start:
                response = client.post('/api/admin/cohort-refresh', headers={'X-Admin-Token': 'test-token'})
                self.assertEqual(response.status_code, 202)
                start.assert_called_once_with()
            response = client.get('/api/admin/cohort-refresh', headers={'X-Admin-Token': 'test-token'})
            self.assertEqual(response.json['job']['state'], 'never_run')


class TestRenderCron(unittest.TestCase):
    def test_polls_to_completion_and_fails_on_worker_error(self):
        for state in ('complete', 'failed'):
            with self.subTest(state=state):
                session = Mock()
                session.headers = {}
                session.post.return_value.json.return_value = {'job': {'run_id': 'one'}}
                session.get.return_value.json.return_value = {'job': {'run_id': 'one', 'state': state}}
                context = Mock()
                context.__enter__ = Mock(return_value=session)
                context.__exit__ = Mock(return_value=False)
                with patch.dict(os.environ, {'RYSK_SERVICE_URL': 'https://example.test', 'ADMIN_BACKFILL_TOKEN': 'test'}), \
                     patch.object(trigger.requests, 'Session', return_value=context), \
                     patch.object(trigger.time, 'sleep'):
                    if state == 'failed':
                        with self.assertRaises(RuntimeError):
                            trigger.main()
                    else:
                        trigger.main()
                self.assertEqual(session.headers['X-Admin-Token'], 'test')
