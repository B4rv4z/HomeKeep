# Family Budget Tracker - Technical Documentation

**Version:** 1.6.2
**Purpose:** Zero-leakage local family finance manager with Telegram bot and SQLite
**Target Platform:** Home Assistant Add-on

---

## Project Overview

A privacy-first family budget management system designed for Israeli households. It features:
- Web dashboard for viewing/managing finances
- Telegram bot for quick expense logging and CC statement imports
- Smart expense categorization via OpenAI GPT
- Learning system that improves categorization over time
- Support for Israeli credit card statement formats (PDF, XLSX)
- Installment payment (תשלומים) tracking with proper monthly allocation

---

## Project Structure

```
family_budget/
├── backend/
│   ├── __init__.py
│   ├── main.py          # FastAPI application, all API endpoints
│   ├── database.py      # SQLModel definitions, migrations, seeding
│   ├── bot.py           # Telegram bot handlers, file parsing
│   ├── parser.py        # OpenAI GPT integration, text parsing
│   └── analytics.py     # Monthly analytics calculations
├── frontend/
│   ├── index.html       # Single-page dashboard (Hebrew RTL)
│   └── js/
│       └── app.js       # Frontend JavaScript application
├── data/                # SQLite database storage (gitignored)
├── config.yaml          # Home Assistant add-on configuration
├── Dockerfile           # Container build instructions
├── requirements.txt     # Python dependencies
├── run.sh              # Container entrypoint script
└── build.yaml          # Home Assistant build configuration
```

---

## Database Schema

### Tables (SQLModel definitions in `backend/database.py`)

#### `members`
| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| name | str | Family member name (unique) |

#### `categories`
| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| name | str | Category name (Hebrew, unique) |
| type | str | 'fixed' or 'variable' |
| monthly_budget | float | Budget allocation for this category |

**Default categories:** מזון וצרכנות, הוצאות רכב, מסעדות ואוכל בחוץ, ילדים וחינוך, פנאי ובילוי, דיור וחשבונות, ביטוח ובריאות, קניות אינטרנט, מנויים ושירותים, כללי ושונות, טיפוח ויופי

#### `expenses`
| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| amount | float | Monthly charge amount (for installments, this is the monthly payment) |
| description | str | Expense description/merchant name |
| category_id | int | FK to categories |
| payer | str | Who paid (default: "Unknown") |
| created_at | datetime | Record creation timestamp |
| **transaction_date** | date | Original purchase date (when you bought) |
| **charge_date** | date | Statement billing date (when card is charged) |
| is_fixed | bool | Fixed expense flag |
| source | str | 'manual' or 'file' |
| **original_amount** | float | Total purchase amount (for installments only) |
| **installment_number** | int | Current payment number (e.g., 3 in "3/10") |
| **total_installments** | int | Total payments (e.g., 10 in "3/10") |

**Key Date Logic:**
- `charge_date` determines which month the expense belongs to (for monthly grouping)
- `transaction_date` is when the purchase actually occurred (for analytics like "spending by day of week")
- Fallback order: charge_date → transaction_date → created_at

#### `incomes`
| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| member_id | int | FK to members |
| amount | float | Income amount |
| income_type | str | 'salary', 'bonus', 'extra' |
| received_date | date | Date received |
| notes | str | Optional notes |

#### `investments`
| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| target_name | str | Investment target name |
| amount | float | Amount invested |
| transaction_date | date | Investment date |
| notes | str | Optional notes |

#### `recurring_expenses`
| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| name | str | Expense name (e.g., "משכנתא") |
| amount | float | Monthly amount |
| category_id | int | FK to categories |
| frequency | str | 'monthly' or 'one_time' |
| day_of_month | int | Due day (1-31) |
| is_active | bool | Active flag |
| notes | str | Optional notes |

#### `keyword_mappings` (Learning System)
| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| keyword | str | Keyword to match (lowercase, unique) |
| category_id | int | FK to categories |

When a user changes an expense's category, keywords are extracted from the description and saved here. Future imports use these mappings for automatic categorization.

#### `activity_logs`
| Column | Type | Description |
|--------|------|-------------|
| id | int | Primary key |
| timestamp | datetime | Log timestamp |
| action | str | 'expense_added', 'file_import', etc. |
| source | str | 'telegram', 'dashboard', 'file' |
| details | str | Additional details |
| record_count | int | Number of records (for bulk imports) |
| file_date | date | Statement date (for imports) |
| total_amount | float | Total amount involved |

---

## API Endpoints (backend/main.py)

### Expenses
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/expenses` | Get recent expenses (limit param) |
| POST | `/api/expenses` | Create expense |
| PATCH | `/api/expenses/{id}` | Update expense (triggers learning) |
| DELETE | `/api/expenses/{id}` | Delete single expense |
| DELETE | `/api/expenses/bulk/by-source/{source}` | Delete by source |
| DELETE | `/api/expenses/bulk/by-month?year=&month=` | Delete month expenses |
| GET | `/api/expenses/by-month?year=&month=` | Get expenses for specific month |

### Incomes
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/incomes` | Get all incomes |
| POST | `/api/incomes` | Create income |
| DELETE | `/api/incomes/{id}` | Delete income |

