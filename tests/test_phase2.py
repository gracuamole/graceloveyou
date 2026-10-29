import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import phase2
import test_recommendations as fixtures


class EntryPoint(unittest.TestCase):
    def test_offline_cli_and_fixture_send_block(self):
        coverage = fixtures.Coverage()
        coverage.setUp()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'forecast.json'
            path.write_text(json.dumps({'daily': [coverage.day]}))
            command = [sys.executable, str(Path(phase2.__file__)), '--fixture', str(path), '--date', coverage.day['date']]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('PREVIEW ONLY', result.stdout)
            self.assertIn('18:00–18:10', result.stdout)
            result = subprocess.run(command + ['--send'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('cannot be posted', result.stderr)

    def test_existing_transport_preview_never_posts(self):
        coverage = fixtures.Coverage()
        coverage.setUp()
        transport = MagicMock()
        transport.fetch_full_forecast.return_value = {'daily': [coverage.day]}
        transport.SPOT_NAME = 'Test'
        with patch.dict(sys.modules, {'main4_pkge_indi': transport}), patch.object(sys, 'argv', ['phase2', '--date', coverage.day['date']]), patch('builtins.print'):
            phase2.main()
        transport.cache.clear.assert_called_once()
        transport.fetch_full_forecast.assert_called_once_with(transport.SPOT_ID, days=3)
        transport.curl_requests.post.assert_not_called()

    def test_direct_send_is_disabled(self):
        with patch.object(sys, 'argv', ['phase2', '--send']):
            with self.assertRaises(SystemExit):
                phase2.main()
