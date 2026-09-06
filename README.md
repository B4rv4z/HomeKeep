# Family Budget Tracker

A privacy-first family finance manager designed for Israeli households, running as a Home Assistant add-on.

## Features

- **Zero Cloud Leakage** - All data stored locally in SQLite
- **Telegram Bot** - Quick expense logging via chat
- **Smart Import** - Parse Israeli CC statements (PDF, XLSX) with OpenAI
- **Learning System** - Improves categorization based on your corrections
- **Installment Tracking** - Proper handling of תשלומים (installment payments)
- **Hebrew Interface** - RTL dashboard designed for Israeli families
- **Advanced Analytics** - Duplicate detection, spending patterns, merchant analysis

## Quick Start

### Home Assistant Add-on

1. Add the repository to Home Assistant
2. Install "Family Budget Tracker"
3. Configure in add-on settings:
   - `telegram_bot_token` - Create via [@BotFather](https://t.me/BotFather)
   - `openai_api_key` - For smart CC statement parsing
   - `allowed_user_ids` - (Optional) Restrict bot access

### Local Development

```bash
cd family_budget
pip install -r requirements.txt
python -m uvicorn backend.main:app --reload --port 8000
```

Open http://localhost:8000

## Usage

### Telegram Bot

**Quick expense:**
```
coffee 25
groceries 340
fuel 220
```

**Bulk import:**
```
/bulk
Shufersal 150.00
Wolt 89.50
Paz Gas 220.00
```

**File upload:**
- Send PDF or XLSX credit card statement
- Bot parses transactions using GPT
- Validates total against file
- Asks for confirmation if mismatch >5%

### Web Dashboard

| Tab | Description |
|-----|-------------|
| לוח בקרה | Overview, quick entry, recent expenses |
| ניהול הוצאות | Full expense table, filtering, bulk delete |
| דוחות והשוואות | Charts, comparisons, advanced analytics |
| הגדרות | Categories, budgets, learned keywords |
| לוג פעילות | Activity history |

## Israeli CC Statement Support

Supports statements from:
- MAX
- Isracard
- CAL
- Leumi Card

### Charge Date vs Transaction Date

| Field | Meaning | Used For |
|-------|---------|----------|
| `transaction_date` | When purchase was made | Day-of-week analytics |
| `charge_date` | When card is billed | Monthly grouping |

For installment payments (תשלומים):
- `amount` = Monthly charge (e.g., ₪78)
- `original_amount` = Total purchase (e.g., ₪780)
- Statement's charge_date determines which month to show

## Learning System

When you change an expense's category:
1. Keywords extracted from description
2. Saved to keyword_mappings table
3. Future imports auto-categorize matching expenses

View/manage learned keywords in Settings → מילות מפתח נלמדות

## API

Full REST API available at `/api/`:

| Endpoint | Description |
|----------|-------------|
| `/api/expenses` | CRUD expenses |
| `/api/categories` | Manage categories |
| `/api/analytics/monthly` | Monthly totals & breakdown |
| `/api/analytics/advanced` | Duplicates, merchants, patterns |
| `/api/keywords` | Learned keyword mappings |
| `/api/logs` | Activity history |

See [CLAUDE.md](CLAUDE.md) for full API documentation.

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather | For Telegram |
| `OPENAI_API_KEY` | OpenAI API key | For CC parsing |
| `ALLOWED_USER_IDS` | Comma-separated Telegram user IDs | No |
| `DATA_PATH` | Database storage path | No (default: ./data) |

### Default Categories

- מזון וצרכנות (Groceries)
- הוצאות רכב (Car expenses)
- מסעדות ואוכל בחוץ (Dining)
- ילדים וחינוך (Kids & Education)
- פנאי ובילוי (Leisure)
- דיור וחשבונות (Housing)
- ביטוח ובריאות (Insurance & Health)
- קניות אינטרנט (Online shopping)
- מנויים ושירותים (Subscriptions)
- כללי ושונות (General)
- טיפוח ויופי (Beauty & Grooming)

## Project Structure

```
family_budget/
├── backend/
│   ├── main.py          # FastAPI app & endpoints
│   ├── database.py      # SQLModel definitions
│   ├── bot.py           # Telegram bot
│   ├── parser.py        # GPT integration
│   └── analytics.py     # Analytics calculations
├── frontend/
│   ├── index.html       # Dashboard (Hebrew RTL)
│   └── js/app.js        # Frontend logic
├── config.yaml          # HA add-on config
├── Dockerfile
├── CLAUDE.md            # Technical documentation
└── README.md
```

## Version History

| Version | Changes |
|---------|---------|
| 1.6.2 | Activity logging for Telegram operations |
| 1.6.1 | Multi-sheet XLSX parsing for foreign transactions |
| 1.6.0 | Charge date + installment payment tracking |
| 1.5.6 | Activity Log tab |
| 1.4.0 | Bulk import validation with confirmation flow |

## License

Private use only.
