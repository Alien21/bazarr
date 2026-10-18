"""Recently-added metadata updates remain scoped and preserve Jellyfin metadata."""
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
import pytest
from bazarr.jellyfin.client import JellyfinClient
from bazarr.jellyfin import operations
from fake_jellyfin import FakeJellyfinClient, make_episode, make_movie, make_series


def item_metadata(item_id="m1", item_type="Movie"):
    return {
        "Id": item_id,
        "Name": "Original name",
        "Type": item_type,
        "DateCreated": "2020-01-02T03:04:05Z",
        "OriginalTitle": "Original title",
        "Overview": "Existing overview",
        "ForcedSortName": "Sort this first",
        "SortName": "computed sort name",
        "PreferredMetadataLanguage": "cs",
        "PreferredMetadataCountryCode": "CZ",
        "LockData": True,
        "LockedFields": ["Name", "Overview"],
        "ProviderIds": {"Imdb": "tt123", "Tmdb": "999"},
        "Tags": ["Keep this tag"],
        "Genres": ["Drama"],
        "People": [{"Name": "Actor name", "Type": "Actor", "Role": "Existing role"}],
        "Studios": [{"Name": "Existing studio"}],
        "ProductionLocations": ["Czech Republic"],
        "CustomRating": "Existing rating",
        "Taglines": ["Existing tagline"],
        "PremiereDate": "2019-01-01T00:00:00Z",
        "ProductionYear": 2019,
        "OfficialRating": "PG",
        "CommunityRating": 8.5,
        "CriticRating": 80,
        "Path": "/media/item.mkv",
    }


@pytest.fixture
def fake(monkeypatch):
    settings = SimpleNamespace(jellyfin=SimpleNamespace(
        movie_library_ids=["lib-movies"], series_library_ids=["lib-shows"],
    ))
    client = FakeJellyfinClient()
    monkeypatch.setattr(operations, "settings", settings)
    monkeypatch.setattr(operations, "get_jellyfin_client", lambda: client)
    return client


@patch.object(JellyfinClient, "get")
def test_get_item_requests_complete_metadata_without_user(mock_get):
    metadata = item_metadata()
    mock_get.return_value.json.return_value = {"Items": [metadata]}
    client = JellyfinClient("http://unused.invalid", "test-key")
    assert client.get_item("m1") == metadata
    mock_get.assert_called_once()
    path, = mock_get.call_args.args
    params = mock_get.call_args.kwargs["params"]
    assert path == "/Items"
    assert params["ids"] == "m1"
    assert params["enableUserData"] == "false"
    assert params["enableImages"] == "false"
    assert "userId" not in params
    assert set(params["fields"].split(",")) == {
        "DateCreated", "Settings", "Tags", "Genres", "Overview", "OriginalTitle",
        "ProviderIds", "People", "Studios", "ProductionLocations", "CustomRating",
        "Taglines", "SortName", "SpecialEpisodeNumbers", "Path",
    }


@pytest.mark.parametrize("missing", ["Name", "Type", "LockData", "LockedFields", "Tags", "Genres"])
@patch.object(JellyfinClient, "get_items")
def test_get_item_rejects_partial_metadata(mock_get_items, missing):
    metadata = item_metadata()
    metadata.pop(missing)
    mock_get_items.return_value = [metadata]
    client = JellyfinClient("http://unused.invalid", "test-key")
    with pytest.raises(ValueError):
        client.get_item("m1")


@pytest.mark.parametrize("items", [[], [item_metadata("wrong")], [item_metadata(), item_metadata()]])
@patch.object(JellyfinClient, "get_items")
def test_get_item_rejects_ambiguous_or_mismatched_items(mock_get_items, items):
    mock_get_items.return_value = items
    client = JellyfinClient("http://unused.invalid", "test-key")
    with pytest.raises(ValueError):
        client.get_item("m1")


@patch.object(JellyfinClient, "post")
def test_update_item_posts_complete_metadata_without_adding_defaults(mock_post):
    metadata = item_metadata()
    client = JellyfinClient("http://unused.invalid", "test-key")
    client.update_item("m1", metadata)
    mock_post.assert_called_once_with("/Items/m1", json=metadata)
    assert "EndDate" not in metadata


@patch.object(JellyfinClient, "post")
def test_update_item_rejects_mismatched_id(mock_post):
    client = JellyfinClient("http://unused.invalid", "test-key")
    with pytest.raises(ValueError):
        client.update_item("other", item_metadata())
    mock_post.assert_not_called()


