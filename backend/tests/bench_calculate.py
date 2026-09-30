"""/api/calculate latency, in process (FR-C1): `python -m tests.bench_calculate [N]`.

Cycles through standard, custom-size, add-on and outdoor requests and prints p50/p95/max
in milliseconds for N requests (default 200) after a warm-up. Not collected by pytest.
"""
import dataclasses
import logging
import statistics
import sys
import time

from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import get_settings

REQUESTS = [
    {"item_id": "rigid_boxes/3x3x2-in/top-bottom", "quantity": 450},
    {"item_id": "rigid_boxes/3x3x2-in/top-bottom", "quantity": 60},
    {"product_id": "rigid_boxes", "options": {"option_1": "Top-Bottom"}, "custom_dimensions": {"length": 3.5, "width": 3.5, "height": 2, "unit": "in"}, "quantity": 300},
    {"product_id": "carry_bags_large", "options": {}, "custom_dimensions": {"height": 12, "length": 14, "side": 4, "unit": "in"}, "quantity": 700},
    {"item_id": "vc_standard/300-gsm/none/single-side", "quantity": 1200, "addons": ["round_edges"]},
    {"item_id": "sticker_sheets/paper", "quantity": 250, "addons": ["sample"]},
    {"item_id": "outdoor_branding/flex-printing-block-out", "quantity": 240, "outdoor": {"width": 10, "height": 12, "pieces": 2}},
    {"item_id": "butter_paper/29x9-in", "quantity": 1500, "addons": ["multicolour", "custom_cut"]},
]


def main(n: int) -> None:
    logging.disable(logging.CRITICAL)
    settings = dataclasses.replace(get_settings(), rate_limit_per_minute=0, site_password=None, require_password=False)
    client = TestClient(create_app(settings))
    for body in REQUESTS * 3:  # warm-up
        client.post("/api/calculate", json=body)
    times = []
    for i in range(n):
        body = REQUESTS[i % len(REQUESTS)]
        started = time.perf_counter()
        r = client.post("/api/calculate", json=body)
        times.append((time.perf_counter() - started) * 1000)
        assert r.status_code == 200, r.text
    times.sort()
    p95 = times[max(0, int(round(0.95 * n)) - 1)]
    print(f"n={n} p50={statistics.median(times):.2f} ms p95={p95:.2f} ms max={times[-1]:.2f} ms")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)
