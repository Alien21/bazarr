# coding=utf-8

import os
from unittest import mock

import pytest

from utilities.post_processing import pp_replace
from subtitles.post_processing import postprocessing


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_DUMMY_CMD = 'cmd {{episode}} {{subtitles}} {{directory}}'


def _replace(episode, subtitles='sub.srt'):
    return pp_replace(
        _DUMMY_CMD,
        episode, subtitles,
        'English', 'en', 'eng',
        'English', 'en', 'eng',
        100, '1', 'manual', 'user', 'unknown', 1, 1,
    )


def _make_mock_process():
    proc = mock.MagicMock()
    proc.communicate.return_value = ('output', '')
    return proc


# ──────────────────────────────────────────────────────────────────────────────
# pp_replace – backslash safety in re.sub replacement strings (issue #3413)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("episode,subtitles,expected_fragment", [
    # Linux path – no backslashes
    ('/home/user/Videos/show.mkv', '/home/user/Videos/show.en.srt',
     '"/home/user/Videos/show.mkv"'),
    # Windows local path – backslash separators must not cause re.PatternError
    (r'C:\Videos\show.mkv', r'C:\Videos\show.en.srt',
     r'"C:\Videos\show.mkv"'),
    # Windows UNC path – \\ prefix and backslash-letter sequences like \y
    (r'\\Server\y\show.mkv', r'\\Server\y\show.en.srt',
     r'"\\Server\y\show.mkv"'),
    # UNC path with different share letters
    (r'\\NAS\media\show.mkv', r'\\NAS\media\show.en.srt',
     r'"\\NAS\media\show.mkv"'),
])
def test_pp_replace_does_not_raise_and_substitutes(episode, subtitles, expected_fragment):
    # Must not raise re.PatternError: bad escape
    result = _replace(episode, subtitles)
    assert expected_fragment in result


def test_pp_replace_unc_subtitle_path_preserved():
    # The leading \\ of a UNC subtitle path must survive substitution intact
    result = _replace(r'\\Server\drive\show.mkv', r'\\Server\drive\show.en.srt')
    assert r'"\\Server\drive\show.en.srt"' in result


def test_pp_replace_unc_directory_placeholder():
    result = _replace(r'\\Server\y\show.mkv')
    expected_dir = os.path.dirname(r'\\Server\y\show.mkv')
    assert f'"{expected_dir}"' in result


def test_pp_replace_linux_directory_placeholder():
    result = _replace('/srv/media/show.mkv')
    assert '"/srv/media"' in result


def test_pp_replace_windows_local_directory_placeholder():
    result = _replace(r'C:\Videos\show.mkv')
    expected_dir = os.path.dirname(r'C:\Videos\show.mkv')
    assert f'"{expected_dir}"' in result


# ──────────────────────────────────────────────────────────────────────────────
# postprocessing – Windows vs Unix subprocess invocation (issue #3413)
# ──────────────────────────────────────────────────────────────────────────────

def test_postprocessing_windows_uses_shell_true():
    command = r'python3 C:\Scripts\process.py "\\Server\y\subtitle.srt"'
    with mock.patch('os.name', 'nt'), \
         mock.patch('ctypes.windll', create=True) as mock_windll, \
         mock.patch('subprocess.Popen', return_value=_make_mock_process()) as mock_popen:
        mock_windll.kernel32.GetConsoleOutputCP.return_value = 1252
        postprocessing(command, r'\\Server\y\show.mkv')

    _, kwargs = mock_popen.call_args
    assert kwargs['shell'] is True


def test_postprocessing_windows_passes_command_as_string():
    # The full command string must reach Popen unchanged – no shlex mangling
    command = r'python3 C:\Scripts\process.py "\\Server\y\subtitle.srt"'
    with mock.patch('os.name', 'nt'), \
         mock.patch('ctypes.windll', create=True) as mock_windll, \
         mock.patch('subprocess.Popen', return_value=_make_mock_process()) as mock_popen:
        mock_windll.kernel32.GetConsoleOutputCP.return_value = 1252
        postprocessing(command, r'\\Server\y\show.mkv')

    args, _ = mock_popen.call_args
    assert isinstance(args[0], str)
    assert args[0] == command


def test_postprocessing_windows_unc_path_not_mangled():
    # \\Server\y must not be stripped to \Server\y (shlex POSIX regression)
    unc_command = r'python3 "\\Server\y\subtitle.srt"'
    with mock.patch('os.name', 'nt'), \
         mock.patch('ctypes.windll', create=True) as mock_windll, \
         mock.patch('subprocess.Popen', return_value=_make_mock_process()) as mock_popen:
        mock_windll.kernel32.GetConsoleOutputCP.return_value = 1252
        postprocessing(unc_command, r'\\Server\y\show.mkv')

    args, _ = mock_popen.call_args
    assert r'\\Server\y\subtitle.srt' in args[0]


def test_postprocessing_windows_local_path_not_mangled():
    # C:\Scripts\... must not become C:Scripts... (shlex POSIX backslash-escape regression)
    local_command = r'python3 C:\Scripts\process.py'
    with mock.patch('os.name', 'nt'), \
         mock.patch('ctypes.windll', create=True) as mock_windll, \
         mock.patch('subprocess.Popen', return_value=_make_mock_process()) as mock_popen:
        mock_windll.kernel32.GetConsoleOutputCP.return_value = 1252
        postprocessing(local_command, r'C:\Videos\show.mkv')

    args, _ = mock_popen.call_args
    assert r'C:\Scripts\process.py' in args[0]


def test_postprocessing_unix_uses_shell_false():
    command = 'python3 /usr/local/bin/process.py "/srv/media/subtitle.srt"'
    with mock.patch('os.name', 'posix'), \
         mock.patch('subprocess.Popen', return_value=_make_mock_process()) as mock_popen:
        postprocessing(command, '/srv/media/show.mkv')

    _, kwargs = mock_popen.call_args
    assert kwargs['shell'] is False


def test_postprocessing_unix_passes_args_as_list():
    command = 'python3 /usr/local/bin/process.py "/srv/media/subtitle.srt"'
    with mock.patch('os.name', 'posix'), \
         mock.patch('subprocess.Popen', return_value=_make_mock_process()) as mock_popen:
        postprocessing(command, '/srv/media/show.mkv')

    args, _ = mock_popen.call_args
    assert isinstance(args[0], list)
    assert args[0] == ['python3', '/usr/local/bin/process.py', '/srv/media/subtitle.srt']


def test_postprocessing_unix_quoted_path_with_spaces():
    # A quoted path containing spaces must be a single argv token after shlex.split
    command = 'python3 /usr/local/bin/process.py "/srv/my media/subtitle.srt"'
    with mock.patch('os.name', 'posix'), \
         mock.patch('subprocess.Popen', return_value=_make_mock_process()) as mock_popen:
        postprocessing(command, '/srv/my media/show.mkv')

    args, _ = mock_popen.call_args
    assert args[0] == ['python3', '/usr/local/bin/process.py', '/srv/my media/subtitle.srt']