### Investments
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/investments` | Get all investments |
| POST | `/api/investments` | Create investment |
| DELETE | `/api/investments/{id}` | Delete investment |

### Categories
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/categories` | Get all categories |
| POST | `/api/categories` | Create category |
| PUT | `/api/categories/{id}` | Update category |
| DELETE | `/api/categories/{id}` | Delete (only if unused) |

### Recurring Expenses
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/recurring` | Get all recurring expenses |
| POST | `/api/recurring` | Create recurring expense |
| PATCH | `/api/recurring/{id}` | Update recurring expense |
| DELETE | `/api/recurring/{id}` | Delete recurring expense |

### Analytics
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/analytics/monthly?year=&month=` | Monthly totals, category breakdown, alerts |
| GET | `/api/analytics/recent?limit=` | Recent expenses with categories |
| GET | `/api/analytics/advanced?year=&month=` | Duplicates, merchants, day-of-week patterns |
| GET | `/api/analytics/comparison?months=` | Multi-month comparison data |

### Keywords (Learning System)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/keywords` | Get all keyword mappings |
| GET | `/api/keywords/stats` | Keyword statistics |
| POST | `/api/keywords` | Add keyword mapping |
| DELETE | `/api/keywords/{id}` | Delete keyword |
| DELETE | `/api/keywords/bulk/all` | Reset all learning |

### Activity Logs
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/logs?limit=` | Get recent activity logs |
| DELETE | `/api/logs/clear` | Clear all logs |

### Other
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Serve dashboard HTML |
| GET | `/api/members` | Get family members |

---

## Telegram Bot (backend/bot.py)

### Commands
| Command | Description |
|---------|-------------|
| `/start` | Welcome message with usage instructions |
| `/help` | Help text with examples |
| `/bulk <text>` | Bulk import transactions from text |

### Message Handlers
- **Text messages:** Parsed as quick expenses (e.g., "coffee 25" → ₪25 to מסעדות)
- **Document uploads:** PDF, XLSX, CSV, TXT files parsed as CC statements

### File Processing Flow
1. User uploads file to Telegram
2. `handle_document()` downloads and validates file
3. Text extracted via `extract_text_from_pdf()` or `extract_text_from_xlsx()`
4. Charge date extracted from file header
5. `parse_bulk_transactions()` sends text to GPT for parsing
6. If parsed total differs from file total by >5%, user confirmation required
7. Transactions saved with charge_date applied to all
8. Activity logged to activity_logs table

### Key Functions

**`extract_charge_date_from_xlsx()`**
Extracts billing date from CC statement header. Supports:
- "עסקאות לחיוב ב-DD/MM/YYYY" (Isracard/CAL format)
- "MM/YYYY" standalone cell (MAX format)
- "תאריך חיוב" column header

**`extract_text_from_xlsx()`**
Smart XLSX parsing that:
- Identifies Israeli CC statement structure
- Extracts only "סכום חיוב" (charge amount), not "סכום עסקה מקורי"
- Removes summary lines that confuse GPT
- Preserves header with charge date info

**`save_transactions_to_db()`**
Saves parsed transactions with:
- charge_date from file header
- transaction_date from GPT parsing (original purchase date)
- installment info (original_amount, installment_number, total_installments)

### Activity Logging
The bot logs activities for:
- Manual expenses via Telegram (action: "expense_added", source: "telegram")
- File imports (action: "file_import", source: "telegram")
- Approved imports with mismatch (includes "approved with mismatch" in details)

---

## Parser / GPT Integration (backend/parser.py)

### `parse_expense_text(text)`
Parses single expense from Telegram message.
1. Extracts amount via regex
2. Checks keyword_mappings for category match (free, fast)
3. Falls back to GPT classification (if OpenAI configured)
4. Default: "כללי ושונות"

### `parse_bulk_transactions(text)`
Parses CC statement text using GPT-4o-mini.

**GPT Prompt includes:**
- Instructions for Israeli CC statement structure
- Amount logic: ALWAYS use "סכום חיוב" (charge amount)
- Installment extraction: original_amount, installment_current, installment_total
- Multi-section handling (domestic + foreign transactions)
- Date parsing: Convert DD/MM/YY to YYYY-MM-DD
- Category list from database

**Returns:**
```python
[{
    "amount": 78.0,          # Monthly charge
    "original_amount": 780.0, # For installments
    "description": "Store",
    "category_id": 5,
    "category_name": "קטגוריה",
    "transaction_date": "2026-01-15",  # Original purchase
    "installment_current": 3,
    "installment_total": 10
}]
```

### Learning System

**`learn_category_from_correction(description, new_category_id)`**
Called when user changes expense category via PATCH /api/expenses/{id}:
1. Extracts keywords from description
2. Saves to keyword_mappings table
3. Future imports check keywords BEFORE sending to GPT

**`get_category_by_keywords(description)`**
Checks if description matches learned keywords:
1. Exact match on full description
2. Word-level matching with regex boundaries

---

## Analytics (backend/analytics.py)

### Date Handling Functions

**`get_expense_effective_date(exp)`**
For monthly grouping (which month does expense belong to):
- Priority: charge_date → transaction_date → created_at
- Used for: monthly analytics, filtering by month

**`get_expense_transaction_date(exp)`**
For shopping behavior analytics:
- Priority: transaction_date → charge_date → created_at
- Used for: day-of-week patterns, duplicate detection

### `calculate_monthly_analytics(year, month)`
Returns:
```python
{
    "period": "2026-09",
    "totals": {
        "income": 15000.0,
        "salary": 12000.0,
        "bonus": 3000.0,
        "spent": 8500.0,
        "invested": 2000.0,
        "savings_rate_pct": 13.3
    },
    "category_breakdown": [...],
    "alerts": ["חריגה מתקציב ב'מזון'..."],
    "insights": ["שיעור חיסכון: 13.3%"]
}
```

### `calculate_advanced_analytics(year, month)`
Returns:
```python
{
    "potential_duplicates": [...],  # Same amount + similar desc on same day
    "top_merchants": [...],          # Top 10 by spending
    "spending_by_day_of_week": [...], # Uses transaction_date
    "daily_average": 250.0,
    "expense_size_distribution": {...},
    "total_transactions": 85,
    "total_spent": 8500.0,
    "insights": [...]
}
```

---

## Frontend (frontend/index.html + js/app.js)

### Tabs
1. **לוח בקרה (Dashboard):** Overview, quick entry forms, recent expenses
2. **ניהול הוצאות (Expenses):** Full expense table, filtering, bulk delete
3. **דוחות והשוואות (Reports):** Charts, comparisons, advanced analytics
4. **הגדרות (Settings):** Categories, budgets, learned keywords
5. **לוג פעילות (Logs):** Activity history

### Global Month Selector
- Single month selector in header affects all tabs
- `selectedMonth` variable stores "YYYY-M" format
- `loadByGlobalMonth()` refreshes all relevant data

### Key Features
- Inline editing of expenses (description, amount, category)
- Category changes trigger backend learning
- Installment badge display: "תשלום 3/10" with tooltip showing original amount
- RTL Hebrew interface

---

## Configuration (config.yaml)

```yaml
options:
  telegram_bot_token: ""      # Required for Telegram bot
  allowed_user_ids: ""        # Comma-separated user IDs (optional)
  openai_api_key: ""          # Required for smart parsing
