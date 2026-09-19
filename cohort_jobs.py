"""Launch refresh work on the web service that owns Render's persistent disk."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from db import DB_PATH, get_db, init_db


def save_refresh_status(data):
    conn = get_db()
    init_db(conn)
    try:
        conn.execute('INSERT OR REPLACE INTO sync_meta(key,value) VALUES (?,?)',
                     ('last_cohort_refresh_json', json.dumps(data)))
        conn.commit()
    finally:
        conn.close()


def refresh_status():
    conn = get_db()
    try:
        row = conn.execute("SELECT value FROM sync_meta WHERE key='last_cohort_refresh_json'").fetchone()
        status = json.loads(row[0]) if row else {'state': 'never_run'}
    finally:
        conn.close()
    if status.get('state') in ('queued', 'running'):
        with open(DB_PATH + '.refresh.lock', 'a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return status
            # A deployment or process exit can leave stale running metadata.
            # Re-read under the lock in case the worker completed in between.
            conn = get_db()
            try:
                row = conn.execute("SELECT value FROM sync_meta WHERE key='last_cohort_refresh_json'").fetchone()
                status = json.loads(row[0]) if row else {'state': 'never_run'}
            finally:
                conn.close()
            if status.get('state') in ('queued', 'running'):
                status.update(state='failed', success=False, finished_at=int(time.time()),
                              error='Refresh process exited before recording completion; rerun to resume cached progress')
                save_refresh_status(status)
    return status


def start_refresh_job():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    lock = open(DB_PATH + '.refresh.lock', 'a')
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {**refresh_status(), 'already_running': True}
        run_id = uuid.uuid4().hex
        status = {'run_id': run_id, 'state': 'queued', 'started_at': int(time.time()), 'success': False}
        save_refresh_status(status)
        env = dict(os.environ)
        env['RYSK_REFRESH_LOCK_FD'] = str(lock.fileno())
        env['RYSK_REFRESH_RUN_ID'] = run_id
        root = Path(__file__).resolve().parent
        with open(DB_PATH + '.refresh.log', 'a') as log:
            subprocess.Popen(
                [sys.executable, str(root / 'scripts' / 'refresh_cohorts.py')], cwd=str(root),
                env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                start_new_session=True, pass_fds=(lock.fileno(),),
            )
        return status
    except Exception as exc:
        if 'status' in locals():
            save_refresh_status({**status, 'state': 'failed', 'error': str(exc), 'finished_at': int(time.time())})
        raise
    finally:
        # The child inherits this open file description, retaining its flock.
        lock.close()
