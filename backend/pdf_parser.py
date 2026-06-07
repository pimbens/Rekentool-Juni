import re
import pdfplumber
from typing import List, Dict, Optional


def parse_price_list(file_path: str) -> List[Dict]:
    """Extract product rows from a Willem Dijk AGF price list PDF."""
    products = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    product = _parse_row(row)
                    if product:
                        products.append(product)
    # Deduplicate by description
    seen = set()
    unique = []
    for p in products:
        if p["description"] not in seen:
            seen.add(p["description"])
            unique.append(p)
    return unique


def _parse_row(row) -> Optional[Dict]:
    if not row or len(row) < 4:
        return None
    # Expected columns: Omschrijving | Inhoud | per | Prijs | per | Aantal
    # Filter out header rows and section headers
    description = str(row[0] or "").strip()
    if not description or description in ("Omschrijving", "") :
        return None
    # Skip section headers (no price)
    price_str = str(row[3] or "").strip() if len(row) > 3 else ""
    if not price_str:
        return None
    price = _parse_price(price_str)
    if price is None:
        return None

    content = str(row[1] or "").strip() if len(row) > 1 else ""
    packaging = str(row[2] or "").strip() if len(row) > 2 else ""
    price_unit_raw = str(row[4] or "").strip() if len(row) > 4 else ""
    price_unit = _normalize_unit(price_unit_raw)

    return {
        "description": description,
        "content": content,
        "packaging": packaging,
        "price": price,
        "price_unit": price_unit,
    }


def _parse_price(s: str) -> Optional[float]:
    s = s.replace("€", "").replace(",", ".").strip()
    match = re.search(r"[\d]+\.[\d]+|[\d]+", s)
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None


def _normalize_unit(s: str) -> str:
    s = s.lower().strip()
    if "kilo" in s or "kg" in s:
        return "Kilo"
    if "colli" in s:
        return "Colli"
    if "stuk" in s or "stuks" in s:
        return "stuk"
    return s or "onbekend"
