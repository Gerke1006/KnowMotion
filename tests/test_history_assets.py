"""Validate shipped asset integrity and geographic/portrait provenance, without network calls."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "renderers" / "remotion" / "project" / "public"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_land_is_physical_public_domain_data_with_verified_checksum():
    source = read_json(PUBLIC / "data" / "SOURCES.json")["sources"][0]
    path = PUBLIC / "data" / source["asset"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"]
    data = read_json(path)
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == source["feature_count"]
    assert all(f["geometry"]["type"] in {"Polygon", "MultiPolygon"} for f in data["features"])
    assert all(f["properties"]["featurecla"] == "Land" for f in data["features"])
    assert source["license"] == "Public domain"
    assert source["repository_commit"] in source["source_url"]


def test_geographic_anchors_have_coordinate_provenance_and_correct_region():
    records = read_json(ROOT / "assets" / "history" / "locations.json")["records"]
    assert len({record["id"] for record in records}) == len(records)
    for record in records:
        assert 20 < record["lon"] < 120 and 25 < record["lat"] < 50
        assert record["accuracy"] == "approximate-modern-place-anchor"
        assert record["source"]["property"] == "P625"
        assert record["source"]["statement_id"] and record["source"]["revision_id"]
        assert record["source"]["license"] == "CC0-1.0"
    alexandria = next(r for r in records if r["id"] == "alexandria")
    assert 29 < alexandria["lon"] < 31 and 30 < alexandria["lat"] < 32


def test_mural_asset_preserves_license_and_later_depiction_notice():
    registry = read_json(ROOT / "assets" / "history" / "portraits.json")
    for entry in registry["assets"]:
        path = (PUBLIC / entry["path"]).resolve()
        assert path.is_relative_to(PUBLIC.resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        assert "Public domain" in entry["license"]
        assert "后世描绘" in entry["caption"]
        assert "汉武帝" in entry["interpretation_note"]


def test_history_source_registry_contains_official_urls_not_bundled_narration():
    sources = read_json(ROOT / "assets" / "history" / "sources.json")["sources"]
    assert len({source["id"] for source in sources}) == len(sources)
    assert sum(source["kind"] == "web" for source in sources) >= 2
    for source in sources:
        parsed = urlsplit(source["url"])
        assert parsed.scheme == "https" and parsed.hostname.endswith("unesco.org")
        assert source["topics"] and source["title"]
        assert "narration" not in source and "excerpt" not in source
