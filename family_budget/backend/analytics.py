from datetime import datetime
from typing import Dict, Any, List
from sqlmodel import Session, select
from backend.database import engine, Expense, Income, Investment, Category, RecurringExpense


def calculate_monthly_analytics(year: int, month: int) -> Dict[str, Any]:
    """
    Calculate comprehensive monthly financial analytics.

    Args:
        year: Target year (e.g., 2024)
        month: Target month (1-12)

    Returns:
        Dictionary containing totals, category breakdown, alerts, and insights
    """
    with Session(engine) as session:
        # 1. Total Incomes for target month
        all_incomes = session.exec(select(Income)).all()
        month_incomes = [
            inc for inc in all_incomes
            if inc.received_date.year == year and inc.received_date.month == month
        ]
        total_salary = sum(inc.amount for inc in month_incomes if inc.income_type == "salary")
        total_bonus = sum(inc.amount for inc in month_incomes if inc.income_type == "bonus")
        total_extra = sum(inc.amount for inc in month_incomes if inc.income_type == "extra")
        total_income = total_salary + total_bonus + total_extra

        # 2. Total Investments for target month
        all_investments = session.exec(select(Investment)).all()
        month_investments = [
            inv for inv in all_investments
            if inv.transaction_date.year == year and inv.transaction_date.month == month
        ]
        total_invested = sum(inv.amount for inv in month_investments)

        # 3. Total Expenses per Category for target month
        all_expenses = session.exec(select(Expense)).all()
        month_expenses = [
            exp for exp in all_expenses
            if exp.created_at.year == year and exp.created_at.month == month
        ]
        total_spent = sum(exp.amount for exp in month_expenses)

        # 3b. Add recurring expenses (monthly ones always, one_time check if applicable)
        all_recurring = session.exec(
            select(RecurringExpense).where(RecurringExpense.is_active == True)
        ).all()
        total_recurring = sum(
            r.amount for r in all_recurring if r.frequency == "monthly"
        )
        total_spent += total_recurring

        # 4. Breakdown by category
        categories = session.exec(select(Category)).all()
        category_breakdown: List[Dict[str, Any]] = []
        alerts: List[str] = []

        for cat in categories:
            cat_expenses = [exp for exp in month_expenses if exp.category_id == cat.id]
            spent = sum(exp.amount for exp in cat_expenses)
            # Add recurring expenses for this category
            cat_recurring = [r for r in all_recurring if r.category_id == cat.id and r.frequency == "monthly"]
            spent += sum(r.amount for r in cat_recurring)
            budget = cat.monthly_budget or 0.0
            diff = budget - spent
            pct_used = (spent / budget * 100) if budget > 0 else 0.0

            category_breakdown.append({
                "category_id": cat.id,
                "name": cat.name,
                "type": cat.type,
                "spent": round(spent, 2),
                "budget": round(budget, 2),
                "percent_used": round(pct_used, 1),
                "remaining": round(diff, 2)
            })

            # Threshold Alert (Exceeding Budget)
            if budget > 0 and spent > budget:
                alerts.append(
                    f"Over budget in '{cat.name}': Spent {spent:,.0f} of {budget:,.0f} ({pct_used:.0f}%)."
                )
            elif budget > 0 and pct_used >= 80:
                alerts.append(
                    f"Approaching budget limit in '{cat.name}': {pct_used:.0f}% used."
                )

        # 5. Savings Rate Computation
        savings_rate = (total_invested / total_income * 100) if total_income > 0 else 0.0

        # 6. Generate Insights & Recommendations
        insights: List[str] = []
        if total_income > 0:
            insights.append(f"Monthly Savings/Investment Rate: {savings_rate:.1f}%.")
            if savings_rate < 20.0:
                insights.append("Recommendation: Target a minimum 20% savings & investment rate.")
            else:
                insights.append("Healthy savings discipline maintained this month.")

        if total_bonus > 0:
            if total_invested >= (total_bonus * 0.5):
                insights.append("Bonus allocation verified: 50%+ of bonus deployed into investments.")
            else:
                insights.append(
                    "Bonus notice: Consider allocating a higher portion of this month's bonus "
                    "into investment accounts."
                )

        # Net balance (income - expenses - investments)
        net_balance = total_income - (total_spent + total_invested)

        return {
            "period": f"{year}-{month:02d}",
            "totals": {
                "income": round(total_income, 2),
                "salary": round(total_salary, 2),
                "bonus": round(total_bonus, 2),
                "extra": round(total_extra, 2),
                "spent": round(total_spent, 2),
                "invested": round(total_invested, 2),
                "net_balance": round(net_balance, 2),
                "savings_rate_pct": round(savings_rate, 1)
            },
            "category_breakdown": category_breakdown,
            "alerts": alerts,
            "insights": insights
        }


def get_recent_expenses(limit: int = 10) -> List[Dict[str, Any]]:
    """Get the most recent expenses with category names."""
    with Session(engine) as session:
        expenses = session.exec(
            select(Expense).order_by(Expense.created_at.desc()).limit(limit)
        ).all()

        result = []
        for exp in expenses:
            cat = session.get(Category, exp.category_id)
            result.append({
                "id": exp.id,
                "amount": exp.amount,
                "description": exp.description,
                "category": cat.name if cat else "Unknown",
                "payer": exp.payer,
                "created_at": exp.created_at.isoformat(),
                "is_fixed": exp.is_fixed
            })
        return result
