"""A6 / FR-C2: /api/calculate answers exactly as it did before the tier-slider release.

fixtures/calculate_snapshot.json was recorded from the baseline commit (M0 of
docs/BRD-tier-slider-back-nav.pdf) with `python -m tests.test_calculate_snapshot`. It
holds each request with a SHA-256 of its response (status code + body, keys sorted).
The only field allowed to differ is the added `data.tier_schedule` block, which is
removed before hashing. Don't re-record the file to make this test pass.
"""
import dataclasses
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import get_settings

SNAPSHOT = Path(__file__).parent / "fixtures" / "calculate_snapshot.json"

CUSTOM_DIMS = {
    "box": [{"length": 3.5, "width": 3.5, "height": 2}, {"length": 1, "width": 1, "height": 1}, {"length": 7, "width": 5, "height": 3}, {"length": 60, "width": 60, "height": 60}],
    "bag": [{"height": 8, "length": 10, "side": 3}, {"height": 2, "length": 2, "side": 1}, {"height": 60, "length": 60, "side": 60}],
    "flat": [{"length": 7, "width": 9}, {"length": 1, "width": 1}, {"length": 20, "width": 20}, {"length": 60, "width": 60}],
}


def _quantities(breakpoints: list[int], sqft: bool, max_qty: int | None) -> list:
    qs = set()
    if breakpoints[0] > 1:
        qs.add(breakpoints[0] - 1)
    for a, b in zip(breakpoints, breakpoints[1:] + [breakpoints[-1] * 3]):
        qs.update({a, (a + b) // 2, b - 1})
    if max_qty:
        qs.update({max_qty, max_qty + 1})
    out = sorted(q for q in qs if q >= 1)
    if sqft:
        out += [q + 0.25 for q in out[:3]]
    return out


def snapshot_requests(cat) -> list[dict]:
    reqs: list[dict] = []
    for product in cat.products.values():
        sqft = product.custom_dims == "area_sqft"
        for item in product.items:
            for q in _quantities(item.breakpoints, sqft, product.max_qty):
                body = {"item_id": item.id, "quantity": q}
                if sqft:
                    body["outdoor"] = {"width": 2, "height": 2, "pieces": 1}
                reqs.append(body)
        first = product.items[0]
        mid = first.breakpoints[min(1, len(first.breakpoints) - 1)] + 3
        addon_items = [i for i in product.items if i.sample_charge is not None] or [first]
        for a in product.addons:
            reqs.append({"item_id": addon_items[0].id, "quantity": mid, "addons": [a.id]})
        if product.addons:
            reqs.append({"item_id": addon_items[0].id, "quantity": mid, "addons": [a.id for a in product.addons]})
            reqs.append({"item_id": addon_items[0].id, "quantity": first.breakpoints[0] - 1 or 1, "addons": [a.id for a in product.addons]})
        reqs.append({"item_id": first.id, "quantity": mid, "billing_type": "invoice"})
        if product.supports_custom:
            for key in product.anchor_match or [None]:
                values = sorted({i.option(key) for i in product.items if i.option(key)}) if key else [None]
                for value in values:
                    for dims in CUSTOM_DIMS[product.custom_dims]:
                        for q in (first.breakpoints[0] - 1 or 1, mid, first.breakpoints[-1] + 7):
                            reqs.append(
                                {
                                    "product_id": product.id,
                                    "options": {key: value} if key else {},
                                    "custom_dimensions": {**dims, "unit": "in"},
                                    "quantity": q,
                                }
                            )
            dims = CUSTOM_DIMS[product.custom_dims][0]
            reqs.append({"product_id": product.id, "options": {}, "custom_dimensions": {**{k: v * 2.54 for k, v in dims.items()}, "unit": "cm"}, "quantity": mid})
    # Errors keep their codes and messages too.
    reqs += [
        {"item_id": "nope/nothing", "quantity": 10},
        {"item_id": "rigid_boxes/3x3x2-in/top-bottom", "quantity": 10.5},
        {"item_id": "rigid_boxes/3x3x2-in/top-bottom", "quantity": 100, "addons": ["round_edges"]},
        {"product_id": "rigid_boxes", "options": {"option_1": "Nope"}, "custom_dimensions": {"length": 3, "width": 3, "height": 3}, "quantity": 100},
        {"product_id": "vc_standard", "options": {}, "custom_dimensions": {"length": 3, "width": 3}, "quantity": 100},
        {"item_id": "rigid_boxes/3x3x2-in/top-bottom", "custom_dimensions": {"length": 3, "width": 3, "height": 3}, "quantity": 100},
    ]
    return reqs


def digest(response) -> str:
    body = response.json()
    if isinstance(body.get("data"), dict):
        body["data"].pop("tier_schedule", None)
    canonical = json.dumps({"status": response.status_code, "body": body}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _client():
    settings = dataclasses.replace(get_settings(), rate_limit_per_minute=0, site_password=None, require_password=False)
    return TestClient(create_app(settings))


@pytest.fixture(scope="module")
def snapshot():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_every_recorded_request_answers_the_same(snapshot):
    client = _client()
    changed = []
    for entry in snapshot["entries"]:
        r = client.post("/api/calculate", json=entry["request"])
        if digest(r) != entry["sha256"]:
            changed.append(entry["request"])
    assert not changed, f"{len(changed)} responses changed, first: {changed[:3]}"


def test_snapshot_covers_every_item(snapshot):
    client = _client()
    ids = {e["request"].get("item_id") for e in snapshot["entries"]}
    assert set(client.app.state.store.catalogue.items) <= ids
    assert len(snapshot["entries"]) > 1000


if __name__ == "__main__":
    client = _client()
    entries = [
        {"request": body, "sha256": digest(client.post("/api/calculate", json=body))}
        for body in snapshot_requests(client.app.state.store.catalogue)
    ]
    SNAPSHOT.write_text(json.dumps({"entries": entries}, indent=0) + "\n", encoding="utf-8")
    print(f"wrote {len(entries)} entries to {SNAPSHOT}")
