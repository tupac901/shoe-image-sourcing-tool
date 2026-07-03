# Shoe Image Sourcing Tool

Public web app for sourcing shoe product images from ecommerce and image-search platforms for Ozon-oriented listing preparation.

## Features

- Upload a shoe product image.
- Enter brand, model, SKU, color, and keywords.
- Generate English and Russian search queries.
- Search platform entry points for WB, Yandex Images, Ozon, eBay, official search, Lamoda, Avito, StockX, and GOAT.
- Mark Ozon as competitor reference.
- Prepare for duplicate grouping and 3:4 image processing.

## Local Run

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements-shoe-sourcing.txt
uvicorn shoe_image_sourcing.app:app --reload --port 8765
```

Open `http://127.0.0.1:8765`.

## Deploy

GitHub Pages alone is not enough because this app needs a Python backend.

Recommended hosts:

- Render
- Railway
- Fly.io

Use:

```text
Build command: pip install -r requirements-shoe-sourcing.txt
Start command: uvicorn shoe_image_sourcing.app:app --host 0.0.0.0 --port $PORT
```

## Limits

- No login-required scraping.
- No Dewu App automation.
- No iPhone automation.
- Ozon images are competitor references by default.
- Users are responsible for final image usage rights.
