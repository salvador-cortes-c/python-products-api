import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


def get_products_json_path() -> Path:
    configured = os.environ.get("PRODUCTS_JSON_PATH")
    if configured:
        return Path(configured)

    repo_root = Path(__file__).resolve().parent
    return (repo_root.parent / "python-playwright-scraper" / "products.json").resolve()


def get_price_snapshots_json_path(products_path: Path) -> Path:
    configured = os.environ.get("PRICE_SNAPSHOTS_JSON_PATH")
    if configured:
        return Path(configured)

    return products_path.with_name("price_snapshots.json")


def product_key(name: str, packaging_format: str) -> str:
    return f"{(name or '').strip()}__{(packaging_format or '').strip()}".lower()


def load_json_array(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
    return out


def build_product_views() -> list[dict[str, Any]]:
    products_path = get_products_json_path()
    products_raw = load_json_array(products_path)
    snapshots_raw = load_json_array(get_price_snapshots_json_path(products_path))

    latest_by_key: dict[str, dict[str, Any]] = {}
    for snap in snapshots_raw:
        key = str(snap.get("product_key") or "")
        if not key:
            continue
        current = latest_by_key.get(key)
        # scraped_at is ISO-8601; string compare works for ordering
        if current is None or str(snap.get("scraped_at") or "") >= str(current.get("scraped_at") or ""):
            latest_by_key[key] = snap

    views: list[dict[str, Any]] = []
    for p in products_raw:
        name = str(p.get("name") or "")
        packaging_format = str(p.get("packaging_format") or "")
        key = str(p.get("product_key") or "") or product_key(name, packaging_format)
        latest = latest_by_key.get(key) or {}

        views.append(
            {
                "product_key": key,
                "name": name,
                "packaging_format": packaging_format or None,
                "image": p.get("image") or None,
                "price": latest.get("price") or None,
                "unit_price": latest.get("unit_price") or None,
                "source_url": latest.get("source_url") or None,
                "scraped_at": latest.get("scraped_at") or None,
            }
        )

    return views


def search(views: list[dict[str, Any]], query: str, limit: int) -> list[dict[str, Any]]:
    q = (query or "").strip().lower()
    if not q:
        return views[:limit]

    matches = [v for v in views if q in str(v.get("name") or "").lower()]

    def score(v: dict[str, Any]) -> tuple[int, int]:
        name = str(v.get("name") or "").lower()
        starts = 0 if name.startswith(q) else 1
        return (starts, len(name))

    matches.sort(key=score)
    return matches[:limit]


class Handler(BaseHTTPRequestHandler):
    def address_string(self) -> str:
        # Avoid reverse DNS lookups which can hang on locked-down networks.
        return self.client_address[0]

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        # Silence default request logging to prevent DNS / IO hangs.
        return

    def _send_json(self, code: int, payload: Any) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/health":
            self._send_json(200, {"status": "ok"})
            return

        if path in ("/products", "/products/search"):
            views = build_product_views()

            if path == "/products":
                limit = int((qs.get("limit") or ["50"])[0])
                limit = max(1, min(limit, 500))
                self._send_json(200, views[:limit])
                return

            query = (qs.get("q") or [""])[0]
            limit = int((qs.get("limit") or ["8"])[0])
            limit = max(1, min(limit, 50))
            self._send_json(200, search(views, query, limit))
            return

        self._send_json(404, {"detail": "Not found"})


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    server = HTTPServer((host, port), Handler)
    print(f"Serving on http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
