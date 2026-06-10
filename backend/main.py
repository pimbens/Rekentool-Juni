import os
import re
import tempfile
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import (
    get_db, init_db, FruitCategory, PackageType,
    CategoryMapping, PriceListUpload, Product
)
from pdf_parser import parse_price_list
from optimizer import assign_categories, estimate_price_per_piece, find_cheapest_combination

app = FastAPI(title="Rekentool Fruitpakketten")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND_DIR, "static")), name="static")


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/admin")
def admin():
    return FileResponse(os.path.join(FRONTEND_DIR, "admin.html"))


@app.post("/api/upload-price-list")
async def upload_price_list(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith(".pdf"):
        raise HTTPException(400, "Alleen PDF-bestanden zijn toegestaan")

    db.query(PriceListUpload).update({"active": False})

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        import asyncio
        from concurrent.futures import ThreadPoolExecutor
        import logging
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger(__name__)
        logger.info(f"Start verwerken PDF: {file.filename}")
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            rows = await loop.run_in_executor(pool, parse_price_list, tmp_path)
        logger.info(f"PDF verwerkt: {len(rows)} rijen gevonden")
    except Exception as e:
        raise HTTPException(500, f"Fout bij verwerken PDF: {str(e)}")
    finally:
        os.unlink(tmp_path)

    upload = PriceListUpload(filename=file.filename)
    db.add(upload)
    db.flush()

    categories = db.query(FruitCategory).all()
    cat_list = [{"id": c.id, "name": c.name, "keywords": c.keywords} for c in categories]

    mappings = db.query(CategoryMapping).all()
    mapping_dict = {}
    for m in mappings:
        mapping_dict[m.product_keyword.lower()] = (m.category_id, m.grams_per_piece)

    products_added = 0
    for row in rows:
        row_copy = dict(row)
        desc_lower = row_copy["description"].lower()
        matched_cat = None
        matched_grams = None
        for kw, (cid, grams) in mapping_dict.items():
            if kw in desc_lower:
                matched_cat = cid
                matched_grams = grams
                break

        if matched_cat is None:
            import re as _re
            for cat in cat_list:
                for kw in cat["keywords"]:
                    pattern = r'\b' + _re.escape(kw.lower().strip())
                    if _re.search(pattern, desc_lower):
                        matched_cat = cat["id"]
                        break
                if matched_cat is not None:
                    break

        row_copy["category_id"] = matched_cat
        row_copy["grams_per_piece"] = matched_grams
        row_copy["price_per_piece"] = estimate_price_per_piece({**row_copy})

        p = Product(
            price_list_id=upload.id,
            description=row_copy["description"],
            content=row_copy.get("content", ""),
            packaging=row_copy.get("packaging", ""),
            price=row_copy.get("price"),
            price_unit=row_copy.get("price_unit", ""),
            category_id=matched_cat,
            grams_per_piece=matched_grams,
            price_per_piece=row_copy.get("price_per_piece"),
        )
        db.add(p)
        products_added += 1

    db.commit()
    return {"id": upload.id, "filename": file.filename, "products_parsed": products_added}


@app.get("/api/price-list/active")
def get_active_price_list(db: Session = Depends(get_db)):
    upload = db.query(PriceListUpload).filter(PriceListUpload.active == True).order_by(PriceListUpload.id.desc()).first()
    if not upload:
        return {"active": False, "products": []}
    products = db.query(Product).filter(Product.price_list_id == upload.id).all()
    return {
        "active": True,
        "id": upload.id,
        "filename": upload.filename,
        "upload_date": upload.upload_date.isoformat(),
        "products": [
            {
                "id": p.id,
                "description": p.description,
                "content": p.content,
                "packaging": p.packaging,
                "price": p.price,
                "price_unit": p.price_unit,
                "category_id": p.category_id,
                "price_per_piece": p.price_per_piece,
            }
            for p in products
        ],
    }


@app.get("/api/price-lists")
def list_price_lists(db: Session = Depends(get_db)):
    uploads = db.query(PriceListUpload).order_by(PriceListUpload.id.desc()).limit(20).all()
    return [{"id": u.id, "filename": u.filename, "upload_date": u.upload_date.isoformat(), "active": u.active} for u in uploads]


@app.post("/api/price-lists/{list_id}/activate")
def activate_price_list(list_id: int, db: Session = Depends(get_db)):
    db.query(PriceListUpload).update({"active": False})
    u = db.query(PriceListUpload).filter(PriceListUpload.id == list_id).first()
    if not u:
        raise HTTPException(404)
    u.active = True
    db.commit()
    return {"ok": True}


class OrderItem(BaseModel):
    package_type_id: int
    quantity: int


@app.post("/api/calculate")
def calculate(order: List[OrderItem], db: Session = Depends(get_db)):
    upload = db.query(PriceListUpload).filter(PriceListUpload.active == True).order_by(PriceListUpload.id.desc()).first()
    if not upload:
        raise HTTPException(400, "Geen actieve prijslijst. Upload eerst een prijslijst.")

    results = []
    for item in order:
        pkg = db.query(PackageType).filter(PackageType.id == item.package_type_id).first()
        if not pkg:
            raise HTTPException(404, f"Pakkettype {item.package_type_id} niet gevonden")

        cats = {c.id: c for c in db.query(FruitCategory).all()}
        requirements = pkg.requirements or []
        for req in requirements:
            cid = req["category_id"]
            req["category_name"] = cats[cid].name if cid in cats else f"Cat {cid}"

        products_by_cat = {}
        for req in requirements:
            cid = req["category_id"]
            prods = db.query(Product).filter(
                Product.price_list_id == upload.id,
                Product.category_id == cid,
            ).all()
            products_by_cat[cid] = [
                {
                    "id": p.id,
                    "description": p.description,
                    "content": p.content,
                    "price": p.price,
                    "price_unit": p.price_unit,
                    "price_per_piece": p.price_per_piece,
                    "grams_per_piece": p.grams_per_piece,
                }
                for p in prods if p.price_per_piece is not None
            ]

        result = find_cheapest_combination(
            {"requirements": requirements, "total_pieces": pkg.total_pieces},
            products_by_cat,
            item.quantity,
        )
        result["package_name"] = pkg.name
        result["package_id"] = pkg.id
        results.append(result)

    return results


class PackageTypeIn(BaseModel):
    name: str
    total_pieces: float = 25
    requirements: list = []


@app.get("/api/package-types")
def list_package_types(db: Session = Depends(get_db)):
    pkgs = db.query(PackageType).all()
    cats = {c.id: c.name for c in db.query(FruitCategory).all()}
    result = []
    for pkg in pkgs:
        reqs = pkg.requirements or []
        for r in reqs:
            r["category_name"] = cats.get(r["category_id"], "?")
        result.append({
            "id": pkg.id,
            "name": pkg.name,
            "total_pieces": pkg.total_pieces,
            "requirements": reqs,
        })
    return result


@app.post("/api/package-types")
def create_package_type(body: PackageTypeIn, db: Session = Depends(get_db)):
    pkg = PackageType(name=body.name, total_pieces=body.total_pieces, requirements=body.requirements)
    db.add(pkg)
    db.commit()
    db.refresh(pkg)
    return {"id": pkg.id}


@app.put("/api/package-types/{pkg_id}")
def update_package_type(pkg_id: int, body: PackageTypeIn, db: Session = Depends(get_db)):
    pkg = db.query(PackageType).filter(PackageType.id == pkg_id).first()
    if not pkg:
        raise HTTPException(404)
    pkg.name = body.name
    pkg.total_pieces = body.total_pieces
    pkg.requirements = body.requirements
    db.commit()
    return {"ok": True}


@app.delete("/api/package-types/{pkg_id}")
def delete_package_type(pkg_id: int, db: Session = Depends(get_db)):
    pkg = db.query(PackageType).filter(PackageType.id == pkg_id).first()
    if not pkg:
        raise HTTPException(404)
    db.delete(pkg)
    db.commit()
    return {"ok": True}


class CategoryIn(BaseModel):
    name: str
    keywords: list = []


def _recategorize_active_products(db: Session):
    """Re-run keyword matching on all products in the active price list."""
    upload = db.query(PriceListUpload).filter(PriceListUpload.active == True).order_by(PriceListUpload.id.desc()).first()
    if not upload:
        return
    categories = db.query(FruitCategory).all()
    products = db.query(Product).filter(Product.price_list_id == upload.id).all()
    for p in products:
        desc_lower = p.description.lower()
        matched_cat = None
        for cat in categories:
            for kw in (cat.keywords or []):
                pattern = r'\b' + re.escape(kw.lower().strip())
                if re.search(pattern, desc_lower):
                    matched_cat = cat.id
                    break
            if matched_cat is not None:
                break
        p.category_id = matched_cat
        p.price_per_piece = estimate_price_per_piece({
            "price": p.price,
            "price_unit": p.price_unit,
            "content": p.content,
            "description": p.description,
            "grams_per_piece": p.grams_per_piece,
        })
    db.commit()


@app.get("/api/categories")
def list_categories(db: Session = Depends(get_db)):
    cats = db.query(FruitCategory).all()
    return [{"id": c.id, "name": c.name, "keywords": c.keywords} for c in cats]


@app.post("/api/categories")
def create_category(body: CategoryIn, db: Session = Depends(get_db)):
    cat = FruitCategory(name=body.name, keywords=body.keywords)
    db.add(cat)
    db.commit()
    db.refresh(cat)
    _recategorize_active_products(db)
    return {"id": cat.id}


@app.put("/api/categories/{cat_id}")
def update_category(cat_id: int, body: CategoryIn, db: Session = Depends(get_db)):
    cat = db.query(FruitCategory).filter(FruitCategory.id == cat_id).first()
    if not cat:
        raise HTTPException(404)
    cat.name = body.name
    cat.keywords = body.keywords
    db.commit()
    _recategorize_active_products(db)
    return {"ok": True}


@app.delete("/api/categories/{cat_id}")
def delete_category(cat_id: int, db: Session = Depends(get_db)):
    cat = db.query(FruitCategory).filter(FruitCategory.id == cat_id).first()
    if not cat:
        raise HTTPException(404)
    db.delete(cat)
    db.commit()
    _recategorize_active_products(db)
    return {"ok": True}


class ProductOverride(BaseModel):
    category_id: Optional[int] = None
    grams_per_piece: Optional[float] = None


@app.put("/api/products/{product_id}")
def update_product(product_id: int, body: ProductOverride, db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if not p:
        raise HTTPException(404)
    if body.category_id is not None:
        p.category_id = body.category_id
    if body.grams_per_piece is not None:
        p.grams_per_piece = body.grams_per_piece
    p.price_per_piece = estimate_price_per_piece({
        "price": p.price,
        "price_unit": p.price_unit,
        "content": p.content,
        "description": p.description,
        "grams_per_piece": p.grams_per_piece,
    })
    db.commit()
    return {"ok": True, "price_per_kg": p.price_per_piece}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
