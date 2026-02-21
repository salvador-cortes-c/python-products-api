# Products API

REST API that serves the `products.json` produced by `python-playwright-scraper` to the Next.js app.

## Endpoints

- `GET /health`
- `GET /products?limit=50`
- `GET /products/search?q=milk&limit=8`

## Config

The API reads products from `PRODUCTS_JSON_PATH`.

If `PRODUCTS_JSON_PATH` is not set, it assumes this folder layout:

```
/Users/.../
	python-products-api/
	python-playwright-scraper/
	react-supermarket-purchase-helper/
```

Example (macOS/Linux):

```bash
export PRODUCTS_JSON_PATH="/Users/salvador_cortes_catalan/python-playwright-scraper/products.json"
```

## Run locally

```bash
cd python-products-api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open docs:
- http://localhost:8000/docs

## Frontend integration

From Next.js (localhost:3000), call:
- `http://localhost:8000/products/search?q=<query>&limit=8`
