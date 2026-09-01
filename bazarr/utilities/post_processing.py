# coding=utf-8

import os
import re
import sys
import logging

from app.config import settings


# Wraps the input string within double quotes
def _double_quotes(in_str):
    return f"\"{in_str}\""


def pp_replace(pp_command, episode, subtitles, language, language_code2, language_code3, episode_language,
               episode_language_code2, episode_language_code3, score, subtitle_id, provider, uploader,
               release_info, series_id, episode_id):
    # Use lambdas as replacements so re.sub never interprets backslashes in the
    # replacement string as escape sequences (fixes UNC paths on Windows, e.g. \\Server\y\...)
    pp_command = re.sub(r'[\'"]?{{directory}}[\'"]?', lambda m: _double_quotes(os.path.dirname(episode)), pp_command)
    pp_command = re.sub(r'[\'"]?{{episode}}[\'"]?', lambda m: _double_quotes(episode), pp_command)
    pp_command = re.sub(r'[\'"]?{{episode_name}}[\'"]?',
                        lambda m: _double_quotes(os.path.splitext(os.path.basename(episode))[0]), pp_command)
    pp_command = re.sub(r'[\'"]?{{subtitles}}[\'"]?', lambda m: _double_quotes(str(subtitles)), pp_command)
    pp_command = re.sub(r'[\'"]?{{subtitles_language}}[\'"]?', lambda m: _double_quotes(str(language)), pp_command)
    pp_command = re.sub(r'[\'"]?{{subtitles_language_code2}}[\'"]?', lambda m: _double_quotes(str(language_code2)), pp_command)
    pp_command = re.sub(r'[\'"]?{{subtitles_language_code3}}[\'"]?', lambda m: _double_quotes(str(language_code3)), pp_command)
    pp_command = re.sub(r'[\'"]?{{subtitles_language_code2_dot}}[\'"]?',
                        lambda m: _double_quotes(str(language_code2).replace(':', '.')), pp_command)
    pp_command = re.sub(r'[\'"]?{{subtitles_language_code3_dot}}[\'"]?',
                        lambda m: _double_quotes(str(language_code3).replace(':', '.')), pp_command)
    pp_command = re.sub(r'[\'"]?{{episode_language}}[\'"]?', lambda m: _double_quotes(str(episode_language)), pp_command)
    pp_command = re.sub(r'[\'"]?{{episode_language_code2}}[\'"]?', lambda m: _double_quotes(str(episode_language_code2)), pp_command)
    pp_command = re.sub(r'[\'"]?{{episode_language_code3}}[\'"]?', lambda m: _double_quotes(str(episode_language_code3)), pp_command)
    pp_command = re.sub(r'[\'"]?{{score}}[\'"]?', lambda m: _double_quotes(str(score)), pp_command)
    pp_command = re.sub(r'[\'"]?{{subtitle_id}}[\'"]?', lambda m: _double_quotes(str(subtitle_id)), pp_command)
    pp_command = re.sub(r'[\'"]?{{provider}}[\'"]?', lambda m: _double_quotes(str(provider)), pp_command)
    pp_command = re.sub(r'[\'"]?{{uploader}}[\'"]?', lambda m: _double_quotes(str(uploader)), pp_command)
    pp_command = re.sub(r'[\'"]?{{release_info}}[\'"]?', lambda m: _double_quotes(str(release_info)), pp_command)
    pp_command = re.sub(r'[\'"]?{{series_id}}[\'"]?', lambda m: _double_quotes(str(series_id)), pp_command)
    pp_command = re.sub(r'[\'"]?{{episode_id}}[\'"]?', lambda m: _double_quotes(str(episode_id)), pp_command)
    return pp_command


def set_chmod(subtitles_path):
    # apply chmod if required
    chmod = int(settings.general.chmod, 8) if not sys.platform.startswith(
        'win') and settings.general.chmod_enabled else None
    if chmod:
        logging.debug(f"BAZARR setting permission to {chmod} on {subtitles_path} after custom post-processing.")
        os.chmod(subtitles_path, chmod)
