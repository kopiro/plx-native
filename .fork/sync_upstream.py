"""Merge upstream into a candidate, run the existing CI, then advance the custom fork safely."""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path


def run(*args, check=True):
    result = subprocess.run(args, check=check, text=True, stdout=subprocess.PIPE)
    return result.stdout.strip() if check else result


def prepare_merge(upstream):
    if run('git', 'status', '--porcelain'):
        raise RuntimeError('Refusing to synchronize a dirty checkout')
    run('git', 'fetch', '--no-tags', upstream, 'main')
    upstream_sha = run('git', 'rev-parse', 'FETCH_HEAD')
    if run('git', 'merge-base', '--is-ancestor', upstream_sha, 'HEAD', check=False).returncode == 0:
        return None
    before = run('git', 'rev-parse', 'HEAD')
    result = run('git', 'merge', '--no-edit', upstream_sha, check=False)
    if result.returncode:
        run('git', 'merge', '--abort')
        if run('git', 'rev-parse', 'HEAD') != before:
            raise RuntimeError('Merge abort did not restore the original revision')
        raise RuntimeError('Upstream conflicts with the customized fork; resolve the conflict manually')
    return upstream_sha


def synchronize(repo, upstream, branch):
    if run('git', 'branch', '--show-current') != branch:
        raise RuntimeError(f'Check out {branch} before synchronizing')
    run_id = os.environ.get('GITHUB_RUN_ID')
    if not run_id or not run_id.isdigit():
        raise RuntimeError('Run synchronization through the GitHub workflow')
    upstream_sha = prepare_merge(upstream)
    if upstream_sha is None:
        print('The customized fork already includes upstream main.')
        return
    candidate_sha = run('git', 'rev-parse', 'HEAD')
    candidate = f'fork-sync/{run_id}'
    run('git', 'push', 'origin', f'HEAD:refs/heads/{candidate}')
    run('gh', 'workflow', 'run', 'ci.yml', '--repo', repo, '--ref', candidate)
    ci_run = None
    for _ in range(60):
        rows = json.loads(run('gh', 'run', 'list', '--repo', repo, '--workflow', 'ci.yml',
                             '--branch', candidate, '--event', 'workflow_dispatch', '--limit', '1',
                             '--json', 'databaseId,headSha'))
        if rows and rows[0]['headSha'] == candidate_sha:
            ci_run = rows[0]['databaseId']
            break
        time.sleep(5)
    if ci_run is None:
        raise RuntimeError(f'CI did not start. The customized branch is unchanged; inspect {candidate}.')
    ci_url = f'https://github.com/{repo}/actions/runs/{ci_run}'
    print(f'Validating the candidate: {ci_url}', flush=True)
    result = run('gh', 'run', 'watch', str(ci_run), '--repo', repo, '--exit-status', '--interval', '20', check=False)
    if result.returncode:
        raise RuntimeError(f'CI failed. The customized branch is unchanged. See {ci_url}')
    # A concurrent owner's push rejects this ordinary push. Never overwrite it with a force push.
    run('git', 'push', 'origin', f'HEAD:refs/heads/{branch}')
    run('git', 'push', 'origin', '--delete', candidate)
    summary = f'Merged upstream `{upstream_sha[:12]}` into `{branch}` after [CI passed]({ci_url}).\n'
    if path := os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(path).open('a') as output:
            output.write(summary)
    print(summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--upstream', default='https://github.com/plxnative/plx-native.git')
    parser.add_argument('--branch', default='kopiro')
    args = parser.parse_args()
    synchronize(args.repo, args.upstream, args.branch)


if __name__ == '__main__':
    main()
