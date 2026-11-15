"""Exercise merge preservation, conflict recovery, CI refusal and schedule recovery offline."""
import datetime
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import check_sync
import sync_upstream


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.upstream = self.root / 'upstream'
        self.fork = self.root / 'fork'
        self.git('init', '--initial-branch=main', str(self.upstream))
        self.configure(self.upstream)
        (self.upstream / 'shared').write_text('base\n')
        self.commit(self.upstream, 'base')
        self.git('clone', str(self.upstream), str(self.fork))
        self.configure(self.fork)
        self.git('-C', str(self.fork), 'switch', '-c', 'kopiro')
        self.before_cwd = Path.cwd()
        os.chdir(self.fork)
        self.addCleanup(os.chdir, self.before_cwd)

    def git(self, *args):
        return subprocess.check_output(['git', *args], text=True, stderr=subprocess.DEVNULL).strip()

    def configure(self, repo):
        self.git('-C', str(repo), 'config', 'user.name', 'Fixture')
        self.git('-C', str(repo), 'config', 'user.email', 'fixture@example.invalid')

    def commit(self, repo, message):
        self.git('-C', str(repo), 'add', '.')
        self.git('-C', str(repo), 'commit', '-m', message)

    def test_merge_preserves_custom_changes_and_includes_upstream(self):
        (self.fork / 'ours').write_text('customized feature\n')
        self.commit(self.fork, 'feature')
        before = self.git('rev-parse', 'HEAD')
        (self.upstream / 'new').write_text('upstream improvement\n')
        self.commit(self.upstream, 'upstream improvement')
        upstream = sync_upstream.prepare_merge(str(self.upstream))
        self.assertEqual((self.fork / 'ours').read_text(), 'customized feature\n')
        self.assertEqual((self.fork / 'new').read_text(), 'upstream improvement\n')
        self.git('merge-base', '--is-ancestor', before, 'HEAD')
        self.git('merge-base', '--is-ancestor', upstream, 'HEAD')
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_conflict_restores_the_customized_checkout(self):
        (self.fork / 'shared').write_text('our change\n')
        self.commit(self.fork, 'our change')
        before = self.git('rev-parse', 'HEAD')
        (self.upstream / 'shared').write_text('upstream change\n')
        self.commit(self.upstream, 'upstream change')
        with self.assertRaisesRegex(RuntimeError, 'conflicts'):
            sync_upstream.prepare_merge(str(self.upstream))
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)
        self.assertEqual((self.fork / 'shared').read_text(), 'our change\n')
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_no_upstream_changes_leave_history_untouched(self):
        before = self.git('rev-parse', 'HEAD')
        self.assertIsNone(sync_upstream.prepare_merge(str(self.upstream)))
        self.assertEqual(self.git('rev-parse', 'HEAD'), before)


class GuardTests(unittest.TestCase):
    def test_failed_ci_never_advances_the_customized_branch(self):
        commands = []

        def run(*args, check=True):
            commands.append(args)
            if args[:3] == ('git', 'branch', '--show-current'):
                return 'kopiro'
            if args[:2] == ('git', 'rev-parse'):
                return 'candidate-sha'
            if args[:3] == ('gh', 'run', 'list'):
                return json.dumps([{'databaseId': 123, 'headSha': 'candidate-sha'}])
            if args[:3] == ('gh', 'run', 'watch'):
                return SimpleNamespace(returncode=1)
            return ''

        with patch.object(sync_upstream, 'run', run), patch.object(sync_upstream, 'prepare_merge', return_value='upstream-sha'), patch.dict(os.environ, {'GITHUB_RUN_ID': '456'}):
            with self.assertRaisesRegex(RuntimeError, 'CI failed'):
                sync_upstream.synchronize('owner/fork', 'upstream', 'kopiro')
        self.assertIn(('git', 'push', 'origin', 'HEAD:refs/heads/fork-sync/456'), commands)
        self.assertNotIn(('git', 'push', 'origin', 'HEAD:refs/heads/kopiro'), commands)

    def test_manual_pause_is_respected(self):
        with patch.object(check_sync, 'gh', return_value=json.dumps({'state': 'disabled_manually'})) as gh:
            check_sync.check('owner/fork')
        self.assertEqual(gh.call_count, 1)

    def test_inactivity_disable_is_reenabled_and_a_missed_run_dispatched(self):
        with patch.object(check_sync, 'gh', side_effect=[json.dumps({'state': 'disabled_inactivity'}), '', '[]', '']) as gh:
            check_sync.check('owner/fork')
        self.assertEqual(gh.call_args_list[1].args[:2], ('workflow', 'enable'))
        self.assertEqual(gh.call_args_list[-1].args[:2], ('workflow', 'run'))

    def test_a_recent_run_is_not_dispatched_twice(self):
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with patch.object(check_sync, 'gh', side_effect=[json.dumps({'state': 'active'}), json.dumps([{
            'createdAt': now, 'status': 'completed', 'conclusion': 'success', 'url': 'https://example.invalid/run'}])]) as gh:
            check_sync.check('owner/fork')
        self.assertEqual(gh.call_count, 2)


if __name__ == '__main__':
    unittest.main()
