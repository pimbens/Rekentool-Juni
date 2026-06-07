"""
Calculates the cheapest product selection for a given package type.

Buying logic:
- Products priced per "stuk": buy individual pieces (minimum 1)
- Products priced per "Colli" with kilo content: buy whole boxes
- Products priced per "Kilo" with box content: buy whole boxes
- When gap remains after whole boxes: compare buying extra box vs. supplement from loose product
"""
import re
from typing import List, Dict, Optional, Tuple
from scipy.optimize import linprog
import numpy as np


# ─── Helpers ───────────────────────────────────────────────────────────────────────────────

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


def compute_box_info(product: dict) -> Tuple[int, float]:
    """
    Returns (pieces_per_purchase_unit, cost_per_purchase_unit).
    - stuk:  buy per piece -> (1, price)
    - Colli with kilo content: whole box -> (kg*1000/g, price)
    - Colli with stuks content: whole box -> (n, price)
    - Kilo with box size in content: whole box -> (kg*1000/g, kg*price)
    """
    price = product.get("price", 0) or 0
    unit = product.get("price_unit", "")
    content = product.get("content", "")
    desc = product.get("description", "").lower()
    grams = product.get("grams_per_piece") or _default_grams(desc)

    if unit == "stuk":
        return (1, price)

    if unit == "Colli":
        kg = _parse_box_kg(content)
        if kg and grams:
            pieces = max(1, int(kg * 1000 / grams))
            return (pieces, price)
        n = _parse_box_stuks(content)
        if n:
            return (n, price)
        # fallback: leading number
        m = re.match(r"^(\d+)", content.strip())
        if m:
            n = int(m.group(1))
            if n > 0:
                return (n, price)

    if unit == "Kilo":
        kg = _parse_box_kg(content)
        if kg and grams:
            pieces = max(1, int(kg * 1000 / grams))
            return (pieces, round(kg * price, 4))
        if grams:
            # Unknown box size - assume 1 kg minimum
            pieces = max(1, int(1000 / grams))
            return (pieces, price)

    return (1, price)


def estimate_price_per_piece(product: dict) -> Optional[float]:
    """Price per individual piece (used for ranking cheapest option)."""
    pieces, cost = compute_box_info(product)
    if pieces and cost is not None:
        return round(cost / pieces, 4)
    return None


# ─── Category assignment ────────────────────────────────────────────────────────────────────────────

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
                product["price_per_piece"] = estimate_price_per_piece(product)
                break
    return products


# ─── Core optimiser ────────────────────────────────────────────────────────────────────────────

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
    # Fallback: midpoints, normalised
    fracs = [(lo + hi) / 2 for lo, hi in bounds]
    total = sum(fracs) or 1
    return [f / total for f in fracs]


def _purchase_plan(pieces_needed: int, product: dict, loose_candidates: list) -> dict:
    """
    Given a product (possibly box-only) and pieces needed, decide:
      - how many whole boxes to buy
      - whether to top up with a loose product or buy one extra box
    Returns a plan dict.
    """
    ppunit, cost_per_unit = compute_box_info(product)

    if ppunit == 1:
        # Already per piece - buy exact amount
        return {
            "boxes": pieces_needed,
            "pieces_per_box": 1,
            "actual_pieces": pieces_needed,
            "bulk_cost": round(pieces_needed * cost_per_unit, 2),
            "supplement": None,
            "total_cost": round(pieces_needed * cost_per_unit, 2),
        }

    full_boxes = pieces_needed // ppunit
    covered = full_boxes * ppunit
    gap = pieces_needed - covered

    if gap == 0:
        return {
            "boxes": full_boxes,
            "pieces_per_box": ppunit,
            "actual_pieces": covered,
            "bulk_cost": round(full_boxes * cost_per_unit, 2),
            "supplement": None,
            "total_cost": round(full_boxes * cost_per_unit, 2),
        }

    # Option A: buy one extra box
    cost_a = (full_boxes + 1) * cost_per_unit
    pieces_a = (full_boxes + 1) * ppunit

    # Option B: supplement with cheapest loose product (price_unit == stuk, min 1 piece)
    best_loose = None
    cost_b = None
    for lp in loose_candidates:
        if lp.get("id") == product.get("id"):
            continue
        lp_ppu = lp.get("price_per_piece")
        if lp_ppu is None:
            continue
        candidate_cost = full_boxes * cost_per_unit + gap * lp_ppu
        if cost_b is None or candidate_cost < cost_b:
            cost_b = candidate_cost
            best_loose = lp

    if best_loose and cost_b is not None and cost_b < cost_a:
        return {
            "boxes": full_boxes,
            "pieces_per_box": ppunit,
            "actual_pieces": covered + gap,
            "bulk_cost": round(full_boxes * cost_per_unit, 2),
            "supplement": {
                "product": best_loose,
                "pieces": gap,
                "cost": round(gap * best_loose["price_per_piece"], 2),
            },
            "total_cost": round(cost_b, 2),
        }

    # Default: extra box
    return {
        "boxes": full_boxes + 1,
        "pieces_per_box": ppunit,
        "actual_pieces": pieces_a,
        "bulk_cost": round((full_boxes + 1) * cost_per_unit, 2),
        "supplement": None,
        "total_cost": round(cost_a, 2),
    }


def find_cheapest_combination(
    package_type: dict,
    products_by_category: dict,
    num_packages: int,
) -> dict:
    requirements = package_type.get("requirements", [])
    total_pieces = package_type.get("total_pieces", 100)
    warnings = []

    # Best (cheapest per piece) product per category
    best = {}
    for req in requirements:
        cid = req["category_id"]
        candidates = [
            p for p in products_by_category.get(cid, [])
            if p.get("price_per_piece") is not None
        ]
        if not candidates:
            warnings.append(
                f"Geen producten met bekende stuksprijs voor categorie '{req.get('category_name', cid)}'"
            )
            best[cid] = None
        else:
            best[cid] = min(candidates, key=lambda p: p["price_per_piece"])

    fractions = _optimal_fractions(requirements, best)

    allocations = []
    grand_total = 0.0

    for i, req in enumerate(requirements):
        cid = req["category_id"]
        pieces_per_package = round(fractions[i] * total_pieces)
        pieces_needed_total = pieces_per_package * num_packages

        product = best.get(cid)
        if not product:
            allocations.append({
                "category_id": cid,
                "category_name": req.get("category_name", f"Cat {cid}"),
                "product": None,
                "pct": round(fractions[i] * 100, 1),
                "pieces_per_package": pieces_per_package,
                "plan": None,
                "total_cost": 0,
            })
            continue

        # Loose candidates = other products in same category with price_unit stuk
        loose = [
            p for p in products_by_category.get(cid, [])
            if p.get("price_per_piece") is not None
            and p.get("price_unit") == "stuk"
            and p.get("id") != product.get("id")
        ]

        plan = _purchase_plan(pieces_needed_total, product, loose)
        grand_total += plan["total_cost"]

        allocations.append({
            "category_id": cid,
            "category_name": req.get("category_name", f"Cat {cid}"),
            "product": product,
            "pct": round(fractions[i] * 100, 1),
            "pieces_per_package": pieces_per_package,
            "pieces_needed": pieces_needed_total,
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
