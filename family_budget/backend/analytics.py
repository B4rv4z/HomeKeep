from datetime import datetime, date
from typing import Dict, Any, List
from sqlmodel import Session, select
from backend.database import engine, Expense, Income, Investment, Category, RecurringExpense


def get_expense_effective_date(exp: Expense) -> date:
    """Get the effective date for an expense - transaction_date if available, else created_at date."""
    if exp.transaction_date:
        return exp.transaction_date
    return exp.created_at.date()


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
        # Uses transaction_date if available, otherwise created_at
        all_expenses = session.exec(select(Expense)).all()
        month_expenses = [
            exp for exp in all_expenses
            if get_expense_effective_date(exp).year == year and get_expense_effective_date(exp).month == month
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

            # Threshold Alert (Exceeding Budget) - Hebrew
            if budget > 0 and spent > budget:
                alerts.append(
                    f"חריגה מתקציב ב'{cat.name}': הוצאת ₪{spent:,.0f} מתוך ₪{budget:,.0f} ({pct_used:.0f}%)"
                )
            elif budget > 0 and pct_used >= 80:
                alerts.append(
                    f"מתקרבים לגבול התקציב ב'{cat.name}': נוצלו {pct_used:.0f}%"
                )

        # 5. Savings Rate Computation
        savings_rate = (total_invested / total_income * 100) if total_income > 0 else 0.0

        # 6. Generate Insights & Recommendations - Hebrew
        insights: List[str] = []
        if total_income > 0:
            insights.append(f"שיעור חיסכון/השקעה חודשי: {savings_rate:.1f}%")
            if savings_rate < 20.0:
                insights.append("המלצה: שאפו לשיעור חיסכון והשקעה של לפחות 20%")
            else:
                insights.append("משמעת חיסכון בריאה נשמרת החודש")

        if total_bonus > 0:
            if total_invested >= (total_bonus * 0.5):
                insights.append("הקצאת בונוס אומתה: מעל 50% מהבונוס הופנה להשקעות")
            else:
                insights.append(
                    "הערה על בונוס: שקלו להקצות חלק גדול יותר מהבונוס החודשי להשקעות"
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
                "is_fixed": exp.is_fixed,
                "source": exp.source
            })
        return result


