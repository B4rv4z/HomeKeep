import os
from datetime import datetime, date
from typing import Optional
from sqlmodel import Field, SQLModel, Session, create_engine, select

DATA_PATH = os.getenv("DATA_PATH", "./data")
os.makedirs(DATA_PATH, exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(DATA_PATH, 'family_budget.db')}")

engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})


class Member(SQLModel, table=True):
    __tablename__ = "members"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)


class Category(SQLModel, table=True):
    __tablename__ = "categories"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    type: str = Field(default="variable")  # 'fixed' or 'variable'
    monthly_budget: float = Field(default=0.0)


class KeywordMapping(SQLModel, table=True):
    __tablename__ = "keyword_mappings"
    id: Optional[int] = Field(default=None, primary_key=True)
    keyword: str = Field(unique=True, index=True)
    category_id: int = Field(foreign_key="categories.id")


class Expense(SQLModel, table=True):
    __tablename__ = "expenses"
    id: Optional[int] = Field(default=None, primary_key=True)
    amount: float
    description: str
    category_id: int = Field(foreign_key="categories.id", index=True)
    payer: Optional[str] = Field(default="Unknown")
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    is_fixed: bool = Field(default=False)


class Income(SQLModel, table=True):
    __tablename__ = "incomes"
    id: Optional[int] = Field(default=None, primary_key=True)
    member_id: int = Field(foreign_key="members.id", index=True)
    amount: float
    income_type: str = Field(default="salary")  # 'salary', 'bonus', 'extra'
    received_date: date = Field(default_factory=date.today)
    notes: Optional[str] = None


class Investment(SQLModel, table=True):
    __tablename__ = "investments"
    id: Optional[int] = Field(default=None, primary_key=True)
    target_name: str = Field(index=True)
    amount: float
    transaction_date: date = Field(default_factory=date.today)
    notes: Optional[str] = None


class RecurringExpense(SQLModel, table=True):
    """Recurring expenses like mortgage, insurance, subscriptions."""
    __tablename__ = "recurring_expenses"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    amount: float
    category_id: int = Field(foreign_key="categories.id", index=True)
    frequency: str = Field(default="monthly")  # 'monthly' or 'one_time'
    day_of_month: int = Field(default=1)  # Day when payment is due
    is_active: bool = Field(default=True)
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


def init_db():
    """Initialize database tables and seed default data."""
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        # Seed default member if empty
        if not session.exec(select(Member)).first():
            session.add(Member(name="Family"))
            session.commit()

        # Seed default categories if empty
        if not session.exec(select(Category)).first():
            categories = [
                Category(name="Groceries & Supermarket", type="variable", monthly_budget=4500.0),
                Category(name="Transportation & Fuel", type="variable", monthly_budget=1200.0),
                Category(name="Restaurants & Dining", type="variable", monthly_budget=1500.0),
                Category(name="Kids & Education", type="variable", monthly_budget=1500.0),
                Category(name="Housing & Utilities", type="fixed", monthly_budget=6000.0),
                Category(name="Insurance & Health", type="fixed", monthly_budget=1200.0),
                Category(name="General & Miscellaneous", type="variable", monthly_budget=1000.0),
            ]
            session.add_all(categories)
            session.commit()

            # Seed default keyword mappings
            cat_map = {c.name: c.id for c in session.exec(select(Category)).all()}
            mappings = [
                # Groceries
                KeywordMapping(keyword="supermarket", category_id=cat_map["Groceries & Supermarket"]),
                KeywordMapping(keyword="groceries", category_id=cat_map["Groceries & Supermarket"]),
                KeywordMapping(keyword="shufersal", category_id=cat_map["Groceries & Supermarket"]),
                KeywordMapping(keyword="rami levy", category_id=cat_map["Groceries & Supermarket"]),
                KeywordMapping(keyword="mega", category_id=cat_map["Groceries & Supermarket"]),
                # Transportation
                KeywordMapping(keyword="fuel", category_id=cat_map["Transportation & Fuel"]),
                KeywordMapping(keyword="gas", category_id=cat_map["Transportation & Fuel"]),
                KeywordMapping(keyword="charging", category_id=cat_map["Transportation & Fuel"]),
                KeywordMapping(keyword="parking", category_id=cat_map["Transportation & Fuel"]),
                KeywordMapping(keyword="sonol", category_id=cat_map["Transportation & Fuel"]),
                KeywordMapping(keyword="paz", category_id=cat_map["Transportation & Fuel"]),
                # Restaurants
                KeywordMapping(keyword="coffee", category_id=cat_map["Restaurants & Dining"]),
                KeywordMapping(keyword="restaurant", category_id=cat_map["Restaurants & Dining"]),
                KeywordMapping(keyword="wolt", category_id=cat_map["Restaurants & Dining"]),
                KeywordMapping(keyword="cafe", category_id=cat_map["Restaurants & Dining"]),
                KeywordMapping(keyword="pizza", category_id=cat_map["Restaurants & Dining"]),
            ]
            session.add_all(mappings)
            session.commit()


def get_session():
    """Dependency for FastAPI routes."""
    with Session(engine) as session:
        yield session
