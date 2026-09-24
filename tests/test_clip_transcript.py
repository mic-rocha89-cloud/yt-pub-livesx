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
    def run_stage(self, fake_downloader, with_node=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            # Execute the actual transcript stage, with local stand-ins for its tools.
            script = (ROOT / 'scripts' / 'yt-clip').read_text(encoding='utf-8')
            stage = script.split('echo "==> [1/5]', 1)[1].split('# ETAPA 2:', 1)[0]
            prelude = 'set -euo pipefail\nJOB_DIR="$1"\nVIDEO_ID=test_video\n'
            prelude += 'YT_DLP_JS_ARGS=(--js-runtimes node)\n' if with_node else 'YT_DLP_JS_ARGS=()\n'
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

    def test_node_argument_reaches_authenticated_and_anonymous_downloads(self):
        result, attempts, moved = self.run_stage('''
printf 'attempt\n' >> "$JOB_DIR/attempts"
if [[ " $* " != *" --js-runtimes node "* ]]; then
  echo 'missing Node runtime' >&2
  return 9
fi
if [[ "$1" == '--cookies-from-browser' ]]; then return 1; fi
printf '{"events":[]}' > "$JOB_DIR/$VIDEO_ID.pt.json3"
return 0
''', with_node=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(attempts), 2)
        self.assertTrue(moved)


@unittest.skipUnless(BASH, 'Bash is required to test runtime selection')
class JavaScriptRuntimeTests(unittest.TestCase):
    def test_node_is_used_only_if_supported_and_deno_is_absent(self):
        script = (ROOT / 'scripts' / 'yt-clip').read_text(encoding='utf-8')
        selection = 'YT_DLP_JS_ARGS=()' + script.split('YT_DLP_JS_ARGS=()', 1)[1].split('validate_media_file()', 1)[0]
        stubs = '''
set -euo pipefail
command() {
  case "$2" in
    deno) [[ "$HAS_DENO" == 1 ]] ;;
    node) [[ "$HAS_NODE" == 1 ]] ;;
    *) builtin command "$@" ;;
  esac
}
node() { return "$NODE_RESULT"; }
'''
        for has_deno, has_node, node_result, expected in [
                ('1', '1', '0', False), ('1', '0', '0', False),
                ('0', '1', '0', True), ('0', '1', '1', False), ('0', '0', '0', False)]:
            with self.subTest(deno=has_deno, node=has_node, compatible=node_result):
                env = dict(os.environ, HAS_DENO=has_deno, HAS_NODE=has_node, NODE_RESULT=node_result)
                result = subprocess.run([BASH, '-c', stubs + selection + '\ndeclare -p YT_DLP_JS_ARGS'],
                                        capture_output=True, text=True, timeout=10, env=env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual('node' in result.stdout, expected)


if __name__ == '__main__':
    unittest.main()