def calculate_advanced_analytics(year: int, month: int) -> Dict[str, Any]:
    """
    Calculate advanced analytics for a specific month including:
    - Potential duplicate charges
    - Top merchants/stores by spending
    - Spending patterns (day of week, daily average)
    - Expense size distribution
    """
    from collections import defaultdict

    with Session(engine) as session:
        # Get all expenses for the target month
        # Uses transaction_date if available, otherwise created_at
        all_expenses = session.exec(select(Expense)).all()
        month_expenses = [
            exp for exp in all_expenses
            if get_expense_effective_date(exp).year == year and get_expense_effective_date(exp).month == month
        ]

        if not month_expenses:
            return {
                "period": f"{year}-{month:02d}",
                "potential_duplicates": [],
                "top_merchants": [],
                "spending_by_day_of_week": {},
                "daily_average": 0,
                "expense_size_distribution": {},
                "total_transactions": 0,
                "insights": []
            }

        # 1. Find potential duplicates (same amount + similar description within 3 days)
        potential_duplicates = []
        seen_pairs = set()

        for i, exp1 in enumerate(month_expenses):
            for exp2 in month_expenses[i+1:]:
                # Skip if already paired
                pair_key = tuple(sorted([exp1.id, exp2.id]))
                if pair_key in seen_pairs:
                    continue

                # Check if same amount
                if abs(exp1.amount - exp2.amount) < 0.01:
                    # Check if within 3 days (use effective date)
                    date1 = get_expense_effective_date(exp1)
                    date2 = get_expense_effective_date(exp2)
                    day_diff = abs((date1 - date2).days)
                    if day_diff <= 3:
                        # Check description similarity (simple: same first 5 chars or contains same word)
                        desc1_words = set(exp1.description.lower().split())
                        desc2_words = set(exp2.description.lower().split())
                        common_words = desc1_words & desc2_words

                        # If descriptions share words or start similarly
                        similar = (
                            len(common_words) > 0 or
                            exp1.description[:5].lower() == exp2.description[:5].lower()
                        )

                        if similar:
                            seen_pairs.add(pair_key)
                            cat1 = session.get(Category, exp1.category_id)
                            cat2 = session.get(Category, exp2.category_id)
                            potential_duplicates.append({
                                "expense1": {
                                    "id": exp1.id,
                                    "amount": exp1.amount,
                                    "description": exp1.description,
                                    "category": cat1.name if cat1 else "Unknown",
                                    "date": date1.strftime("%Y-%m-%d")
                                },
                                "expense2": {
                                    "id": exp2.id,
                                    "amount": exp2.amount,
                                    "description": exp2.description,
                                    "category": cat2.name if cat2 else "Unknown",
                                    "date": date2.strftime("%Y-%m-%d")
                                },
                                "days_apart": day_diff
                            })

        # 2. Top merchants/stores by total spending
        merchant_totals = defaultdict(lambda: {"total": 0, "count": 0})

        for exp in month_expenses:
            # Normalize description for grouping (take first few words, lowercase)
            desc = exp.description.strip()
            # Try to extract merchant name (first 2-3 significant words)
            words = [w for w in desc.split() if len(w) > 1]
            merchant_key = " ".join(words[:3]) if words else desc
            merchant_totals[merchant_key]["total"] += exp.amount
            merchant_totals[merchant_key]["count"] += 1

        # Sort by total spending and get top 10
        top_merchants = sorted(
            [{"name": k, "total": round(v["total"], 2), "count": v["count"]}
             for k, v in merchant_totals.items()],
            key=lambda x: x["total"],
            reverse=True
        )[:10]

        # 3. Spending by day of week (using effective date)
        day_names_hebrew = {
            0: "שני", 1: "שלישי", 2: "רביעי",
            3: "חמישי", 4: "שישי", 5: "שבת", 6: "ראשון"
        }
        spending_by_dow = defaultdict(float)
        count_by_dow = defaultdict(int)

        for exp in month_expenses:
            effective_date = get_expense_effective_date(exp)
            dow = effective_date.weekday()
            spending_by_dow[dow] += exp.amount
            count_by_dow[dow] += 1

        spending_by_day_of_week = [
            {
                "day": day_names_hebrew[i],
                "day_num": i,
                "total": round(spending_by_dow[i], 2),
                "count": count_by_dow[i],
                "average": round(spending_by_dow[i] / count_by_dow[i], 2) if count_by_dow[i] > 0 else 0
            }
            for i in range(7)
        ]

        # 4. Daily average spending (using effective date)
        unique_days = len(set(get_expense_effective_date(exp) for exp in month_expenses))
        total_spent = sum(exp.amount for exp in month_expenses)
        daily_average = total_spent / unique_days if unique_days > 0 else 0

        # 5. Expense size distribution
        size_buckets = {
            "קטן (עד ₪50)": 0,
            "בינוני (₪50-200)": 0,
            "גדול (₪200-500)": 0,
            "גדול מאוד (₪500-1000)": 0,
            "חריג (מעל ₪1000)": 0
        }

        for exp in month_expenses:
            if exp.amount <= 50:
                size_buckets["קטן (עד ₪50)"] += 1
            elif exp.amount <= 200:
                size_buckets["בינוני (₪50-200)"] += 1
            elif exp.amount <= 500:
                size_buckets["גדול (₪200-500)"] += 1
            elif exp.amount <= 1000:
                size_buckets["גדול מאוד (₪500-1000)"] += 1
            else:
                size_buckets["חריג (מעל ₪1000)"] += 1

        # 6. Generate insights
        insights = []

        if potential_duplicates:
            insights.append(f"נמצאו {len(potential_duplicates)} חיובים שעשויים להיות כפולים")

        if top_merchants and top_merchants[0]["total"] > total_spent * 0.3:
            insights.append(f"'{top_merchants[0]['name']}' מהווה מעל 30% מההוצאות החודשיות")

        # Find highest spending day
        max_dow = max(spending_by_day_of_week, key=lambda x: x["total"])
        if max_dow["total"] > 0:
            insights.append(f"יום ההוצאות הגבוה ביותר: יום {max_dow['day']} (₪{max_dow['total']:,.0f})")

        # Large transactions alert
        large_count = size_buckets["חריג (מעל ₪1000)"]
        if large_count > 0:
            insights.append(f"{large_count} הוצאות מעל ₪1,000 החודש")

        return {
            "period": f"{year}-{month:02d}",
            "potential_duplicates": potential_duplicates,
            "top_merchants": top_merchants,
            "spending_by_day_of_week": spending_by_day_of_week,
            "daily_average": round(daily_average, 2),
            "expense_size_distribution": size_buckets,
            "total_transactions": len(month_expenses),
            "total_spent": round(total_spent, 2),
            "insights": insights
        }
