import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Depends, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.database import init_db, get_session, Expense, Income, Investment, Category, Member
from backend.bot import run_bot_in_thread
from backend.analytics import calculate_monthly_analytics, get_recent_expenses

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Pydantic models for request/response
class ExpenseCreate(BaseModel):
    amount: float
    description: str
    category_id: int
    payer: Optional[str] = "Dashboard"
    is_fixed: bool = False


class IncomeCreate(BaseModel):
    member_id: int = 1
    amount: float
    income_type: str = "salary"
    received_date: str  # ISO format: YYYY-MM-DD
    notes: Optional[str] = None


class InvestmentCreate(BaseModel):
    target_name: str
    amount: float
    transaction_date: str  # ISO format: YYYY-MM-DD
    notes: Optional[str] = None


class CategoryCreate(BaseModel):
    name: str
    type: str = "variable"
    monthly_budget: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager - startup and shutdown."""
    # Startup
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized.")

    logger.info("Starting Telegram bot worker...")
    run_bot_in_thread()

    yield

    # Shutdown
    logger.info("Application shutting down...")


app = FastAPI(
    title="Family Budget Tracker",
    description="Local-first family finance management with Telegram bot",
    version="1.0.0",
    lifespan=lifespan
)

# Mount frontend static files
app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/")
async def serve_dashboard():
    """Serve the main dashboard HTML."""
    return FileResponse("frontend/index.html")


# ============ Expense Endpoints ============

@app.get("/api/expenses")
async def get_expenses(
    limit: int = Query(default=100, le=500),
    db: Session = Depends(get_session)
):
    """Get recent expenses."""
    expenses = db.exec(
        select(Expense).order_by(Expense.created_at.desc()).limit(limit)
    ).all()
    return expenses


@app.post("/api/expenses")
async def create_expense(expense: ExpenseCreate, db: Session = Depends(get_session)):
    """Create a new expense entry."""
    new_expense = Expense(
        amount=expense.amount,
        description=expense.description,
        category_id=expense.category_id,
        payer=expense.payer,
        is_fixed=expense.is_fixed
    )
    db.add(new_expense)
    db.commit()
    db.refresh(new_expense)
    return new_expense


@app.delete("/api/expenses/{expense_id}")
async def delete_expense(expense_id: int, db: Session = Depends(get_session)):
    """Delete an expense by ID."""
    expense = db.get(Expense, expense_id)
    if not expense:
        return {"error": "Expense not found"}
    db.delete(expense)
    db.commit()
    return {"status": "deleted", "id": expense_id}


class ExpenseUpdate(BaseModel):
    category_id: Optional[int] = None
    description: Optional[str] = None
    amount: Optional[float] = None


@app.patch("/api/expenses/{expense_id}")
async def update_expense(
    expense_id: int,
    updates: ExpenseUpdate,
    db: Session = Depends(get_session)
):
    """Update an expense (category, description, or amount)."""
    expense = db.get(Expense, expense_id)
    if not expense:
        return {"error": "Expense not found"}

    if updates.category_id is not None:
        expense.category_id = updates.category_id
    if updates.description is not None:
        expense.description = updates.description
    if updates.amount is not None:
        expense.amount = updates.amount

    db.add(expense)
    db.commit()
    db.refresh(expense)

    # Return with category name
    cat = db.get(Category, expense.category_id)
    return {
        "id": expense.id,
        "amount": expense.amount,
        "description": expense.description,
        "category_id": expense.category_id,
        "category": cat.name if cat else "Unknown",
        "payer": expense.payer,
        "created_at": expense.created_at.isoformat()
    }


# ============ Income Endpoints ============

@app.get("/api/incomes")
async def get_incomes(db: Session = Depends(get_session)):
    """Get all income records."""
    incomes = db.exec(select(Income).order_by(Income.received_date.desc())).all()
    return incomes


@app.post("/api/incomes")
async def create_income(income: IncomeCreate, db: Session = Depends(get_session)):
    """Create a new income entry."""
    from datetime import date
    new_income = Income(
        member_id=income.member_id,
        amount=income.amount,
        income_type=income.income_type,
        received_date=date.fromisoformat(income.received_date),
        notes=income.notes
    )
    db.add(new_income)
    db.commit()
    db.refresh(new_income)
    return new_income


@app.delete("/api/incomes/{income_id}")
async def delete_income(income_id: int, db: Session = Depends(get_session)):
    """Delete an income record by ID."""
    income = db.get(Income, income_id)
    if not income:
        return {"error": "Income not found"}
    db.delete(income)
    db.commit()
    return {"status": "deleted", "id": income_id}


# ============ Investment Endpoints ============

@app.get("/api/investments")
async def get_investments(db: Session = Depends(get_session)):
    """Get all investment records."""
    investments = db.exec(
        select(Investment).order_by(Investment.transaction_date.desc())
    ).all()
    return investments


@app.post("/api/investments")
async def create_investment(
    investment: InvestmentCreate,
    db: Session = Depends(get_session)
):
    """Create a new investment entry."""
    from datetime import date
    new_investment = Investment(
        target_name=investment.target_name,
        amount=investment.amount,
        transaction_date=date.fromisoformat(investment.transaction_date),
        notes=investment.notes
    )
    db.add(new_investment)
    db.commit()
    db.refresh(new_investment)
    return new_investment


@app.delete("/api/investments/{investment_id}")
async def delete_investment(investment_id: int, db: Session = Depends(get_session)):
    """Delete an investment record by ID."""
    investment = db.get(Investment, investment_id)
    if not investment:
        return {"error": "Investment not found"}
    db.delete(investment)
    db.commit()
    return {"status": "deleted", "id": investment_id}


# ============ Category Endpoints ============

@app.get("/api/categories")
async def get_categories(db: Session = Depends(get_session)):
    """Get all expense categories."""
    categories = db.exec(select(Category)).all()
    return categories


@app.post("/api/categories")
async def create_category(category: CategoryCreate, db: Session = Depends(get_session)):
    """Create a new category."""
    new_category = Category(
        name=category.name,
        type=category.type,
        monthly_budget=category.monthly_budget
    )
    db.add(new_category)
    db.commit()
    db.refresh(new_category)
    return new_category


@app.put("/api/categories/{category_id}")
async def update_category(
    category_id: int,
    category: CategoryCreate,
    db: Session = Depends(get_session)
):
    """Update a category's budget or details."""
    existing = db.get(Category, category_id)
    if not existing:
        return {"error": "Category not found"}
    existing.name = category.name
    existing.type = category.type
    existing.monthly_budget = category.monthly_budget
    db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing


# ============ Analytics Endpoints ============

@app.get("/api/analytics/monthly")
async def get_monthly_analytics(
    year: Optional[int] = Query(default=None),
    month: Optional[int] = Query(default=None)
):
    """
    Get monthly analytics including totals, category breakdown, and insights.
    Defaults to current month if not specified.
    """
    now = datetime.now()
    target_year = year if year is not None else now.year
    target_month = month if month is not None else now.month
    return calculate_monthly_analytics(target_year, target_month)


@app.get("/api/analytics/recent")
async def get_recent_expenses_api(limit: int = Query(default=10, le=50)):
    """Get recent expenses with category names."""
    return get_recent_expenses(limit)


# ============ Members Endpoint ============

@app.get("/api/members")
async def get_members(db: Session = Depends(get_session)):
    """Get all family members."""
    members = db.exec(select(Member)).all()
    return members