@pytest.mark.parametrize("is_movie", [True, False])
def test_added_date_preserves_all_other_metadata(fake, is_movie):
    item_id = "m1" if is_movie else "ep2"
    metadata = item_metadata(item_id, "Movie" if is_movie else "Episode")
    if is_movie:
        fake.items = [make_movie(id=item_id, imdb_id="tt123")]
        operation = operations.jellyfin_set_movie_added_date_now
    else:
        fake.items = [make_series(id="s1", imdb_id="tt123")]
        fake.episodes = {"s1": {1: [make_episode(id="ep1", index=1), make_episode(id=item_id, index=2)]}}
        metadata.update({"IndexNumber": 2, "ParentIndexNumber": 1,
                         "AirsBeforeEpisodeNumber": 3, "AirsBeforeSeasonNumber": 2,
                         "AirsAfterSeasonNumber": 1, "SeriesName": "Existing series"})
        operation = operations.jellyfin_set_episode_added_date_now
    fake.item_details[item_id] = metadata
    original = deepcopy(metadata)
    before = datetime.now(timezone.utc)
    operation(SimpleNamespace(imdbId="tt123", season=1, episode=2))
    after = datetime.now(timezone.utc)
    assert len(fake.update_item_calls) == 1
    updated_id, updated = fake.update_item_calls[0]
    assert updated_id == item_id
    assert before <= datetime.fromisoformat(updated["DateCreated"]) <= after
    assert {k: v for k, v in updated.items() if k != "DateCreated"} == {
        k: v for k, v in original.items() if k != "DateCreated"
    }
    assert metadata == original
    assert fake.get_item_calls == [item_id]
    assert fake.refresh_item_calls == []
    assert fake.report_media_updated_calls == []


def test_added_movie_matches_tmdb_without_imdb(fake):
    fake.items = [make_movie(id="m1", imdb_id=None, tmdb_id="999")]
    fake.item_details["m1"] = item_metadata()
    operations.jellyfin_set_movie_added_date_now(SimpleNamespace(imdbId=None, tmdbId=999))
    assert [item_id for item_id, _ in fake.update_item_calls] == ["m1"]


def test_added_episode_matches_tvdb_and_exact_episode(fake):
    fake.items = [make_series(id="s1", imdb_id=None, tvdb_id=789)]
    fake.episodes = {"s1": {0: [make_episode(id="special", index=2), make_episode(id="other", index=3)]}}
    fake.item_details["special"] = item_metadata("special", "Episode")
    operations.jellyfin_set_episode_added_date_now(SimpleNamespace(tvdbId=789, season=0, episode=2))
    assert [item_id for item_id, _ in fake.update_item_calls] == ["special"]


def test_added_date_only_searches_selected_libraries(fake):
    fake.library_items = {"lib-movies": [], "unselected": [make_movie(imdb_id="tt123")]}
    operations.jellyfin_set_movie_added_date_now(SimpleNamespace(imdbId="tt123"))
    assert [params["parentId"] for params in fake.get_items_calls] == ["lib-movies"]
    assert fake.get_item_calls == []
    assert fake.update_item_calls == []
    assert fake.refresh_item_calls == []


@pytest.mark.parametrize("scenario", ["no-libraries", "no-ids", "no-match", "no-episode", "no-number"])
def test_added_date_skips_unresolved_items_without_library_fallback(fake, scenario):
    metadata = SimpleNamespace(imdbId="tt123", season=1, episode=2)
    operation = operations.jellyfin_set_movie_added_date_now
    if scenario == "no-libraries":
        operations.settings.jellyfin.movie_library_ids = []
    elif scenario == "no-ids":
        metadata.imdbId = None
    elif scenario in ("no-episode", "no-number"):
        operation = operations.jellyfin_set_episode_added_date_now
        fake.items = [make_series(imdb_id="tt123")]
        if scenario == "no-number":
            metadata.episode = None
    operation(metadata)
    assert fake.update_item_calls == []
    assert fake.get_item_calls == []
    assert fake.refresh_item_calls == []
    assert fake.report_media_updated_calls == []


@pytest.mark.parametrize("failing_method", ["get_item", "update_item"])
def test_added_date_failure_is_logged_and_does_not_abort_subtitle_processing(fake, monkeypatch, caplog, failing_method):
    fake.items = [make_movie(id="m1", imdb_id="tt123")]
    fake.item_details["m1"] = item_metadata()
    monkeypatch.setattr(fake, failing_method, MagicMock(side_effect=RuntimeError("offline failure")))
    operations.jellyfin_set_movie_added_date_now(SimpleNamespace(imdbId="tt123"))
    assert "Failed to update Jellyfin added date" in caplog.text
    assert fake.refresh_item_calls == []
