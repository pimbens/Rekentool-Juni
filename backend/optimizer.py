"""
Calculates the cheapest product selection for a given package type.

Units are in KILOGRAMS throughout.

Buying logic:
- Kilo-priced product with box content (e.g. "7 Kilo"): must buy whole box
- Kilo-priced product without box content: buy per kg (min 1 kg)
- Colli-priced product with kilo content: buy whole colli
- Colli-priced product with stuks content: buy whole colli (converted to kg)
- stuk-priced product: buy per piece (converted to kg via grams_per_piece)
"""
import re
import math
from typing import Optional, Tuple
from scipy.optimize import linprog
import numpy as np


def _default_grams(desc: str) -> Optional[float]:
    desc = desc.lower()
    if "appel" in desc:
        return 180.0
    if "peer" in desc or "peren" in desc:
        return 160.0
    if "banaan" in desc or "bananen" in desc:
        return 120.0
    if "mandarijn" in desc:
        return 80.0
    return None


def _parse_box_kg(content: str) -> Optional[float]:
    m = re.match(r"^([\d,]+)\s*kilo$", content.strip(), re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def _parse_box_stuks(content: str) -> Optional[int]:
    m = re.match(
        r"^(\d+)\s*(stuks?|st\.?|bos|punnet|schaal|net|zak|beker|hoes|bakje|ddb|fles)$",
        content.strip(), re.IGNORECASE
    )
    if m:
        return int(m.group(1))
    return None


def compute_unit_info_kg(product: dict) -> Tuple[float, float]:
    """
    Returns (kg_per_purchase_unit, cost_per_purchase_unit).
    - Kilo + box content "7 Kilo" -> must buy whole box: (7.0, 7*price)
    - Kilo + no box content        -> buy per kg:         (1.0, price)
    - Colli + kilo content          -> whole colli:        (kg, colli_price)
    - Colli + stuks content         -> whole colli in kg:  (n*g/1000, colli_price)
    - stuk                          -> per piece in kg:    (g/1000, stuk_price)
    """
    price = product.get("price", 0) or 0
    unit = product.get("price_unit", "")
    content = (product.get("content") or "").strip()
    desc = product.get("description", "").lower()
    grams = product.get("grams_per_piece") or _default_grams(desc)

    if unit == "Kilo":
        kg = _parse_box_kg(content)
        if kg:
            return (kg, round(kg * price, 4))
        return (1.0, price)

    if unit == "Colli":
        kg = _parse_box_kg(content)
        if kg:
            return (kg, price)
        n = _parse_box_stuks(content)
        if n and grams:
            return (round(n * grams / 1000, 4), price)
        m = re.match(r"^(\d+)", content)
        if m and grams:
            n = int(m.group(1))
            if n > 0:
                return (round(n * grams / 1000, 4), price)

    if unit == "stuk":
        if grams:
            return (grams / 1000, price)
        return (0.1, price)

    return (1.0, price)


def estimate_price_per_kg(product: dict) -> Optional[float]:
    """Price per kg (used for ranking cheapest option)."""
    kg, cost = compute_unit_info_kg(product)
    if kg and kg > 0 and cost is not None:
        return round(cost / kg, 4)
    return None


# Voor compatibiliteit met main.py
def estimate_price_per_piece(product: dict) -> Optional[float]:
    return estimate_price_per_kg(product)


def assign_categories(products: list, categories: list) -> list:
    for product in products:
        desc_lower = product["description"].lower()
        for cat in categories:
            keywords = cat.get("keywords", [])
            matched = any(
                re.search(r'\b' + re.escape(kw.lower().strip()), desc_lower)
                for kw in keywords
            )
            if matched:
                product["category_id"] = cat["id"]
                product["price_per_piece"] = estimate_price_per_kg(product)
                break
    return products


def _optimal_fractions(requirements: list, best: dict) -> list:
    n = len(requirements)
    prices, bounds = [], []
    for req in requirements:
        cid = req["category_id"]
        p = best.get(cid)
        prices.append(p["price_per_piece"] if p else 999_999)
        lo = req.get("min_pct", 0) / 100
        hi = req.get("max_pct", 100) / 100
        bounds.append((lo, hi))

    result = linprog(
        np.array(prices),
        A_eq=np.ones((1, n)),
        b_eq=np.array([1.0]),
        bounds=bounds,
        method="highs",
    )
    if result.success:
        return result.x.tolist()
    fracs = [(lo + hi) / 2 for lo, hi in bounds]
    total = sum(fracs) or 1
    return [f / total for f in fracs]


def _purchase_plan_kg(kg_needed: float, product: dict, loose_candidates: list) -> dict:
    kg_per_unit, cost_per_unit = compute_unit_info_kg(product)

    full_units = int(kg_needed / kg_per_unit)
    covered_kg = full_units * kg_per_unit
    gap_kg = round(kg_needed - covered_kg, 6)

    if gap_kg < 0.001:
        return {
            "units": full_units,
            "kg_per_unit": round(kg_per_unit, 3),
            "actual_kg": round(covered_kg, 3),
            "bulk_cost": round(full_units * cost_per_unit, 2),
            "supplement": None,
            "total_cost": round(full_units * cost_per_unit, 2),
        }

    # Optie A: extra eenheid
    cost_a = (full_units + 1) * cost_per_unit
    kg_a = (full_units + 1) * kg_per_unit

    # Optie B: aanvullen met goedkoopste ander product
    best_loose = None
    cost_b = None
    for lp in loose_candidates:
        if lp.get("id") == product.get("id"):
            continue
        if lp.get("price_per_piece") is None:
            continue
        lp_kg_per_unit, lp_cost_per_unit = compute_unit_info_kg(lp)
        if lp_kg_per_unit <= 0:
            continue
        supp_units = math.ceil(gap_kg / lp_kg_per_unit)
        supp_cost = supp_units * lp_cost_per_unit
        candidate_cost = full_units * cost_per_unit + supp_cost
        if cost_b is None or candidate_cost < cost_b:
            cost_b = candidate_cost
            best_loose = (lp, supp_units, round(supp_units * lp_kg_per_unit, 3), round(supp_cost, 2))

    if best_loose and cost_b is not None and cost_b < cost_a:
        lp, supp_units, supp_kg, supp_cost = best_loose
        return {
            "units": full_units,
            "kg_per_unit": round(kg_per_unit, 3),
            "actual_kg": round(covered_kg + supp_kg, 3),
            "bulk_cost": round(full_units * cost_per_unit, 2),
            "supplement": {
                "product": lp,
                "units": supp_units,
                "kg": supp_kg,
                "cost": supp_cost,
            },
            "total_cost": round(cost_b, 2),
        }

    return {
        "units": full_units + 1,
        "kg_per_unit": round(kg_per_unit, 3),
        "actual_kg": round(kg_a, 3),
        "bulk_cost": round((full_units + 1) * cost_per_unit, 2),
        "supplement": None,
        "total_cost": round(cost_a, 2),
    }


def find_cheapest_combination(
    package_type: dict,
    products_by_category: dict,
    num_packages: int,
) -> dict:
    requirements = package_type.get("requirements", [])
    total_kg = package_type.get("total_pieces", 25)
    warnings = []

    best = {}
    for req in requirements:
        cid = req["category_id"]
        candidates = [
            p for p in products_by_category.get(cid, [])
            if p.get("price_per_piece") is not None
        ]
        if not candidates:
            warnings.append(
                f"Geen producten voor categorie '{req.get('category_name', cid)}'"
            )
            best[cid] = None
        else:
            best[cid] = min(candidates, key=lambda p: p["price_per_piece"])

    fractions = _optimal_fractions(requirements, best)

    allocations = []
    grand_total = 0.0

    for i, req in enumerate(requirements):
        cid = req["category_id"]
        kg_per_package = round(fractions[i] * total_kg, 3)
        kg_needed_total = round(kg_per_package * num_packages, 3)

        product = best.get(cid)
        if not product:
            allocations.append({
                "category_id": cid,
                "category_name": req.get("category_name", f"Cat {cid}"),
                "product": None,
                "pct": round(fractions[i] * 100, 1),
                "kg_per_package": kg_per_package,
                "plan": None,
                "total_cost": 0,
            })
            continue

        loose = [
            p for p in products_by_category.get(cid, [])
            if p.get("price_per_piece") is not None
            and p.get("id") != product.get("id")
        ]

        plan = _purchase_plan_kg(kg_needed_total, product, loose)
        grand_total += plan["total_cost"]

        allocations.append({
            "category_id": cid,
            "category_name": req.get("category_name", f"Cat {cid}"),
            "product": product,
            "pct": round(fractions[i] * 100, 1),
            "kg_per_package": kg_per_package,
            "kg_needed": kg_needed_total,
            "plan": plan,
            "price_per_kg": product["price_per_piece"],
            "total_cost": plan["total_cost"],
        })

    return {
        "success": True,
        "allocations": allocations,
        "total_cost_per_package": round(grand_total / num_packages, 2) if num_packages else 0,
        "grand_total": round(grand_total, 2),
        "num_packages": num_packages,
        "warnings": warnings,
    }
