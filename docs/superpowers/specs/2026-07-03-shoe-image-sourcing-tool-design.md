# Public Shoe Image Sourcing Tool Design

## Goal

Build a public web tool for shoe product image sourcing that can be deployed from GitHub and used by other users. A user uploads a product image and optional product facts, then the tool searches priority ecommerce and image platforms, collects candidate product images, removes duplicates, crops selected images to a 3:4 Ozon-friendly ratio, and lets the user download originals and processed images.

This first version does not integrate with the existing ERP and is not limited to one local machine.

## Target User

The primary user is an Ozon Russia local-store operator sourcing shoe images for marketplace listing preparation. Secondary users may be other marketplace operators. The tool should prioritize sources useful for Ozon differentiation, not generic image scraping volume.

## First-Version Platform Scope

Default enabled platforms:

- Wildberries / WB
- Yandex Images
- Ozon
- eBay
- Brand official site / official store search
- Lamoda
- Avito
- StockX
- GOAT

Available but default disabled:

- Amazon
- AliExpress
- Farfetch
- Мегамаркет
- KazanExpress / Магнит Маркет

Ozon images are treated as competitor-reference images by default. They should help identify common competitor visual styles, not become the preferred export source.

## Core Workflow

1. User uploads a shoe product image.
2. User optionally enters brand, model, SKU/article number, color, and free-form keywords.
3. The tool generates English and Russian search queries.
4. The user selects target platforms.
5. The crawler searches selected platforms and collects image candidates with source URL, platform, page title, and image URL.
6. Images are downloaded into a per-run storage area.
7. The tool removes near-duplicates and filters low-quality images.
8. Images are shown in a local web interface as a source-labeled gallery.
9. User selects images to export.
10. Selected images are cropped/padded to 3:4 and downloaded together with originals.

## Deployment Model

The project should be hosted on GitHub and deployable as a web application.

Recommended first deployment:

- GitHub repository for source code.
- Frontend deployed on Vercel or Render.
- Backend API deployed on Render, Railway, Fly.io, or another small Python-friendly host.
- Optional object storage for generated images and run artifacts. For the first public MVP, short-lived local/server storage is acceptable if the host supports it; production should use S3-compatible storage.

GitHub Pages alone is not enough because the tool needs backend crawling, image downloading, image processing, and duplicate detection.

The README should include one-click or clear deployment instructions.

## Image Handling Rules

- Keep original downloaded images unchanged.
- Create processed 3:4 output copies in a separate folder.
- Prefer center crop with white or neutral padding when cropping would cut off the shoe.
- Filter tiny images and obvious icons/logos.
- Use perceptual hash for duplicate and near-duplicate detection in the first version.
- Preserve source metadata in a JSON manifest.

## Ozon Differentiation Rules

- Mark Ozon-sourced images as `competitor_reference_only` by default.
- If a non-Ozon image is visually very similar to an Ozon image, mark it as `possible_ozon_similarity`.
- Prefer non-Ozon sources for final export when quality is comparable.
- Prioritize WB, eBay, official sites, StockX, GOAT, Lamoda, and Avito for usable image material.
- Keep Ozon images visible in the gallery so the user can judge competitor sameness.

## UI Design

The first version is a local web app.

Main layout:

- Left panel: upload image, product facts, platform checkboxes, run button.
- Center panel: crawl progress and logs.
- Right/main area: gallery grid.
- Top filters: platform, duplicate status, Ozon reference status, processed/not processed.
- Image card: thumbnail, source platform, source link, dimensions, duplicate label, select checkbox.
- Actions: remove duplicates, crop selected to 3:4, export selected.

## Data Layout

Each crawl creates a timestamped run folder or object-storage prefix:

```text
outputs/shoe_image_sourcing/runs/<timestamp>/
  input/
  originals/
  processed_3x4/
  thumbnails/
  manifest.json
  report.csv
```

`manifest.json` records:

- run id
- input facts
- generated queries
- platform
- source page URL
- image URL
- local original path
- processed path
- width and height
- duplicate group id
- source status labels

## Implementation Approach

Use a web app with a deployable frontend and backend.

Recommended stack:

- FastAPI for backend API.
- React or simple server-rendered frontend for the web UI.
- Playwright for pages that require browser rendering.
- Requests/HTTPX for direct image downloads.
- Pillow for image processing.
- imagehash or OpenCV/phash for duplicate detection.
- Redis/RQ, Celery, or a simple background task queue if crawl jobs become slow.

The crawler should be modular, with one adapter per platform. Each adapter returns normalized candidate records. If a platform blocks or changes page structure, it should fail independently and leave an error entry in the run log.

For public deployment, crawling should be job-based instead of a long blocking HTTP request. The first version can use an in-process job registry if deployed to a single instance, but the design should leave room for Redis-backed jobs.

## Public-Use Safety and Limits

- Add file size limits for uploads.
- Add accepted file type checks.
- Add per-IP rate limits.
- Add per-run image count limits.
- Do not store user uploads permanently by default.
- Add a cleanup job for old run artifacts.
- Display source links and make users responsible for final usage rights.
- Do not collect login cookies or private account data.

## First-Version Non-Goals

- No ERP integration.
- No得物 App automation.
- No iPhone automation.
- No login-required scraping.
- No guaranteed bypass of anti-bot systems.
- No automatic use of copyrighted images in final listings. The tool collects candidates for review and listing preparation.
- No multi-user account system in the first version.
- No paid plan, billing, or team workspace.

## Success Criteria

- User can upload one shoe image and enter basic facts.
- Tool can run at least Yandex Images, WB, Ozon, eBay, and one official/search-based source path.
- Tool displays downloaded candidates in a local gallery.
- Duplicate detection groups repeated images.
- Selected images export as 3:4 copies.
- Ozon images are clearly marked as competitor reference.
- The project can be deployed from GitHub using documented instructions.
- A public user can run a crawl without local setup.
