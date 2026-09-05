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
    source: str = Field(default="manual")  # 'manual' or 'file'


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
                Category(name="מזון וצרכנות", type="variable", monthly_budget=4500.0),
                Category(name="הוצאות רכב", type="variable", monthly_budget=1200.0),
                Category(name="מסעדות ואוכל בחוץ", type="variable", monthly_budget=1500.0),
                Category(name="ילדים וחינוך", type="variable", monthly_budget=1500.0),
                Category(name="פנאי ובילוי", type="variable", monthly_budget=1000.0),
                Category(name="דיור וחשבונות", type="fixed", monthly_budget=6000.0),
                Category(name="ביטוח ובריאות", type="fixed", monthly_budget=1200.0),
                Category(name="קניות אינטרנט", type="variable", monthly_budget=1500.0),
                Category(name="מנויים ושירותים", type="fixed", monthly_budget=500.0),
                Category(name="כללי ושונות", type="variable", monthly_budget=1000.0),
            ]
            session.add_all(categories)
            session.commit()

            # Seed default keyword mappings
            cat_map = {c.name: c.id for c in session.exec(select(Category)).all()}
            mappings = [
                # Groceries / מזון וצרכנות
                KeywordMapping(keyword="supermarket", category_id=cat_map["מזון וצרכנות"]),
                KeywordMapping(keyword="groceries", category_id=cat_map["מזון וצרכנות"]),
                KeywordMapping(keyword="shufersal", category_id=cat_map["מזון וצרכנות"]),
                KeywordMapping(keyword="rami levy", category_id=cat_map["מזון וצרכנות"]),
                KeywordMapping(keyword="mega", category_id=cat_map["מזון וצרכנות"]),
                KeywordMapping(keyword="שופרסל", category_id=cat_map["מזון וצרכנות"]),
                KeywordMapping(keyword="רמי לוי", category_id=cat_map["מזון וצרכנות"]),
                KeywordMapping(keyword="ירקות", category_id=cat_map["מזון וצרכנות"]),
                KeywordMapping(keyword="בשר", category_id=cat_map["מזון וצרכנות"]),
                KeywordMapping(keyword="אטליז", category_id=cat_map["מזון וצרכנות"]),
                # Car expenses / הוצאות רכב
                KeywordMapping(keyword="fuel", category_id=cat_map["הוצאות רכב"]),
                KeywordMapping(keyword="gas", category_id=cat_map["הוצאות רכב"]),
                KeywordMapping(keyword="charging", category_id=cat_map["הוצאות רכב"]),
                KeywordMapping(keyword="parking", category_id=cat_map["הוצאות רכב"]),
                KeywordMapping(keyword="sonol", category_id=cat_map["הוצאות רכב"]),
                KeywordMapping(keyword="paz", category_id=cat_map["הוצאות רכב"]),
                KeywordMapping(keyword="דלק", category_id=cat_map["הוצאות רכב"]),
                KeywordMapping(keyword="חניה", category_id=cat_map["הוצאות רכב"]),
                KeywordMapping(keyword="טעינה", category_id=cat_map["הוצאות רכב"]),
                # Restaurants / מסעדות ואוכל בחוץ
                KeywordMapping(keyword="coffee", category_id=cat_map["מסעדות ואוכל בחוץ"]),
                KeywordMapping(keyword="restaurant", category_id=cat_map["מסעדות ואוכל בחוץ"]),
                KeywordMapping(keyword="wolt", category_id=cat_map["מסעדות ואוכל בחוץ"]),
                KeywordMapping(keyword="cafe", category_id=cat_map["מסעדות ואוכל בחוץ"]),
                KeywordMapping(keyword="pizza", category_id=cat_map["מסעדות ואוכל בחוץ"]),
                KeywordMapping(keyword="קפה", category_id=cat_map["מסעדות ואוכל בחוץ"]),
                KeywordMapping(keyword="מסעדה", category_id=cat_map["מסעדות ואוכל בחוץ"]),
                KeywordMapping(keyword="פיצה", category_id=cat_map["מסעדות ואוכל בחוץ"]),
                # Leisure & Entertainment / פנאי ובילוי
                KeywordMapping(keyword="cinema", category_id=cat_map["פנאי ובילוי"]),
                KeywordMapping(keyword="movie", category_id=cat_map["פנאי ובילוי"]),
                KeywordMapping(keyword="theater", category_id=cat_map["פנאי ובילוי"]),
                KeywordMapping(keyword="concert", category_id=cat_map["פנאי ובילוי"]),
                KeywordMapping(keyword="museum", category_id=cat_map["פנאי ובילוי"]),
                KeywordMapping(keyword="gym", category_id=cat_map["פנאי ובילוי"]),
                KeywordMapping(keyword="spa", category_id=cat_map["פנאי ובילוי"]),
                KeywordMapping(keyword="קולנוע", category_id=cat_map["פנאי ובילוי"]),
                KeywordMapping(keyword="סרט", category_id=cat_map["פנאי ובילוי"]),
                KeywordMapping(keyword="תיאטרון", category_id=cat_map["פנאי ובילוי"]),
                KeywordMapping(keyword="הופעה", category_id=cat_map["פנאי ובילוי"]),
                KeywordMapping(keyword="מוזיאון", category_id=cat_map["פנאי ובילוי"]),
                KeywordMapping(keyword="חדר כושר", category_id=cat_map["פנאי ובילוי"]),
                KeywordMapping(keyword="ספא", category_id=cat_map["פנאי ובילוי"]),
                KeywordMapping(keyword="בילוי", category_id=cat_map["פנאי ובילוי"]),
                # E-commerce & Shopping / קניות אינטרנט
                KeywordMapping(keyword="amazon", category_id=cat_map["קניות אינטרנט"]),
                KeywordMapping(keyword="aliexpress", category_id=cat_map["קניות אינטרנט"]),
                KeywordMapping(keyword="shein", category_id=cat_map["קניות אינטרנט"]),
                KeywordMapping(keyword="asos", category_id=cat_map["קניות אינטרנט"]),
                KeywordMapping(keyword="zara", category_id=cat_map["קניות אינטרנט"]),
                KeywordMapping(keyword="h&m", category_id=cat_map["קניות אינטרנט"]),
                KeywordMapping(keyword="terminalx", category_id=cat_map["קניות אינטרנט"]),
                KeywordMapping(keyword="ksp", category_id=cat_map["קניות אינטרנט"]),
                KeywordMapping(keyword="ivory", category_id=cat_map["קניות אינטרנט"]),
                KeywordMapping(keyword="בגדים", category_id=cat_map["קניות אינטרנט"]),
                KeywordMapping(keyword="הנעלה", category_id=cat_map["קניות אינטרנט"]),
                KeywordMapping(keyword="נעליים", category_id=cat_map["קניות אינטרנט"]),
                # Subscriptions / מנויים ושירותים
                KeywordMapping(keyword="netflix", category_id=cat_map["מנויים ושירותים"]),
                KeywordMapping(keyword="spotify", category_id=cat_map["מנויים ושירותים"]),
                KeywordMapping(keyword="apple", category_id=cat_map["מנויים ושירותים"]),
                KeywordMapping(keyword="google", category_id=cat_map["מנויים ושירותים"]),
                KeywordMapping(keyword="disney", category_id=cat_map["מנויים ושירותים"]),
                KeywordMapping(keyword="hbo", category_id=cat_map["מנויים ושירותים"]),
                KeywordMapping(keyword="yes", category_id=cat_map["מנויים ושירותים"]),
                KeywordMapping(keyword="hot", category_id=cat_map["מנויים ושירותים"]),
                KeywordMapping(keyword="cellcom", category_id=cat_map["מנויים ושירותים"]),
                KeywordMapping(keyword="partner", category_id=cat_map["מנויים ושירותים"]),
                KeywordMapping(keyword="pelephone", category_id=cat_map["מנויים ושירותים"]),
                KeywordMapping(keyword="מנוי", category_id=cat_map["מנויים ושירותים"]),
                KeywordMapping(keyword="סלולר", category_id=cat_map["מנויים ושירותים"]),
            ]
            session.add_all(mappings)
            session.commit()


def get_session():
    """Dependency for FastAPI routes."""
    with Session(engine) as session:
        yield session
