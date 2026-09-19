"""Render cron client: start and monitor a refresh on the disk-owning web service."""
import os
import time

import requests


def main():
    url = os.environ['RYSK_SERVICE_URL'].rstrip('/') + '/api/admin/cohort-refresh'
    token = os.environ['ADMIN_BACKFILL_TOKEN']
    with requests.Session() as session:
        session.headers['X-Admin-Token'] = token
        response = session.post(url, timeout=30)
        response.raise_for_status()
        job = response.json()['job']
        run_id = job.get('run_id')
        if not run_id:
            raise RuntimeError('Refresh is locked but has no observable job ID')
        print(f'Monitoring cohort refresh {run_id}', flush=True)
        deadline = time.monotonic() + 6 * 3600
        while time.monotonic() < deadline:
            time.sleep(15)
            try:
                response = session.get(url, timeout=30)
                response.raise_for_status()
                status = response.json()['job']
            except requests.RequestException:
                # A transient web deploy should not silently mark a cron run successful.
                continue
            if status.get('run_id') != run_id:
                raise RuntimeError('Refresh job changed before completion was observed')
            if status.get('state') == 'complete':
                print('Cohort refresh completed on the persistent database', flush=True)
                for chain in status.get('by_chain', []):
                    print(f"{chain['chain_name']}: {chain['attributed_trades']}/{chain['total_trades']} attributed", flush=True)
                return
            if status.get('state') == 'failed':
                raise RuntimeError('Cohort refresh failed; inspect the authenticated job status and service log')
        raise RuntimeError('Cohort refresh did not complete within six hours')


if __name__ == '__main__':
    main()
