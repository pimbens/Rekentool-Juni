"""
Calculates the cheapest product selection for a given package type.

Buying logic:
- Products priced per Kilo with box content (e.g. "7 Kilo"): buy whole boxes
- Products priced per Colli with kilo content: buy whole collis
- Products priced per stuk: treated as kg using grams_per_piece
- When gap remains after whole boxes: compare buying extra box vs. supplement from other product
"""
import re
from typing import List, Dict, Optional, Tuple
from scipy.optimize import linprog
import numpy as np


# ─── Helpers ──────────────────────────────────────────────────────────────────

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
    - Kilo + "7 Kilo" content → buy whole box of 7 kg at 7 * price_per_kg
    - Kilo + no kg content → 1 kg minimum at price
    - Colli + "18 Kilo" content → whole colli at colli_price
    - Colli + stuks content → n * grams/1000 kg at colli_price
    - stuk → grams_per_piece/1000 kg at stuk_price
    """
    price = product.get("price", 0) or 0
    unit = product.get("price_unit", "")
    content = product.get("content", "") or ""
    grams = product.get("grams_per_piece")

    if unit == "Kilo":
        kg = _parse_box_kg(content)
        if kg and kg > 0:
            return (kg, round(kg * price, 4))
        # No box info — minimum 1 kg
        return (1.0, price)

    if unit == "Colli":
        kg = _parse_box_kg(content)
        if kg and kg > 0:
            return (kg, price)
        n = _parse_box_stuks(content)
        if n and grams:
            kg_colli = round(n * grams / 1000, 4)
            return (kg_colli, price)
        m = re.match(r"^(\d+)", content.strip())
        if m and grams:
            n = int(m.group(1))
            if n > 0:
                kg_colli = round(n * grams / 1000, 4)
                return (kg_colli, price)
        return (1.0, price)

    if unit == "stuk":
        if grams and grams > 0:
            return (round(grams / 1000, 4), price)
        return (0.1, price)  # fallback ~100g

    return (1.0, price)


def estimate_price_per_kg(product: dict) -> Optional[float]:
    kg, cost = compute_unit_info_kg(product)
    if kg and kg > 0 and cost is not None:
        return round(cost / kg, 4)
    return None


def estimate_price_per_piece(product: dict) -> Optional[float]:
    """Alias for kg-based pricing, kept for compatibility with main.py imports."""
    return estimate_price_per_kg(product)


# ─── Category assignment ──────────────────────────────────────────────────────

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


# ─── Core optimiser ───────────────────────────────────────────────────────────

def _optimal_fractions(requirements: list, best: dict) -> list:
    """Solve LP for optimal percentage allocation."""
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
    """
    Given kg needed and a product with a fixed purchase unit size,
    decide how many units to buy and whether to supplement the gap.
    """
    kg_per_unit, cost_per_unit = compute_unit_info_kg(product)

    if kg_per_unit <= 0:
        return {
            "units": 0, "kg_per_unit": 0, "actual_kg": 0,
            "bulk_cost": 0, "supplement": None, "total_cost": 0,
        }

    full_units = int(kg_needed / kg_per_unit)
    covered_kg = full_units * kg_per_unit
    gap_kg = round(kg_needed - covered_kg, 6)

    if gap_kg < 0.001:
        return {
            "units": full_units,
            "kg_per_unit": kg_per_unit,
            "actual_kg": covered_kg,
            "bulk_cost": round(full_units * cost_per_unit, 2),
            "supplement": None,
            "total_cost": round(full_units * cost_per_unit, 2),
        }

    # Option A: extra unit
    cost_a = (full_units + 1) * cost_per_unit
    kg_a = (full_units + 1) * kg_per_unit

    # Option B: supplement with cheapest other product
    best_loose = None
    cost_b = None
    for lp in loose_candidates:
        if lp.get("id") == product.get("id"):
            continue
        lp_ppkg = lp.get("price_per_piece")
        if lp_ppkg is None:
            continue
        lp_kg_unit, lp_cost_unit = compute_unit_info_kg(lp)
        if lp_kg_unit <= 0:
            continue
        supp_units = int(gap_kg / lp_kg_unit) + (1 if gap_kg % lp_kg_unit > 0.001 else 0)
        supp_units = max(1, supp_units)
        candidate_cost = full_units * cost_per_unit + supp_units * lp_cost_unit
        if cost_b is None or candidate_cost < cost_b:
            cost_b = candidate_cost
            best_loose = (lp, supp_units)

    if best_loose and cost_b is not None and cost_b < cost_a:
        lp, supp_units = best_loose
        lp_kg_unit, lp_cost_unit = compute_unit_info_kg(lp)
        return {
            "units": full_units,
            "kg_per_unit": kg_per_unit,
            "actual_kg": round(covered_kg + supp_units * lp_kg_unit, 3),
            "bulk_cost": round(full_units * cost_per_unit, 2),
            "supplement": {
                "product": lp,
                "kg": round(supp_units * lp_kg_unit, 3),
                "units": supp_units,
                "cost": round(supp_units * lp_cost_unit, 2),
            },
            "total_cost": round(cost_b, 2),
        }

    return {
        "units": full_units + 1,
        "kg_per_unit": kg_per_unit,
        "actual_kg": round(kg_a, 3),
        "bulk_cost": round(cost_a, 2),
        "supplement": None,
        "total_cost": round(cost_a, 2),
    }


def find_cheapest_combination(
    package_type: dict,
    products_by_category: dict,
    num_packages: int,
) -> dict:
    requirements = package_type.get("requirements", [])
    total_kg = package_type.get("total_pieces", 25)  # kg per package
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
                f"Geen producten met bekende prijs voor categorie '{req.get('category_name', cid)}'"
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
                "pieces_per_package": kg_per_package,
                "plan": None,
                "total_cost": 0,
                "price_per_piece": None,
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
            "pieces_per_package": kg_per_package,
            "pieces_needed": kg_needed_total,
            "plan": plan,
            "price_per_piece": product["price_per_piece"],
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