```

Environment variables:
- `TELEGRAM_BOT_TOKEN`
- `ALLOWED_USER_IDS`
- `OPENAI_API_KEY`
- `DATA_PATH` (default: ./data)
- `DATABASE_URL` (default: sqlite:///data/family_budget.db)

---

## Israeli CC Statement Handling

### Supported Formats
- **PDF:** MAX, Isracard, CAL, Leumi Card
- **XLSX:** MAX, Isracard, CAL

### Key Patterns Recognized
- Header: "עסקאות לחיוב ב-DD/MM/YYYY"
- Amount columns: "סכום חיוב" (use this!) vs "סכום עסקה מקורי" (ignore)
- Installments: "תשלום X מתוך Y" or "X/Y"
- Totals: "סך הכל" followed by amount (marks section end, not document end)
- Foreign transactions: Appear AFTER first "סך הכל", must also be parsed

### Charge Date vs Transaction Date

| Field | Meaning | Example |
|-------|---------|---------|
| transaction_date | When you made the purchase | Aug 15, 2026 |
| charge_date | When card is billed | Sep 2, 2026 |

**For installment payments:**
- The same purchase (e.g., ₪780 in June) appears as ₪78/month
- Each month's statement shows charge_date = that month's billing date
- transaction_date stays the same (original purchase)

---

## Database Migrations

`migrate_db()` in database.py handles schema evolution:
- Adds `transaction_date` column
- Adds `charge_date` column
- Adds `original_amount`, `installment_number`, `total_installments`

Called automatically on startup via `init_db()`.

---

## Development Notes

### Running Locally
```bash
cd family_budget
pip install -r requirements.txt
python -m uvicorn backend.main:app --reload --port 8000
```

### Adding New Features

**New API endpoint:**
1. Add Pydantic model in main.py
2. Add endpoint function with @app decorator
3. Use `db: Session = Depends(get_session)` for DB access
4. Add activity logging if user-facing action

**New database field:**
1. Add to SQLModel class in database.py
2. Add migration in `migrate_db()`
3. Update relevant endpoints to handle field
4. Update frontend to display/edit field

**New category:**
1. Add to default categories list in `init_db()`
2. Add relevant keyword mappings

---

## Version History

- **v1.6.2:** Add activity logging for Telegram operations
- **v1.6.1:** Fix multi-sheet XLSX parsing for foreign currency
- **v1.6.0:** Add charge_date + installment payment tracking
- **v1.5.6:** Add Activity Log tab
- **v1.5.x:** Keyword learning system, advanced analytics
- **v1.4.x:** Bulk import validation with confirmation flow
