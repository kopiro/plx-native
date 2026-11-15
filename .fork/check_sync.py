"""Recover an inactivity-disabled or missed upstream sync without overriding a manual pause."""
import argparse
import datetime
import json
import os
import plistlib
import shutil
import subprocess
from pathlib import Path

WORKFLOW = 'sync-upstream.yml'


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True)


def check(repo):
    state = json.loads(gh('api', f'repos/{repo}/actions/workflows/{WORKFLOW}'))['state']
    if state == 'disabled_inactivity':
        gh('workflow', 'enable', WORKFLOW, '--repo', repo)
    elif state != 'active':
        print(f'Sync workflow is {state}; respecting its manual pause.')
        return
    rows = json.loads(gh('run', 'list', '--repo', repo, '--workflow', WORKFLOW, '--limit', '1',
                        '--json', 'createdAt,status,conclusion,url'))
    if rows:
        last = rows[0]
        if last['status'] != 'completed':
            print(f'Sync is already running: {last["url"]}')
            return
        age = datetime.datetime.now(datetime.timezone.utc) - datetime.datetime.fromisoformat(last['createdAt'].replace('Z', '+00:00'))
        if age < datetime.timedelta(hours=30):
            print(f'Latest sync: {last["conclusion"]}; {last["url"]}')
            return
    gh('workflow', 'run', WORKFLOW, '--repo', repo, '--ref', 'kopiro')
    print('Dispatched the missed upstream synchronization.')


def install(repo):
    label = 'me.kopiro.plxnative-sync-health'
    logs = Path.home() / 'Library/Logs/plxnative-sync'
    logs.mkdir(parents=True, exist_ok=True)
    path = Path.home() / f'Library/LaunchAgents/{label}.plist'
    python = shutil.which('python3')
    gh_dir = str(Path(shutil.which('gh')).parent)
    config = {
        'Label': label,
        'ProgramArguments': [python, str(Path(__file__).resolve()), '--repo', repo],
        'StartInterval': 3600,
        'RunAtLoad': True,
        'EnvironmentVariables': {'PATH': gh_dir + ':/opt/homebrew/bin:/usr/bin:/bin'},
        'StandardOutPath': str(logs / 'health.log'),
        'StandardErrorPath': str(logs / 'health-error.log'),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(config))
    domain = f'gui/{os.getuid()}'
    subprocess.run(['launchctl', 'bootout', domain, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['launchctl', 'bootstrap', domain, str(path)], check=True)
    print(f'Installed {label}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    install(args.repo) if args.install else check(args.repo)
