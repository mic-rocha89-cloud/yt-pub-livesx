"""Offline transcript-stage regressions; no browser, AI or YouTube calls."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GIT_BASH = Path('C:/Program Files/Git/bin/bash.exe')
BASH = str(GIT_BASH) if GIT_BASH.is_file() else shutil.which('bash')


@unittest.skipUnless(BASH, 'Bash is required to test the clip script')
class TranscriptFailureTests(unittest.TestCase):
    def run_stage(self, fake_downloader):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Execute the actual transcript stage, with local stand-ins for its tools.
            script = (ROOT / 'scripts' / 'yt-clip').read_text(encoding='utf-8')
            stage = script.split('echo "==> [1/5]', 1)[1].split('# ETAPA 2:', 1)[0]
            prelude = 'set -euo pipefail\nJOB_DIR="$1"\nVIDEO_ID=test_video\n'
            prelude += 'yt-dlp() {\n' + fake_downloader + '\n}\n'
            prelude += 'mv() { printf "mv called\\n" >> "$JOB_DIR/moves"; command mv "$@"; }\n'
            test_script = root / 'stage.sh'
            test_script.write_text(prelude + 'echo "==> [1/5]' + stage, encoding='utf-8')
            result = subprocess.run([BASH, str(test_script), str(root)],
                                    capture_output=True, text=True, encoding='utf-8',
                                    errors='replace', timeout=10)
            attempts = (root / 'attempts').read_text().splitlines()
            return result, attempts, (root / 'moves').exists()

    def test_rate_limit_with_cookies_does_not_retry_or_rename_partial_file(self):
        result, attempts, moved = self.run_stage('''
printf 'attempt\n' >> "$JOB_DIR/attempts"
touch "$JOB_DIR/$VIDEO_ID.pt.json3"
echo "ERROR: Unable to download subtitles: HTTP Error 429: Too Many Requests" >&2
return 7
''')
        self.assertEqual(result.returncode, 7)
        self.assertEqual(len(attempts), 1)
        self.assertIn('HTTP Error 429', result.stderr)
        self.assertIn('Aguarde', result.stderr)
        self.assertFalse(moved)

    def test_unavailable_browser_can_fallback_but_download_error_is_preserved(self):
        result, attempts, moved = self.run_stage('''
printf 'attempt\n' >> "$JOB_DIR/attempts"
if [[ "$1" == '--cookies-from-browser' ]]; then
  echo 'ERROR: could not find firefox cookies database' >&2
  return 1
fi
echo 'ERROR: HTTP Error 403: Forbidden' >&2
return 5
''')
        self.assertEqual(result.returncode, 5)
        self.assertEqual(len(attempts), 2)
        self.assertIn('HTTP Error 403', result.stderr)
        self.assertFalse(moved)

    def test_anonymous_rate_limit_stops_without_further_attempts(self):
        result, attempts, moved = self.run_stage('''
printf 'attempt\n' >> "$JOB_DIR/attempts"
if [[ "$1" == '--cookies-from-browser' ]]; then return 1; fi
echo 'ERROR: HTTP Error 429: Too Many Requests' >&2
return 1
''')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(attempts), 2)
        self.assertIn('Aguarde', result.stderr)
        self.assertFalse(moved)

    def test_missing_portuguese_subtitle_is_not_reported_as_success(self):
        result, attempts, moved = self.run_stage('''
printf 'attempt\n' >> "$JOB_DIR/attempts"
return 0
''')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(attempts), 1)
        self.assertIn('legenda pt', result.stderr)
        self.assertFalse(moved)

    def test_successful_download_renames_subtitle_and_continues(self):
        result, attempts, moved = self.run_stage('''
printf 'attempt\n' >> "$JOB_DIR/attempts"
printf '{"events":[]}' > "$JOB_DIR/$VIDEO_ID.pt.json3"
return 0
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(attempts), 1)
        self.assertTrue(moved)


if __name__ == '__main__':
    unittest.main()
