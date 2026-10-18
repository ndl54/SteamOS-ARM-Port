#!/usr/bin/env python3
"""Metadata/icon regressions in private fixtures; never call Steam or Android."""
import contextlib
import io
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
INFO = runpy.run_path(str(ROOT / 'sm8650-overlay/usr/lib/konkr/apk-info'))
GLOBALS = INFO['main'].__globals__
APK = (ROOT / 'sm8650-overlay/usr/bin/konkr-apk').read_text()
PNG = b'\x89PNG\r\n\x1a\nfixture'  # signature fixture, deliberately not a decoded image


def function(name):
    return name + '() {' + APK.split(name + '() {', 1)[1].split('\n}\n', 1)[0] + '\n}\n'


class Archive:
    def __init__(self, files=None):
        self.files = files or {}

    def namelist(self):
        return list(self.files)

    def read(self, path):
        return self.files.get(path, b'')


def metadata(label, pkg='com.test', activity='.Main', files=None, output=None, adaptive=False):
    def axml(data):
        if data == b'adaptive':
            yield 'start', 'foreground', {1: (None, 1, 2)}
            return
        yield 'start', 'manifest', {'package': (pkg, 3, 0)}
        yield 'start', 'application', {GLOBALS['LABEL']: (label, 3, 0), GLOBALS['ICON']: (None, 1, 1)}
        yield 'start', 'activity', {GLOBALS['NAME']: (activity, 3, 0)}
        yield 'start', 'action', {GLOBALS['NAME']: ('android.intent.action.MAIN', 3, 0)}
        yield 'start', 'category', {GLOBALS['NAME']: ('android.intent.category.LAUNCHER', 3, 0)}
        yield 'end', 'activity', None

    class Resources:
        def __init__(self, data):
            pass

        def files(self, ref):
            return ['icon.xml'] if adaptive and ref == 1 else ['bad.png', 'good.png']

    out = io.StringIO()
    argv = ['apk-info', 'fixture'] + ([str(output)] if output else [])
    with patch.dict(GLOBALS, axml=axml, Resources=Resources), \
            patch.object(GLOBALS['zipfile'], 'ZipFile', return_value=Archive(files)), \
            patch.object(sys, 'argv', argv), contextlib.redirect_stdout(out):
        INFO['main']()
    return out.getvalue()


class MetadataTests(unittest.TestCase):
    def test_controls_removed_before_line_framing(self):
        raw = 'Tiếng Việt\n遊戲\r\t\0\x1b\x7f\x85'
        self.assertEqual(metadata(raw), 'com.test\nTiếng Việt遊戲\ncom.test.Main\n')

    def test_unicode_limit_and_empty_fallback(self):
        self.assertEqual(metadata('遊' * 81).split('\n')[1], '遊' * 80)
        self.assertEqual(metadata('\0\n\r').split('\n')[1], 'com.test')
        self.assertEqual(metadata(None).split('\n')[1], 'com.test')

    def test_malformed_identity_rejected(self):
        for kw in ({'pkg': 'com.test\nother'}, {'pkg': '../other'}, {'activity': '.Main\0oops'}):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                metadata('app', **kw)

    def test_candidates_and_adaptive_skip_webp(self):
        for adaptive in (False, True):
            with self.subTest(adaptive=adaptive), tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / 'icon.png'
                metadata('app', files={'resources.arsc': b'', 'icon.xml': b'adaptive',
                         'bad.png': b'RIFFwebp', 'good.png': PNG}, output=output, adaptive=adaptive)
                self.assertEqual(output.read_bytes(), PNG)
                self.assertEqual(list(Path(tmp).iterdir()), [output])

    def test_rejected_image_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'icon.png'
            output.write_bytes(PNG)
            for bad in (b'', b'RIFFwebp', PNG[:7]):
                self.assertFalse(INFO['write_png'](Archive({'bad': bad}), 'bad', str(output)))
                self.assertEqual(output.read_bytes(), PNG)

    def test_atomic_failure_keeps_previous_icon(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'icon.png'
            output.write_bytes(b'old')
            for operation in ('fsync', 'replace'):
                with self.subTest(operation=operation), patch.object(GLOBALS['os'], operation, side_effect=OSError('fixture failure')):
                    with self.assertRaises(OSError):
                        INFO['write_png'](Archive({'good': PNG}), 'good', str(output))
                self.assertEqual(output.read_bytes(), b'old')
                self.assertEqual(list(Path(tmp).iterdir()), [output])


MOCKS = r'''
SYS="$PWD/sys"; DESKTOP_DIR="$PWD/desktop"; APK_INFO=unused; OVERLAY_ROOT="$PWD/overlay"
say() { :; }
mktemp() { echo "$PWD/extracted.apk"; }
# /bin/bash on macOS lacks mapfile. Model line framing without running Android.
mapfile() { meta=(); local line; while IFS= read -r line; do meta+=("$line"); done; }
python3() {
  printf 'com.test\n%s\ncom.test.Main\n' "$LABEL"
  case "$MODE" in
    png) printf '\211PNG\r\n\032\nfixture' >"$3" ;;
    webp) printf RIFFwebp >"$3" ;;
  esac
}
asx() { case "$1" in 'pm path '*) echo package:/base.apk ;; "cat '/base.apk'") echo fake ;; *) return 98 ;; esac; }
steam_has() { return 1; }
steam_add() { cp "$1" requested.desktop; [[ "$MODE" != fail ]]; }
'''


class DesktopTests(unittest.TestCase):
    def run_fixture(self, entrypoint, mode, label='Fixture app'):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Both unrelated desktop and binary Steam data must remain exact.
            (root / 'desktop').mkdir()
            other = root / 'desktop/other.desktop'
            other.write_bytes(b'unrelated\0data')
            library = root / 'shortcuts.vdf'
            library.write_bytes(b'\0shortcuts\0\x08\x08')
            code = 'set -euo pipefail\n' + MOCKS + function(entrypoint)
            code += 'add_title com.test' if entrypoint == 'add_title' else 'cmd_setup'
            result = subprocess.run(['bash', '-c', code], cwd=root, capture_output=True, text=True,
                                    env={**os.environ, 'HOME': tmp, 'MODE': mode, 'LABEL': label}, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            content = (root / 'requested.desktop').read_text()
            self.assertEqual(other.read_bytes(), b'unrelated\0data')
            self.assertEqual(library.read_bytes(), b'\0shortcuts\0\x08\x08')
            self.assertFalse((root / 'injected').exists())
            self.assertEqual((root / 'sys/titles').exists(), mode != 'fail')
            self.assertEqual('Icon=android-package-archive' in content, mode != 'png')
            return content

    def test_add_title_icon_and_no_false_confirmation(self):
        for mode in ('png', 'webp', 'missing', 'fail'):
            with self.subTest(mode=mode):
                content = self.run_fixture('add_title', mode)
                self.assertIn('Exec=/usr/bin/konkr-apk run com.test\n', content)

    def test_literal_backslash_quote_and_shell_text(self):
        label = '遊戲 \\n "quoted" $(touch injected)'
        content = self.run_fixture('add_title', 'png', label)
        self.assertIn('Name=' + label.replace('\\', '\\\\') + '\n', content)

    def test_setup_uses_same_icon_guard(self):
        for mode in ('png', 'webp', 'missing'):
            with self.subTest(mode=mode):
                content = self.run_fixture('cmd_setup', mode)
                self.assertIn('Name=Google Play Store\n', content)


if __name__ == '__main__':
    unittest.main()
