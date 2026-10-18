"""Execute real subtitle integration blocks without downloading or writing subtitles.
AST isolation keeps these hook tests independent of database, providers and media files.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import pytest
from bazarr.jellyfin import operations


@pytest.fixture(params=[
    ("processing.py", "process_subtitle"),
    ("upload.py", "manual_upload_subtitle"),
])
def integration_hook(request):
    filename, function_name = request.param
    source = Path(__file__).parents[2] / "bazarr" / "subtitles" / filename
    module = ast.parse(source.read_text(encoding="utf-8"))
    function = next(node for node in module.body
                    if isinstance(node, ast.FunctionDef) and node.name == function_name)
    def run(server, media_type, enabled=True, added=True, refresh=True, date_hook=None):
        metadata_name = "episode_metadata" if media_type == "series" else "movie_metadata"
        blocks = [node for node in ast.walk(function)
                  if isinstance(node, ast.If)
                  and any(isinstance(child, ast.Attribute) and child.attr == f"use_{server}"
                          for child in ast.walk(node.test))
                  and any(isinstance(child, ast.Name) and child.id == metadata_name
                          for child in ast.walk(node))]
        assert len(blocks) == 1
        calls = []
        flags = SimpleNamespace(set_movie_added=added, set_episode_added=added,
                                update_movie_library=refresh, update_series_library=refresh)
        namespace = {
            "settings": SimpleNamespace(
                general=SimpleNamespace(use_plex=enabled, use_jellyfin=enabled),
                plex=flags, jellyfin=flags),
            metadata_name: SimpleNamespace(imdbId="tt123", tmdbId=999, tvdbId=789, season=1, episode=2),
        }
        for name in (f"{server}_set_movie_added_date_now", f"{server}_set_episode_added_date_now",
                     f"{server}_refresh_item"):
            namespace[name] = lambda *args, hook=name, **kwargs: calls.append(hook)
        if date_hook is not None:
            item_type = "episode" if media_type == "series" else "movie"
            namespace[f"{server}_set_{item_type}_added_date_now"] = date_hook
        block = ast.Module(body=blocks, type_ignores=[])
        exec(compile(block, str(source), "exec"), namespace)
        return calls
    return run


@pytest.mark.parametrize("server", ["plex", "jellyfin"])
@pytest.mark.parametrize("media_type", ["series", "movie"])
@pytest.mark.parametrize("enabled,added,refresh", [
    (True, True, True),
    (True, True, False),
    (True, False, True),
    (False, True, True),
])
def test_subtitle_hooks_update_added_date_before_optional_refresh(integration_hook, server, media_type,
                                                                 enabled, added, refresh):
    calls = integration_hook(server, media_type, enabled=enabled, added=added, refresh=refresh)
    item_type = "episode" if media_type == "series" else "movie"
    expected = []
    if enabled and added:
        expected.append(f"{server}_set_{item_type}_added_date_now")
    if enabled and refresh:
        expected.append(f"{server}_refresh_item")
    assert calls == expected


@pytest.mark.parametrize("media_type", ["series", "movie"])
def test_jellyfin_metadata_failure_still_allows_refresh(integration_hook, media_type, monkeypatch, caplog):
    monkeypatch.setattr(operations, "settings", SimpleNamespace(jellyfin=SimpleNamespace(
        movie_library_ids=["lib-movies"], series_library_ids=["lib-shows"])))
    def fail_connection():
        raise RuntimeError("offline failure")
    monkeypatch.setattr(operations, "get_jellyfin_client", fail_connection)
    date_hook = (operations.jellyfin_set_episode_added_date_now if media_type == "series"
                 else operations.jellyfin_set_movie_added_date_now)
    calls = integration_hook("jellyfin", media_type, date_hook=date_hook)
    assert calls == ["jellyfin_refresh_item"]
    assert "Failed to update Jellyfin added date" in caplog.text
