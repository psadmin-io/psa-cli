"""Tests for domain UUID cache."""

import json

import pytest

from psa.core.domain_cache import (
    get_cached_domain_id,
    load_cache,
    save_cache,
    update_cache_from_ingest,
)


class TestLoadSaveCache:
    def test_load_empty(self, tmp_path):
        cache_file = tmp_path / "domains.json"
        result = load_cache(cache_file)
        assert result == {}

    def test_save_and_load(self, tmp_path):
        cache_file = tmp_path / "domains.json"
        data = {"APPDOM1": {"id": "d1", "node_id": "n1", "type": "app"}}
        save_cache(data, cache_file)
        result = load_cache(cache_file)
        assert result == data

    def test_load_corrupt_json(self, tmp_path):
        cache_file = tmp_path / "domains.json"
        cache_file.write_text("not json")
        result = load_cache(cache_file)
        assert result == {}

    def test_save_creates_parent_dirs(self, tmp_path):
        cache_file = tmp_path / "sub" / "dir" / "domains.json"
        save_cache({"A": {"id": "1"}}, cache_file)
        assert cache_file.exists()


class TestUpdateCacheFromIngest:
    def test_update_with_domains(self, tmp_path):
        cache_file = tmp_path / "domains.json"
        ingest = {
            "domains": [
                {"id": "d1", "name": "APPDOM1", "domain_type": "app", "node_id": "n1"},
                {"id": "d2", "name": "PRCSDOM1", "domain_type": "prcs", "node_id": "n1"},
            ]
        }
        result = update_cache_from_ingest(ingest, cache_file)
        assert result["APPDOM1"]["id"] == "d1"
        assert result["PRCSDOM1"]["id"] == "d2"

        # Verify persisted
        loaded = load_cache(cache_file)
        assert loaded == result

    def test_update_merges_existing(self, tmp_path):
        cache_file = tmp_path / "domains.json"
        save_cache({"OLD": {"id": "old1"}}, cache_file)

        ingest = {"domains": [{"id": "new1", "name": "NEW", "domain_type": "app"}]}
        result = update_cache_from_ingest(ingest, cache_file)
        assert "OLD" in result
        assert "NEW" in result

    def test_update_no_domains_key(self, tmp_path):
        cache_file = tmp_path / "domains.json"
        result = update_cache_from_ingest({}, cache_file)
        assert result == {}

    def test_skips_entries_without_name_or_id(self, tmp_path):
        cache_file = tmp_path / "domains.json"
        ingest = {"domains": [{"name": "A"}, {"id": "b"}, {}]}
        result = update_cache_from_ingest(ingest, cache_file)
        assert result == {}


class TestGetCachedDomainId:
    def test_found(self, tmp_path):
        cache_file = tmp_path / "domains.json"
        save_cache({"APPDOM1": {"id": "d1"}}, cache_file)
        assert get_cached_domain_id("APPDOM1", cache_file) == "d1"

    def test_not_found(self, tmp_path):
        cache_file = tmp_path / "domains.json"
        assert get_cached_domain_id("NOPE", cache_file) is None

    def test_not_found_no_file(self, tmp_path):
        cache_file = tmp_path / "nonexist.json"
        assert get_cached_domain_id("NOPE", cache_file) is None
