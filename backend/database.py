from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, JSON, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

DATABASE_URL = "sqlite:///./rekentool.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class FruitCategory(Base):
    __tablename__ = "fruit_categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    keywords = Column(JSON, default=list)
    mappings = relationship("CategoryMapping", back_populates="category", cascade="all, delete-orphan")


class PackageType(Base):
    __tablename__ = "package_types"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    total_pieces = Column(Integer, default=100)
    requirements = Column(JSON, default=list)


class CategoryMapping(Base):
    __tablename__ = "category_mappings"
    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("fruit_categories.id"))
    category = relationship("FruitCategory", back_populates="mappings")
    product_keyword = Column(String, nullable=False)
    grams_per_piece = Column(Float, nullable=True)


class PriceListUpload(Base):
    __tablename__ = "price_list_uploads"
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    upload_date = Column(DateTime, default=datetime.utcnow)
    active = Column(Boolean, default=True)
    products = relationship("Product", back_populates="price_list", cascade="all, delete-orphan")


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    price_list_id = Column(Integer, ForeignKey("price_list_uploads.id"))
    price_list = relationship("PriceListUpload", back_populates="products")
    description = Column(String)
    content = Column(String)
    packaging = Column(String)
    price = Column(Float)
    price_unit = Column(String)
    category_id = Column(Integer, ForeignKey("fruit_categories.id"), nullable=True)
    grams_per_piece = Column(Float, nullable=True)
    price_per_piece = Column(Float, nullable=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    if db.query(FruitCategory).count() == 0:
        categories = [
            FruitCategory(name="Appels", keywords=["appels", "appel"]),
            FruitCategory(name="Peren", keywords=["peren", "peer"]),
            FruitCategory(name="Mandarijnen", keywords=["mandarijn", "mandarin", "clementine"]),
            FruitCategory(name="Bananen", keywords=["bananen", "banaan"]),
        ]
        db.add_all(categories)
        db.flush()

        pkg = PackageType(
            name="Standaard fruitpakket",
            total_pieces=100,
            requirements=[
                {"category_id": categories[0].id, "min_pct": 30, "max_pct": 40},
                {"category_id": categories[1].id, "min_pct": 20, "max_pct": 30},
                {"category_id": categories[2].id, "min_pct": 10, "max_pct": 20},
                {"category_id": categories[3].id, "min_pct": 0, "max_pct": 100},
            ],
        )
        db.add(pkg)
        db.commit()
    db.close()
