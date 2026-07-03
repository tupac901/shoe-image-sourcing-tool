# Shoe Image Sourcing Tool

Public web app for sourcing shoe/product images from marketplace and search platforms, then deduplicating and converting useful candidates to a 3:4 image format for Ozon listing work.

## What It Does

- Upload a product image and basic product facts.
- Generate search queries for shoes and marketplace product image research.
- Collect image candidates from platforms such as Wildberries, Yandex, Ozon, eBay, Lamoda, Avito, StockX, GOAT, official sites, Amazon, AliExpress, Farfetch, Megamarket, and KazanExpress.
- Mark Ozon results as competitor reference only, so they are used for differentiation instead of direct copying.
- Download available images, remove near-duplicates, create thumbnails, and normalize selected assets to 900 x 1200 pixels.

## Deploy

This is a FastAPI app, so it needs a backend host. GitHub Pages cannot run the crawler backend.

Recommended deployment:

1. Import this repository into Render.
2. Render will detect `render.yaml`.
3. Create the service and wait for build completion.

Build command:

```bash
pip install -r requirements-shoe-sourcing.txt
```

Start command:

```bash
uvicorn shoe_image_sourcing.app:app --host 0.0.0.0 --port $PORT
```

## Local Run

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-shoe-sourcing.txt
uvicorn shoe_image_sourcing.app:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

## Notes

Some platforms block automated public-page requests or require login/session access. In those cases the app keeps the platform search page as a manual review source instead of fabricating image results.
