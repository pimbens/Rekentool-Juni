"""
Calculates the cheapest product selection for a given package type.

For each category we pick the cheapest available product (lowest price per piece).
Then we solve a linear program to find the optimal percentage allocation
within the allowed ranges such that total = 100%.
"""
from typing import List, Dict, Optional
from scipy.optimize import linprog
import numpy as np


def assign_categories(products: list, categories: list) -> list:
    """
    For each product, try to assign it to a category based on keyword matching.
    Returns products with category_id and estimated price_per_piece set.
    """
    import re
    for product in products:
        desc_lower = product["description"].lower()
        for cat in categories:
            keywords = cat.get("keywords", [])
            matched = False
            for kw in keywords:
                if re.search(r'\b' + re.escape(kw.lower().strip()), desc_lower):
                    matched = True
                    break
            if matched:
                product["category_id"] = cat["id"]
                product["price_per_piece"] = estimate_price_per_piece(product)
                break
    return products


def estimate_price_per_piece(product: dict) -> Optional[float]:
    """
    Estimate price per piece from the product data.
    - price_unit == "stuk": price is already per piece
    - price_unit == "Kilo": need grams_per_piece override; fall back to None
    - price_unit == "Colli": divide price by number of pieces extracted from content
    """
    price = product.get("price")
    if price is None:
        return None
    unit = product.get("price_unit", "")
    if unit == "stuk":
        return price

    content = product.get("content", "")
    desc = product.get("description", "").lower()
    if unit == "Colli":
        import re
        # Content like "18 Kilo", "12,5 Kilo" → price per kg = price/kg, then use grams_per_piece
        kilo_match = re.match(r"^([\d,]+)\s*kilo$", content.strip(), re.IGNORECASE)
        if kilo_match:
            kg = float(kilo_match.group(1).replace(",", "."))
            price_per_kg = price / kg
            grams = product.get("grams_per_piece")
            if not grams:
                if "appel" in desc:
                    grams = 180
                elif "peer" in desc or "peren" in desc:
                    grams = 160
                elif "banaan" in desc or "bananen" in desc:
                    grams = 120
                elif "mandarijn" in desc:
                    grams = 80
            if grams:
                return round(price_per_kg * grams / 1000, 4)
            return None
        # Content like "6 Stuks", "26 Stuks"
        stuks_match = re.match(r"^(\d+)\s*(stuks?|st\.?|bos|punnet|schaal|net|zak|beker|hoes|bakje)$",
                               content.strip(), re.IGNORECASE)
        if stuks_match:
            n = int(stuks_match.group(1))
            return round(price / n, 4)
        # Fallback: try to parse leading number
        num_match = re.match(r"^(\d+)", content.strip())
        if num_match:
            n = int(num_match.group(1))
            if n > 0:
                return round(price / n, 4)

    if unit == "Kilo":
        grams = product.get("grams_per_piece")
        if not grams:
            # Fallback defaults based on description keywords
            desc = product.get("description", "").lower()
            if "appel" in desc:
                grams = 180  # ~180g per apple
            elif "peer" in desc or "peren" in desc:
                grams = 160
            elif "banaan" in desc or "bananen" in desc:
                grams = 120
            elif "mandarijn" in desc:
                grams = 80
        if grams:
            return round(price * grams / 1000, 4)
        return None

    return None


def find_cheapest_combination(
    package_type: dict,
    products_by_category: dict,  # {category_id: [product_dicts]}
    num_packages: int,
) -> dict:
    """
    Returns the cheapest product selection and allocation for num_packages packages.

    package_type.requirements: [{"category_id", "min_pct", "max_pct"}, ...]
      The last requirement without explicit max is treated as "rest" (fill up to 100%).

    Returns:
      {
        "success": bool,
        "allocations": [{"category_id", "category_name", "product", "pct", "pieces_per_package", "total_pieces", "price_per_piece", "total_cost"}],
        "total_cost_per_package": float,
        "grand_total": float,
        "warnings": [str],
      }
    """
    requirements = package_type.get("requirements", [])
    total_pieces = package_type.get("total_pieces", 100)
    warnings = []

    # For each category, find the cheapest product (by price_per_piece)
    best = {}  # category_id -> product dict
    for req in requirements:
        cid = req["category_id"]
        candidates = [p for p in products_by_category.get(cid, [])
                      if p.get("price_per_piece") is not None]
        if not candidates:
            warnings.append(f"Geen producten met bekende stuksprijs voor categorie {cid}")
            best[cid] = None
        else:
            best[cid] = min(candidates, key=lambda p: p["price_per_piece"])

    # Solve LP to find optimal percentages
    # Variables: x_i = fraction (0-1) for each category
    # Objective: minimize sum(price_per_piece_i * x_i)  (per piece cost)
    # Constraints: sum(x_i) = 1, min_pct/100 <= x_i <= max_pct/100
    n = len(requirements)
    prices = []
    bounds = []
    for req in requirements:
        cid = req["category_id"]
        p = best.get(cid)
        price_pp = p["price_per_piece"] if p else 999999
        prices.append(price_pp)
        lo = req.get("min_pct", 0) / 100
        hi = req.get("max_pct", 100) / 100
        bounds.append((lo, hi))

    c = np.array(prices)
    # Equality: sum = 1
    A_eq = np.ones((1, n))
    b_eq = np.array([1.0])

    result = linprog(c, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")

    if not result.success:
        # Fallback: use midpoints
        fractions = [(lo + hi) / 2 for lo, hi in bounds]
        total = sum(fractions)
        fractions = [f / total for f in fractions]
    else:
        fractions = result.x.tolist()

    # Build allocations
    allocations = []
    total_cost_per_package = 0.0
    for i, req in enumerate(requirements):
        cid = req["category_id"]
        pct = round(fractions[i] * 100, 1)
        pieces = round(fractions[i] * total_pieces)
        p = best.get(cid)
        price_pp = p["price_per_piece"] if p else 0
        cost_per_package = price_pp * pieces
        total_cost_per_package += cost_per_package
        allocations.append({
            "category_id": cid,
            "category_name": req.get("category_name", f"Cat {cid}"),
            "product": p,
            "pct": pct,
            "pieces_per_package": pieces,
            "total_pieces": pieces * num_packages,
            "price_per_piece": price_pp,
            "cost_per_package": round(cost_per_package, 2),
            "total_cost": round(cost_per_package * num_packages, 2),
        })

    return {
        "success": True,
        "allocations": allocations,
        "total_cost_per_package": round(total_cost_per_package, 2),
        "grand_total": round(total_cost_per_package * num_packages, 2),
        "num_packages": num_packages,
        "warnings": warnings,
    }
