"""Never replace the archive still being read by a running executable."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import os
import unittest
from build_safety import ensure_executable_not_running


@unittest.skipUnless(os.name=='nt','Windows executable deployment')
class BuildSafetyTests(unittest.TestCase):
    def test_active_target_is_rejected_and_staging_build_is_allowed(self):
        active=Path.cwd()/'TheOnigiriShop.exe'
        with patch('build_safety.subprocess.run',return_value=SimpleNamespace(stdout=json.dumps(str(active)))):
            with self.assertRaisesRegex(RuntimeError,'Close all'):
                ensure_executable_not_running(active)
            ensure_executable_not_running(Path.cwd()/'staging'/'TheOnigiriShop.exe')

    def test_no_running_app_allows_build(self):
        with patch('build_safety.subprocess.run',return_value=SimpleNamespace(stdout='')):
            ensure_executable_not_running(Path.cwd()/'TheOnigiriShop.exe')
