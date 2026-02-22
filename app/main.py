import json
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


def get_products_json_path() -> Path:
    configured = os.environ.get("PRODUCTS_JSON_PATH")
    if configured:
        return Path(configured)

    # Default assumes the scraper sits next to this repo:
    #   /Users/.../python-products-api
    #   /Users/.../python-playwright-scraper
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root.parent / "python-playwright-scraper" / "products.json").resolve()


def get_price_snapshots_json_path(products_path: Path) -> Path:
    configured = os.environ.get("PRICE_SNAPSHOTS_JSON_PATH")
    if configured:
        return Path(configured)

    return products_path.with_name("price_snapshots.json")


class Product(BaseModel):
    name: str
    packaging_format: Optional[str] = None
    image: Optional[str] = None
    product_key: Optional[str] = None


app = FastAPI(title="Products API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def load_products() -> list[Product]:
    products_path = get_products_json_path()

    if not products_path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"Products file not found at {products_path}. Set PRODUCTS_JSON_PATH.",
        )

    try:
        raw = json.loads(products_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Products file is not valid JSON: {exc}",
        ) from exc

    if not isinstance(raw, list):
        raise HTTPException(status_code=503, detail="Products file must be a JSON array")

    products: list[Product] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            products.append(Product(**item))
        except Exception:
            # Skip malformed entries
            continue

    return products


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/products", response_model=list[Product])
def list_products(limit: int = Query(default=50, ge=1, le=500)) -> list[Product]:
    return load_products()[:limit]


@app.get("/products/search", response_model=list[Product])
def search_products(
    q: str = Query(default="", min_length=0),
    limit: int = Query(default=8, ge=1, le=50),
) -> list[Product]:
    query = q.strip().lower()
    products = load_products()

    if not query:
        return products[:limit]

    def score(product: Product) -> tuple[int, int]:
        name = product.name.lower()
        starts = 0 if name.startswith(query) else 1
        return (starts, len(name))

    matches = [p for p in products if query in p.name.lower()]
    matches.sort(key=score)
    return matches[:limit]
