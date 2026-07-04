from __future__ import annotations

import re

from .models import ProductFacts


KNOWN_BRANDS = [
    "Nike",
    "Adidas",
    "Puma",
    "Reebok",
    "Asics",
    "New Balance",
    "Mizuno",
    "Fila",
    "Skechers",
    "Under Armour",
    "Converse",
    "Vans",
    "Jordan",
]

SKU_PATTERNS = [
    re.compile(r"(?:官方货号|货号|款号|型号|sku|article|артикул)\s*[:：]?\s*([A-Z0-9][A-Z0-9-]{4,})", re.I),
    re.compile(r"\b([A-Z0-9]{3,}-[A-Z0-9]{2,})\b", re.I),
]

MODEL_LABEL_PATTERN = re.compile(r"(?:俄语名称|品类|标题|商品标题|名称|产品名称|title|name)\s*[:：]\s*(.+)", re.I)
COLOR_LABEL_PATTERN = re.compile(r"(?:Цвет модели|颜色|色号|color|цвет)\s*[:：]\s*(.+)", re.I)


def _join(parts: list[str | None]) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())


def _quote(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    return f'"{value}"' if value else None


def _clean_line(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("【", " ").replace("】", " ")).strip(" -|,，;；")


def _extract_labeled(pattern: re.Pattern[str], text: str) -> str | None:
    for line in text.splitlines():
        match = pattern.search(line)
        if match:
            value = _clean_line(match.group(1))
            if value:
                return value
    return None


def _extract_brand(text: str) -> str | None:
    lower_text = text.lower()
    for brand in KNOWN_BRANDS:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(brand.lower())}(?![A-Za-z0-9])", lower_text):
            return brand
    return None


def _extract_sku(text: str) -> str | None:
    for pattern in SKU_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).upper()
    return None


def _extract_model(text: str, brand: str | None, sku: str | None) -> str | None:
    labeled = _extract_labeled(MODEL_LABEL_PATTERN, text)
    source = labeled or " ".join(line.strip() for line in text.splitlines()[:6])
    if sku:
        source = source.replace(sku, "")
    if brand:
        brand_match = re.search(rf"{re.escape(brand)}\s+([A-Za-z0-9][A-Za-z0-9 '\-]+)", source, re.I)
        if brand_match:
            model = _clean_line(brand_match.group(1))
            model = re.split(r"\s{2,}|[|｜,，;；]", model)[0].strip()
            if model:
                return model[:80]
    cleaned = _clean_line(source)
    return cleaned[:100] or None


def _extract_keywords(text: str, brand: str | None, model: str | None) -> str | None:
    useful_lines = []
    for line in text.splitlines():
        line = _clean_line(line)
        if not line:
            continue
        if any(label in line.lower() for label in ["目标用户", "使用场景", "核心卖点", "dad shoes", "кроссовки"]):
            useful_lines.append(line)
    value = " ".join(useful_lines)
    if not value:
        value = _join([brand, model])
    return value[:220] or None


def enrich_product_facts(facts: ProductFacts) -> ProductFacts:
    """Fill empty fields from a pasted product information block."""
    if not facts.product_text:
        return facts

    text = facts.product_text
    brand = facts.brand or _extract_brand(text)
    sku = facts.sku or _extract_sku(text)
    model = facts.model or _extract_model(text, brand, sku)
    color = facts.color or _extract_labeled(COLOR_LABEL_PATTERN, text)
    keywords = facts.keywords or _extract_keywords(text, brand, model)
    return ProductFacts(
        product_text=facts.product_text,
        brand=brand,
        model=model,
        sku=sku,
        color=color,
        keywords=keywords,
    )


def generate_queries(facts: ProductFacts) -> list[str]:
    base = _join([facts.brand, facts.model, facts.sku, facts.color])
    sku_base = _join([facts.brand, facts.model, facts.sku])
    sku_first_base = _join([facts.sku, facts.brand, facts.model])
    sku_color_base = _join([facts.sku, facts.brand, facts.model, facts.color])
    keyword_base = _join([facts.brand, facts.keywords])
    primary = base or keyword_base or "shoe product"
    sku = facts.sku or primary
    exact_sku_model_query = _join([_quote(facts.sku), _quote(_join([facts.brand, facts.model])), "shoe"]) if facts.sku else None

    queries = [
        exact_sku_model_query,
        f"{sku_first_base} product images" if sku_first_base else None,
        f"{sku_first_base} official product photos" if sku_first_base else None,
        f"{primary} shoes",
        f"{sku_color_base} shoes" if facts.color and sku_color_base != sku_first_base else None,
        f"{primary} кроссовки",
        f"{sku_base} кроссовки" if sku_base else None,
        f"{sku} {facts.brand or ''} shoe product photos".strip(),
        f"{primary} купить",
        f"{primary} фото обуви",
    ]
    if keyword_base and keyword_base != primary:
        queries.append(f"{keyword_base} shoes")

    unique = []
    seen = set()
    for query in queries:
        if not query:
            continue
        normalized = " ".join(query.split())
        if normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique
