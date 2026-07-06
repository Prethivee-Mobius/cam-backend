"""PDF bounding-box utilities (ported from bbox_utils.py)."""

import re

import fitz  # PyMuPDF


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _clean_currency_variants(value):
    if value is None:
        return []

    if isinstance(value, (int, float)):
        if isinstance(value, float):
            v = f"{value:,.2f}"
        else:
            v = str(value)
    else:
        v = str(value).strip()

    if not v:
        return []

    candidates = [v]
    normalized = _normalize(v)
    if normalized and normalized != v:
        candidates.append(normalized)

    clean = re.sub(r"[^0-9.\-]", "", v)
    if clean and clean != v:
        candidates.append(clean)

    if "," in v:
        candidates.append(v.replace(",", ""))

    if v.endswith(".00"):
        candidates.append(v[:-3])

    seen = set()
    unique = []
    for c in candidates:
        c = c.strip()
        if c and c not in seen:
            seen.add(c)
            unique.append(c)

    return unique


def _search_page_for_text(page: fitz.Page, value, debug: bool = False):
    for candidate in _clean_currency_variants(value):
        rects = page.search_for(candidate)
        if rects:
            if debug:
                print(f"    matched '{candidate}' -> {len(rects)} rect(s)")
            return rects

    target_text = _normalize(str(value)).lower()
    if not target_text:
        return []

    words = page.get_text("words")
    words_sorted = sorted(words, key=lambda w: (w[5], w[6], w[7]))
    target_words = target_text.split()
    n = len(target_words)

    for i in range(len(words_sorted) - n + 1):
        window = words_sorted[i : i + n]
        window_text = " ".join(w[4] for w in window).lower()
        if _normalize(window_text) == " ".join(target_words):
            xs0 = [w[0] for w in window]
            ys0 = [w[1] for w in window]
            xs1 = [w[2] for w in window]
            ys1 = [w[3] for w in window]
            rect = fitz.Rect(min(xs0), min(ys0), max(xs1), max(ys1))
            if debug:
                print(f"    fuzzy match -> {rect}")
            return [rect]

    return []


def _rects_to_coordinates(rects, page_number: int, page_width: float, page_height: float):
    if not rects:
        return None
    x0 = min(r.x0 for r in rects)
    y0 = min(r.y0 for r in rects)
    x1 = max(r.x1 for r in rects)
    y1 = max(r.y1 for r in rects)

    return {
        "page": page_number,
        "page_width": round(page_width, 2),
        "page_height": round(page_height, 2),
        "x0": round(x0, 2),
        "y0": round(y0, 2),
        "x1": round(x1, 2),
        "y1": round(y1, 2),
    }


def annotate_items_with_bbox(
    pdf_path: str,
    items: list,
    value_key: str = "value",
    page_key: str = "page_number",
    debug: bool = False,
    fallback_search_all_pages: bool = True,
):
    if not items:
        return items

    doc = fitz.open(pdf_path)
    total_pages = doc.page_count

    try:
        for idx, item in enumerate(items):
            value = item.get(value_key)
            page_number = item.get(page_key)

            if debug:
                print(f"  [{idx + 1}/{len(items)}] page={page_number} value={value!r}")

            item["pdfCoordinates"] = None

            if value is None or str(value).strip() == "":
                continue

            rects = []
            matched_page = None

            if isinstance(page_number, (int, str)):
                try:
                    p_num = int(page_number)
                    if 1 <= p_num <= total_pages:
                        page = doc[p_num - 1]
                        rects = _search_page_for_text(page, value, debug=debug)
                        if rects:
                            matched_page = p_num
                except (TypeError, ValueError):
                    pass

            if not rects and fallback_search_all_pages:
                if debug:
                    print("    not found on reported page, scanning all pages...")
                for p_idx in range(total_pages):
                    p_num = p_idx + 1
                    if p_num == page_number:
                        continue
                    page = doc[p_idx]
                    rects = _search_page_for_text(page, value, debug=False)
                    if rects:
                        matched_page = p_num
                        if debug:
                            print(f"    found on fallback page {p_num}")
                        break

            if rects and matched_page:
                page = doc[matched_page - 1]
                item["pdfCoordinates"] = _rects_to_coordinates(
                    rects, matched_page, page.rect.width, page.rect.height
                )
                item[page_key] = matched_page
            elif debug:
                print("    not found anywhere in document")

    finally:
        doc.close()

    return items
