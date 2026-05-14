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
                {"id": "d1", "name": "APPDOM1", "type": "app", "node_id": "n1"},
                {"id": "d2", "name": "PRCSDOM1", "type": "prcs", "node_id": "n1"},
            ]
        }
        update_cache_from_ingest(ingest, cache_file)
        assert get_cached_domain_id("APPDOM1", cache_path=cache_file) == "d1"
        assert get_cached_domain_id("PRCSDOM1", cache_path=cache_file) == "d2"

    def test_update_merges_existing(self, tmp_path):
        cache_file = tmp_path / "domains.json"
        save_cache({"OLD": {"id": "old1"}}, cache_file)

        ingest = {"domains": [{"id": "new1", "name": "NEW", "type": "app"}]}
        update_cache_from_ingest(ingest, cache_file)
        assert get_cached_domain_id("OLD", cache_path=cache_file) == "old1"
        assert get_cached_domain_id("NEW", cache_path=cache_file) == "new1"

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
        assert get_cached_domain_id("APPDOM1", cache_path=cache_file) == "d1"

    def test_not_found(self, tmp_path):
        cache_file = tmp_path / "domains.json"
        assert get_cached_domain_id("NOPE", cache_path=cache_file) is None

    def test_not_found_no_file(self, tmp_path):
        cache_file = tmp_path / "nonexist.json"
        assert get_cached_domain_id("NOPE", cache_path=cache_file) is None

    def test_composite_key_lookup(self, tmp_path):
        cache_file = tmp_path / "domains.json"
        ingest = {
            "domains": [
                {"id": "a1", "name": "IHDEV", "type": "app", "node_id": "n1"},
                {"id": "p1", "name": "IHDEV", "type": "prcs", "node_id": "n1"},
                {"id": "w1", "name": "IHDEV", "type": "web", "node_id": "n1"},
            ]
        }
        update_cache_from_ingest(ingest, cache_file)
        assert get_cached_domain_id("IHDEV", domain_type="app", cache_path=cache_file) == "a1"
        assert get_cached_domain_id("IHDEV", domain_type="prcs", cache_path=cache_file) == "p1"
        assert get_cached_domain_id("IHDEV", domain_type="web", cache_path=cache_file) == "w1"

    def test_ambiguous_without_type(self, tmp_path):
        cache_file = tmp_path / "domains.json"
        ingest = {
            "domains": [
                {"id": "a1", "name": "IHDEV", "type": "app", "node_id": "n1"},
                {"id": "p1", "name": "IHDEV", "type": "prcs", "node_id": "n1"},
            ]
        }
        update_cache_from_ingest(ingest, cache_file)
        # No type given and multiple typed entries → ambiguous
        assert get_cached_domain_id("IHDEV", cache_path=cache_file) is None

    def test_uppercase_server_type_lookup_with_lowercase(self, tmp_path):
        """Server returns canonical uppercase (APP/PRCS/WEB); local lookups use lowercase."""
        cache_file = tmp_path / "domains.json"
        ingest = {
            "domains": [
                {"id": "a1", "name": "ihdev", "type": "APP", "node_id": "n1"},
                {"id": "p1", "name": "ihdev", "type": "PRCS", "node_id": "n1"},
                {"id": "w1", "name": "ihdev", "type": "WEB", "node_id": "n1"},
            ]
        }
        update_cache_from_ingest(ingest, cache_file)
        assert get_cached_domain_id("ihdev", domain_type="app", cache_path=cache_file) == "a1"
        assert get_cached_domain_id("ihdev", domain_type="prcs", cache_path=cache_file) == "p1"
        assert get_cached_domain_id("ihdev", domain_type="web", cache_path=cache_file) == "w1"

    def test_response_with_domain_type_field_still_works(self, tmp_path):
        """Defensive: server response using `domain_type` instead of `type` is accepted."""
        cache_file = tmp_path / "domains.json"
        ingest = {
            "domains": [
                {"id": "a1", "name": "IHDEV", "domain_type": "app", "node_id": "n1"},
                {"id": "p1", "name": "IHDEV", "domain_type": "prcs", "node_id": "n1"},
            ]
        }
        update_cache_from_ingest(ingest, cache_file)
        assert get_cached_domain_id("IHDEV", domain_type="app", cache_path=cache_file) == "a1"
        assert get_cached_domain_id("IHDEV", domain_type="prcs", cache_path=cache_file) == "p1"

    def test_legacy_flat_entry_still_works(self, tmp_path):
        cache_file = tmp_path / "domains.json"
        save_cache({"OLDDOM": {"id": "old1", "type": "app", "node_id": "n1"}}, cache_file)
        assert get_cached_domain_id("OLDDOM", cache_path=cache_file) == "old1"
        assert get_cached_domain_id("OLDDOM", domain_type="app", cache_path=cache_file) == "old1"
        assert get_cached_domain_id("OLDDOM", domain_type="prcs", cache_path=cache_file) is None
