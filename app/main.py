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


class ProductPriceSnapshot(BaseModel):
    product_key: str
    supermarket_name: Optional[str] = None
    price: str
    unit_price: Optional[str] = None
    source_url: Optional[str] = None
    scraped_at: str


class ProductView(BaseModel):
    product_key: str
    name: str
    packaging_format: Optional[str] = None
    image: Optional[str] = None
    price: Optional[str] = None
    unit_price: Optional[str] = None
    source_url: Optional[str] = None
    scraped_at: Optional[str] = None
    supermarket_name: Optional[str] = None


class StorePrice(BaseModel):
    price: str
    unit_price: Optional[str] = None
    source_url: Optional[str] = None
    scraped_at: Optional[str] = None


class ProductCompareView(BaseModel):
    product_key: str
    name: str
    packaging_format: Optional[str] = None
    image: Optional[str] = None
    prices_by_store: dict[str, StorePrice]


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


def load_price_snapshots(products_path: Path) -> list[ProductPriceSnapshot]:
    snapshots_path = get_price_snapshots_json_path(products_path)

    if not snapshots_path.exists():
        return []

    try:
        raw = json.loads(snapshots_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    if not isinstance(raw, list):
        return []

    snapshots: list[ProductPriceSnapshot] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            snapshots.append(ProductPriceSnapshot(**item))
        except Exception:
            continue

    return snapshots


def load_product_views() -> list[ProductView]:
    products_path = get_products_json_path()
    products = load_products()
    snapshots = load_price_snapshots(products_path)

    latest_by_key: dict[str, ProductPriceSnapshot] = {}
    for snap in snapshots:
        current = latest_by_key.get(snap.product_key)
        if current is None or snap.scraped_at >= current.scraped_at:
            latest_by_key[snap.product_key] = snap

    views: list[ProductView] = []
    for product in products:
        key = product.product_key
        if not key:
            key = f"{(product.name or '').strip()}__{(product.packaging_format or '').strip()}".lower()

        latest = latest_by_key.get(key)
        views.append(
            ProductView(
                product_key=key,
                name=product.name,
                packaging_format=product.packaging_format,
                image=product.image,
                price=latest.price if latest else None,
                unit_price=latest.unit_price if latest else None,
                source_url=latest.source_url if latest else None,
                scraped_at=latest.scraped_at if latest else None,
                supermarket_name=latest.supermarket_name if latest else None,
            )
        )

    return views


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/products", response_model=list[ProductView])
def list_products(limit: int = Query(default=50, ge=1, le=500)) -> list[ProductView]:
    return load_product_views()[:limit]


@app.get("/products/search", response_model=list[ProductView])
def search_products(
    q: str = Query(default="", min_length=0),
    limit: int = Query(default=8, ge=1, le=50),
) -> list[ProductView]:
    query = q.strip().lower()
    products = load_product_views()

    if not query:
        return products[:limit]

    def score(product: ProductView) -> tuple[int, int]:
        name = product.name.lower()
        starts = 0 if name.startswith(query) else 1
        return (starts, len(name))

    matches = [p for p in products if query in p.name.lower()]
    matches.sort(key=score)
    return matches[:limit]


@app.get("/products/compare", response_model=list[ProductCompareView])
def compare_products(
    key: list[str] = Query(default=[]),
) -> list[ProductCompareView]:
    requested_keys = [k.strip().lower() for k in key if isinstance(k, str) and k.strip()]
    if not requested_keys:
        return []

    # Preserve request order, de-dupe
    unique_keys: list[str] = []
    seen: set[str] = set()
    for k in requested_keys:
        if k in seen:
            continue
        seen.add(k)
        unique_keys.append(k)

    products_path = get_products_json_path()
    products = load_products()
    snapshots = load_price_snapshots(products_path)

    product_by_key: dict[str, Product] = {}
    for product in products:
        computed_key = product.product_key
        if not computed_key:
            computed_key = f"{(product.name or '').strip()}__{(product.packaging_format or '').strip()}".lower()
        product_by_key[computed_key] = product

    latest_by_product_store: dict[tuple[str, str], ProductPriceSnapshot] = {}
    target_set = set(unique_keys)
    for snap in snapshots:
        product_key = (snap.product_key or "").strip().lower()
        if product_key not in target_set:
            continue
        store = (snap.supermarket_name or "").strip()
        if not store:
            continue

        tuple_key = (product_key, store)
        current = latest_by_product_store.get(tuple_key)
        if current is None or snap.scraped_at >= current.scraped_at:
            latest_by_product_store[tuple_key] = snap

    result: list[ProductCompareView] = []
    for product_key in unique_keys:
        product = product_by_key.get(product_key)
        prices_by_store: dict[str, StorePrice] = {}
        for (snap_key, store), snap in latest_by_product_store.items():
            if snap_key != product_key:
                continue
            prices_by_store[store] = StorePrice(
                price=snap.price,
                unit_price=snap.unit_price,
                source_url=snap.source_url,
                scraped_at=snap.scraped_at,
            )

        result.append(
            ProductCompareView(
                product_key=product_key,
                name=product.name if product else product_key,
                packaging_format=product.packaging_format if product else None,
                image=product.image if product else None,
                prices_by_store=prices_by_store,
            )
        )

    return result
