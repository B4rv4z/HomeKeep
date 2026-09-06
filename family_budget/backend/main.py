import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional

from fastapi import FastAPI, Depends, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.database import init_db, get_session, Expense, Income, Investment, Category, Member, RecurringExpense, KeywordMapping
from backend.bot import run_bot_in_thread
from backend.analytics import calculate_monthly_analytics, get_recent_expenses, calculate_advanced_analytics
from backend.parser import learn_category_from_correction, get_category_by_keywords

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
    source: str = "manual"  # 'manual' or 'file'
    transaction_date: Optional[str] = None  # ISO format: YYYY-MM-DD


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
    from datetime import date as date_type

    # Parse transaction_date if provided
    tx_date = None
    if expense.transaction_date:
        try:
            tx_date = date_type.fromisoformat(expense.transaction_date)
        except ValueError:
            pass  # Keep as None if parsing fails

    new_expense = Expense(
        amount=expense.amount,
        description=expense.description,
        category_id=expense.category_id,
        payer=expense.payer,
        is_fixed=expense.is_fixed,
        source=expense.source,
        transaction_date=tx_date
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


@app.delete("/api/expenses/bulk/by-source/{source}")
async def delete_expenses_by_source(source: str, db: Session = Depends(get_session)):
    """Delete all expenses with a specific source (e.g., 'file' or 'manual')."""
    expenses = db.exec(select(Expense).where(Expense.source == source)).all()
    count = len(expenses)
    for expense in expenses:
        db.delete(expense)
    db.commit()
    return {"status": "deleted", "source": source, "count": count}


@app.delete("/api/expenses/bulk/by-month")
async def delete_expenses_by_month(
    year: int = Query(...),
    month: int = Query(...),
    db: Session = Depends(get_session)
):
    """Delete all expenses for a specific month."""
    all_expenses = db.exec(select(Expense)).all()
    month_expenses = [
        exp for exp in all_expenses
        if exp.created_at.year == year and exp.created_at.month == month
    ]
    count = len(month_expenses)
    for expense in month_expenses:
        db.delete(expense)
    db.commit()
    return {"status": "deleted", "year": year, "month": month, "count": count}


class ExpenseUpdate(BaseModel):
    category_id: Optional[int] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    transaction_date: Optional[str] = None  # ISO format: YYYY-MM-DD


@app.patch("/api/expenses/{expense_id}")
async def update_expense(
    expense_id: int,
    updates: ExpenseUpdate,
    db: Session = Depends(get_session)
):
    """Update an expense (category, description, amount, or transaction_date).

    When category is changed, the system learns from this correction
    by saving keywords from the description to KeywordMapping.
    This enables automatic categorization of similar expenses in the future.
    """
    from datetime import date as date_type

    expense = db.get(Expense, expense_id)
    if not expense:
        return {"error": "Expense not found"}

    # Track if category is being changed (for learning)
    old_category_id = expense.category_id
    category_changed = False
    learning_result = None

    if updates.category_id is not None:
        if updates.category_id != old_category_id:
            category_changed = True
        expense.category_id = updates.category_id
    if updates.description is not None:
        expense.description = updates.description
    if updates.amount is not None:
        expense.amount = updates.amount
    if updates.transaction_date is not None:
        try:
            expense.transaction_date = date_type.fromisoformat(updates.transaction_date)
        except ValueError:
            pass

    db.add(expense)
    db.commit()
    db.refresh(expense)

    # Learn from category correction
    if category_changed and expense.description:
        learning_result = learn_category_from_correction(
            expense.description,
            expense.category_id
        )
        logger.info(f"Learned from correction: {learning_result}")

    # Return with category name
    cat = db.get(Category, expense.category_id)
    response = {
        "id": expense.id,
        "amount": expense.amount,
        "description": expense.description,
        "category_id": expense.category_id,
        "category": cat.name if cat else "Unknown",
        "payer": expense.payer,
        "created_at": expense.created_at.isoformat(),
        "transaction_date": expense.transaction_date.isoformat() if expense.transaction_date else None
    }

    # Include learning info if category was changed
    if learning_result:
        response["learned"] = learning_result

    return response


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


@app.delete("/api/categories/{category_id}")
async def delete_category(category_id: int, db: Session = Depends(get_session)):
    """Delete a category (only if no expenses use it)."""
    category = db.get(Category, category_id)
    if not category:
        return {"error": "Category not found"}

    # Check if any expenses use this category
    expenses_count = len(db.exec(
        select(Expense).where(Expense.category_id == category_id)
    ).all())

    if expenses_count > 0:
        return {"error": f"Cannot delete: {expenses_count} expenses use this category"}

    db.delete(category)
    db.commit()
    return {"status": "deleted", "id": category_id}


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


@app.get("/api/analytics/advanced")
async def get_advanced_analytics(
    year: Optional[int] = Query(default=None),
    month: Optional[int] = Query(default=None)
):
    """
    Get advanced analytics including:
    - Potential duplicate charges
    - Top merchants/stores by spending
    - Spending patterns by day of week
    - Expense size distribution
    """
    now = datetime.now()
    target_year = year if year is not None else now.year
    target_month = month if month is not None else now.month
    return calculate_advanced_analytics(target_year, target_month)


@app.get("/api/analytics/comparison")
async def get_monthly_comparison(
    months: int = Query(default=6, le=12),
    db: Session = Depends(get_session)
):
    """
    Get monthly comparison data for the last N months.
    Returns spending by category for each month.
    """
    from datetime import datetime
    from dateutil.relativedelta import relativedelta

    now = datetime.now()
    result = []

    for i in range(months - 1, -1, -1):
        target_date = now - relativedelta(months=i)
        year, month = target_date.year, target_date.month

        # Get expenses for this month
        all_expenses = db.exec(select(Expense)).all()
        month_expenses = [
            exp for exp in all_expenses
            if exp.created_at.year == year and exp.created_at.month == month
        ]

        # Get recurring expenses
        all_recurring = db.exec(
            select(RecurringExpense).where(RecurringExpense.is_active == True)
        ).all()

        # Calculate by category
        categories_data = db.exec(select(Category)).all()
        category_totals = {}

        for cat in categories_data:
            cat_expenses = [exp for exp in month_expenses if exp.category_id == cat.id]
            spent = sum(exp.amount for exp in cat_expenses)
            # Add recurring for this category
            cat_recurring = [r for r in all_recurring if r.category_id == cat.id and r.frequency == "monthly"]
            spent += sum(r.amount for r in cat_recurring)
            category_totals[cat.name] = spent

        total_spent = sum(category_totals.values())

        # Get income for this month
        all_incomes = db.exec(select(Income)).all()
        month_income = sum(
            inc.amount for inc in all_incomes
            if inc.received_date.year == year and inc.received_date.month == month
        )

        result.append({
            "year": year,
            "month": month,
            "period": f"{year}-{month:02d}",
            "period_label": target_date.strftime("%b %Y"),
            "total_spent": total_spent,
            "total_income": month_income,
            "categories": category_totals
        })

    return result


def get_expense_effective_date(exp):
    """Get the effective date for filtering - transaction_date if available, else created_at."""
    if exp.transaction_date:
        return exp.transaction_date
    return exp.created_at.date()


@app.get("/api/expenses/by-month")
async def get_expenses_by_month(
    year: int = Query(...),
    month: int = Query(...),
    db: Session = Depends(get_session)
):
    """Get all expenses for a specific month with category names.
    Uses transaction_date for filtering if available, otherwise created_at.
    """
    all_expenses = db.exec(
        select(Expense).order_by(Expense.created_at.desc())
    ).all()

    month_expenses = []
    for exp in all_expenses:
        effective_date = get_expense_effective_date(exp)
        if effective_date.year == year and effective_date.month == month:
            month_expenses.append(exp)

    result = []
    for exp in month_expenses:
        cat = db.get(Category, exp.category_id)
        result.append({
            "id": exp.id,
            "amount": exp.amount,
            "description": exp.description,
            "category_id": exp.category_id,
            "category": cat.name if cat else "Unknown",
            "payer": exp.payer,
            "created_at": exp.created_at.isoformat(),
            "transaction_date": exp.transaction_date.isoformat() if exp.transaction_date else None,
            "is_fixed": exp.is_fixed,
            "source": exp.source
        })

    return result


# ============ Members Endpoint ============

@app.get("/api/members")
async def get_members(db: Session = Depends(get_session)):
    """Get all family members."""
    members = db.exec(select(Member)).all()
    return members


# ============ Recurring Expenses Endpoints ============

class RecurringExpenseCreate(BaseModel):
    name: str
    amount: float
    category_id: int
    frequency: str = "monthly"  # 'monthly' or 'one_time'
    day_of_month: int = 1
    notes: Optional[str] = None


class RecurringExpenseUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = None
    category_id: Optional[int] = None
    frequency: Optional[str] = None
    day_of_month: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


@app.get("/api/recurring")
async def get_recurring_expenses(db: Session = Depends(get_session)):
    """Get all recurring expenses with category names."""
    recurring = db.exec(select(RecurringExpense).order_by(RecurringExpense.name)).all()
    result = []
    for r in recurring:
        cat = db.get(Category, r.category_id)
        result.append({
            "id": r.id,
            "name": r.name,
            "amount": r.amount,
            "category_id": r.category_id,
            "category": cat.name if cat else "Unknown",
            "frequency": r.frequency,
            "day_of_month": r.day_of_month,
            "is_active": r.is_active,
            "notes": r.notes
        })
    return result


@app.post("/api/recurring")
async def create_recurring_expense(
    expense: RecurringExpenseCreate,
    db: Session = Depends(get_session)
):
    """Create a new recurring expense."""
    new_recurring = RecurringExpense(
        name=expense.name,
        amount=expense.amount,
        category_id=expense.category_id,
        frequency=expense.frequency,
        day_of_month=expense.day_of_month,
        notes=expense.notes
    )
    db.add(new_recurring)
    db.commit()
    db.refresh(new_recurring)
    return new_recurring


@app.patch("/api/recurring/{recurring_id}")
async def update_recurring_expense(
    recurring_id: int,
    updates: RecurringExpenseUpdate,
    db: Session = Depends(get_session)
):
    """Update a recurring expense."""
    recurring = db.get(RecurringExpense, recurring_id)
    if not recurring:
        return {"error": "Recurring expense not found"}

    if updates.name is not None:
        recurring.name = updates.name
    if updates.amount is not None:
        recurring.amount = updates.amount
    if updates.category_id is not None:
        recurring.category_id = updates.category_id
    if updates.frequency is not None:
        recurring.frequency = updates.frequency
    if updates.day_of_month is not None:
        recurring.day_of_month = updates.day_of_month
    if updates.is_active is not None:
        recurring.is_active = updates.is_active
    if updates.notes is not None:
        recurring.notes = updates.notes

    db.add(recurring)
    db.commit()
    db.refresh(recurring)
    return recurring


@app.delete("/api/recurring/{recurring_id}")
async def delete_recurring_expense(recurring_id: int, db: Session = Depends(get_session)):
    """Delete a recurring expense."""
    recurring = db.get(RecurringExpense, recurring_id)
    if not recurring:
        return {"error": "Recurring expense not found"}
    db.delete(recurring)
    db.commit()
    return {"status": "deleted", "id": recurring_id}


# ============ Keyword Mapping Endpoints (Learning System) ============

@app.get("/api/keywords")
async def get_keyword_mappings(db: Session = Depends(get_session)):
    """Get all learned keyword-to-category mappings.

    The system learns from user category corrections. When a user changes
    the category of an expense, keywords from the description are saved here.
    Future imports will automatically use these mappings.
    """
    mappings = db.exec(
        select(KeywordMapping).order_by(KeywordMapping.keyword)
    ).all()

    result = []
    for mapping in mappings:
        cat = db.get(Category, mapping.category_id)
        result.append({
            "id": mapping.id,
            "keyword": mapping.keyword,
            "category_id": mapping.category_id,
            "category": cat.name if cat else "Unknown"
        })
    return result


@app.get("/api/keywords/stats")
async def get_keyword_stats(db: Session = Depends(get_session)):
    """Get statistics about learned keywords."""
    mappings = db.exec(select(KeywordMapping)).all()
    categories = db.exec(select(Category)).all()

    # Count keywords per category
    cat_counts = {}
    for mapping in mappings:
        cat = db.get(Category, mapping.category_id)
        cat_name = cat.name if cat else "Unknown"
        cat_counts[cat_name] = cat_counts.get(cat_name, 0) + 1

    return {
        "total_keywords": len(mappings),
        "keywords_by_category": cat_counts
    }


class KeywordCreate(BaseModel):
    keyword: str
    category_id: int


@app.post("/api/keywords")
async def create_keyword_mapping(
    mapping: KeywordCreate,
    db: Session = Depends(get_session)
):
    """Manually add a keyword-to-category mapping."""
    # Check if keyword already exists
    existing = db.exec(
        select(KeywordMapping).where(KeywordMapping.keyword == mapping.keyword.lower())
    ).first()

    if existing:
        # Update existing
        existing.category_id = mapping.category_id
        db.add(existing)
        db.commit()
        db.refresh(existing)
        cat = db.get(Category, existing.category_id)
        return {
            "id": existing.id,
            "keyword": existing.keyword,
            "category_id": existing.category_id,
            "category": cat.name if cat else "Unknown",
            "action": "updated"
        }

    # Create new
    new_mapping = KeywordMapping(
        keyword=mapping.keyword.lower(),
        category_id=mapping.category_id
    )
    db.add(new_mapping)
    db.commit()
    db.refresh(new_mapping)
    cat = db.get(Category, new_mapping.category_id)
    return {
        "id": new_mapping.id,
        "keyword": new_mapping.keyword,
        "category_id": new_mapping.category_id,
        "category": cat.name if cat else "Unknown",
        "action": "created"
    }


@app.delete("/api/keywords/{keyword_id}")
async def delete_keyword_mapping(keyword_id: int, db: Session = Depends(get_session)):
    """Delete a keyword mapping."""
    mapping = db.get(KeywordMapping, keyword_id)
    if not mapping:
        return {"error": "Keyword mapping not found"}
    keyword = mapping.keyword
    db.delete(mapping)
    db.commit()
    return {"status": "deleted", "id": keyword_id, "keyword": keyword}


@app.delete("/api/keywords/bulk/all")
async def delete_all_keyword_mappings(db: Session = Depends(get_session)):
    """Delete all learned keyword mappings (reset learning)."""
    mappings = db.exec(select(KeywordMapping)).all()
    count = len(mappings)
    for mapping in mappings:
        db.delete(mapping)
    db.commit()
    return {"status": "deleted", "count": count}
