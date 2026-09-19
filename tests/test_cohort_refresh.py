import json
import os
import tempfile
import unittest
from unittest.mock import patch

from db import get_db, init_db
from scripts import refresh_cohorts as job


class TestDailyRefresh(unittest.TestCase):
    def test_incremental_run_covers_both_chains_and_saves_outcome(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'test.db')
            conn = get_db(path)
            init_db(conn)
            conn.close()
            with patch.object(job, 'DB_PATH', path), \
                 patch.object(job, 'get_db', side_effect=lambda: get_db(path)), \
                 patch.object(job, 'save_refresh_status'), \
                 patch.object(job, 'sync', return_value={'complete': True}) as sync, \
                 patch.object(job, 'recover', return_value=0) as recover:
                self.assertEqual(job.refresh(), 0)
            sync.assert_called_once_with()
            self.assertEqual([call.args[0][1] for call in recover.call_args_list], ['1', '999'])
            conn = get_db(path)
            data = json.loads(conn.execute("select value from sync_meta where key='last_cohort_refresh_json'").fetchone()[0])
            self.assertTrue(data['success'])
            self.assertIn('finished_at', data)
            conn.close()
