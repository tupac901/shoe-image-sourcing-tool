from .models import ProductFacts


def _join(parts: list[str | None]) -> str:
    return " ".join(part.strip() for part in parts if part and part.strip())


def generate_queries(facts: ProductFacts) -> list[str]:
    base = _join([facts.brand, facts.model, facts.sku, facts.color])
    sku_base = _join([facts.brand, facts.model, facts.sku])
    sku_first_base = _join([facts.sku, facts.brand, facts.model, facts.color])
    keyword_base = _join([facts.brand, facts.keywords])
    primary = base or keyword_base or "shoe product"
    sku = facts.sku or primary

    queries = [
        f"{sku_first_base} product images" if sku_first_base else None,
        f"{primary} shoes",
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
        normalized = " ".join(query.split())
        if normalized not in seen:
            seen.add(normalized)
            unique.append(normalized)
    return unique
