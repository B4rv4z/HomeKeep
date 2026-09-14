"""
Portfolio Excel parser for Israeli bank exports.

Parses the specific XML format used by Israeli banks for portfolio exports.
Uses direct XML parsing since openpyxl may fail on some bank-generated files.
"""
import logging
import re
import zipfile
from io import BytesIO
from typing import Optional
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

# XML namespace for Excel spreadsheet
NS = {'x': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def parse_portfolio_xlsx(file_bytes: bytes) -> dict:
    """
    Parse Israeli bank portfolio export from XLSX bytes.

    Returns:
    {
        "summary": {
            "total_value_ils": 1264018.19,
            "total_change_ils": 269750.86,
            "total_change_pct": 27.13,
            "export_date": "2026-09-14"
        },
        "holdings": [
            {
                "symbol": "GOOGL",
                "name": "ALPHABET INC-CL A",
                "quantity": 99,
                "price": 345.02,
                "currency": "USD",
                "cost_basis": 301.26,
                "value_ils": 104144.63,
                "daily_change_pct": 1.93,
                "total_change_pct": 14.52
            },
            ...
        ]
    }
    """
    try:
        # Extract sheet XML from XLSX (which is a zip file)
        with zipfile.ZipFile(BytesIO(file_bytes)) as zf:
            sheet_xml = zf.read('xl/worksheets/sheet1.xml').decode('utf-8')

        # Parse XML
        root = ET.fromstring(sheet_xml)

        # Find all rows
        rows = root.findall('.//x:row', NS)

        # Parse rows into a 2D list of cell values
        parsed_rows = []
        for row in rows:
            cells = row.findall('x:c', NS)
            row_values = []
            for cell in cells:
                value = _get_cell_value(cell)
                row_values.append(value)
            parsed_rows.append(row_values)

        # Extract summary from header rows (typically row 5)
        summary = _extract_summary(parsed_rows)

        # Extract holdings from data rows
        holdings = _extract_holdings(parsed_rows)

        logger.info(f"Parsed portfolio: {len(holdings)} holdings, total value: {summary.get('total_value_ils', 0):.2f}")

        return {
            "summary": summary,
            "holdings": holdings
        }

    except Exception as e:
        logger.error(f"Error parsing portfolio XLSX: {e}")
        return {
            "summary": {},
            "holdings": [],
            "error": str(e)
        }


def _get_cell_value(cell) -> Optional[str]:
    """Extract value from an Excel XML cell element."""
    cell_type = cell.get('t')

    # Inline string
    if cell_type == 'inlineStr':
        is_elem = cell.find('x:is', NS)
        if is_elem is not None:
            t_elem = is_elem.find('x:t', NS)
            if t_elem is not None and t_elem.text:
                return t_elem.text.strip()
        return None

    # Number
    if cell_type == 'n' or cell_type is None:
        v_elem = cell.find('x:v', NS)
        if v_elem is not None and v_elem.text:
            return v_elem.text.strip()

    return None


def _extract_summary(rows: list) -> dict:
    """Extract portfolio summary from header rows."""
    summary = {}

    # Look for summary row (typically row 5, index 4)
    # Contains: "שווי תיק בש"ח:", value, "סך הכנסה לקבל בש"ח:", value, etc.
    for row in rows[:10]:  # Check first 10 rows
        row_text = ' '.join(str(v) for v in row if v)

        # Total portfolio value
        if 'שווי תיק' in row_text:
            for i, cell in enumerate(row):
                if cell and 'שווי תיק' in str(cell):
                    # Next cell should be the value
                    if i + 1 < len(row) and row[i + 1]:
                        try:
                            summary['total_value_ils'] = float(row[i + 1])
                        except (ValueError, TypeError):
                            pass

        # Cumulative change amount
        if 'שינוי מצטבר בש"ח' in row_text or 'שינוי מצטבר בשח' in row_text:
            for i, cell in enumerate(row):
                cell_str = str(cell) if cell else ''
                if 'שינוי מצטבר' in cell_str and 'באחוז' not in cell_str:
                    if i + 1 < len(row) and row[i + 1]:
                        try:
                            summary['total_change_ils'] = float(row[i + 1])
                        except (ValueError, TypeError):
                            pass

        # Cumulative change percentage
        if 'שינוי מצטבר באחוז' in row_text:
            for i, cell in enumerate(row):
                if cell and 'שינוי מצטבר באחוז' in str(cell):
                    if i + 1 < len(row) and row[i + 1]:
                        try:
                            summary['total_change_pct'] = float(row[i + 1])
                        except (ValueError, TypeError):
                            pass

        # Export date
        date_match = re.search(r'תאריך ייצוא:\s*(\d{1,2}/\d{1,2}/\d{4})', row_text)
        if date_match:
            date_str = date_match.group(1)
            # Convert DD/MM/YYYY to YYYY-MM-DD
            parts = date_str.split('/')
            if len(parts) == 3:
                summary['export_date'] = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"

    return summary


def _extract_holdings(rows: list) -> list:
    """Extract individual holdings from data rows."""
    holdings = []

    # Find header row with column names
    header_row_idx = None
    col_map = {}

    for idx, row in enumerate(rows):
        row_text = ' '.join(str(v) for v in row if v)

        # Header row contains: נייר, מספר נייר, סימבול, כמות, שער אחרון, etc.
        if 'סימבול' in row_text and 'כמות' in row_text:
            header_row_idx = idx
            for col_idx, cell in enumerate(row):
                cell_str = str(cell).strip() if cell else ''

                if cell_str == 'נייר':
                    col_map['name'] = col_idx
                elif cell_str == 'סימבול':
                    col_map['symbol'] = col_idx
                elif cell_str == 'כמות':
                    col_map['quantity'] = col_idx
                elif cell_str == 'שער אחרון':
                    col_map['price'] = col_idx
                elif cell_str == 'מטבע':
                    col_map['currency'] = col_idx
                elif cell_str == 'שער עלות מותאם':
                    col_map['cost_basis'] = col_idx
                elif cell_str == 'שווי אחזקה בשח':
                    col_map['value_ils'] = col_idx
                elif cell_str == 'שינוי יומי באחוז':
                    col_map['daily_change_pct'] = col_idx
                elif 'שינוי משער עלות מותאם באחוז' in cell_str:
                    col_map['total_change_pct'] = col_idx

            logger.info(f"Found header at row {idx}, columns: {col_map}")
            break

    if header_row_idx is None:
        logger.warning("Could not find header row in portfolio")
        return holdings

    # Extract data rows
    for row in rows[header_row_idx + 1:]:
        # Skip empty rows and section headers
        if not row or len(row) < 3:
            continue

        # Skip section headers like "ניע ישראלים", "ניע זרים", "מניות", "מחקי מדד"
        first_cell = str(row[1]) if len(row) > 1 and row[1] else ''
        if first_cell in ['ניע ישראלים', 'ניע זרים', 'מניות', 'מחקי מדד', '', ' ']:
            continue

        # Skip total rows
        if 'סה"כ' in first_cell or ':סה"כ' in first_cell:
            continue

        # Get symbol - if no symbol, skip this row
        symbol_idx = col_map.get('symbol')
        if symbol_idx is None or symbol_idx >= len(row):
            continue
        symbol = row[symbol_idx]
        if not symbol or str(symbol).strip() in ['', ' ']:
            continue

        # Extract holding data
        try:
            holding = {
                'symbol': str(symbol).strip(),
                'name': _get_value(row, col_map.get('name'), ''),
                'quantity': _get_float(row, col_map.get('quantity'), 0),
                'price': _get_float(row, col_map.get('price'), 0),
                'currency': _get_value(row, col_map.get('currency'), 'USD'),
                'cost_basis': _get_float(row, col_map.get('cost_basis'), 0),
                'value_ils': _get_float(row, col_map.get('value_ils'), 0),
                'daily_change_pct': _get_float(row, col_map.get('daily_change_pct'), 0),
                'total_change_pct': _get_float(row, col_map.get('total_change_pct'), 0),
            }

            # Only add if we have meaningful data
            if holding['quantity'] > 0:
                holdings.append(holding)
                logger.debug(f"Parsed holding: {holding['symbol']} - {holding['quantity']} shares")

        except Exception as e:
            logger.warning(f"Error parsing holding row: {e}")
            continue

    return holdings


def _get_value(row: list, idx: Optional[int], default: str) -> str:
    """Get string value from row at index."""
    if idx is None or idx >= len(row) or row[idx] is None:
        return default
    return str(row[idx]).strip()


def _get_float(row: list, idx: Optional[int], default: float) -> float:
    """Get float value from row at index."""
    if idx is None or idx >= len(row) or row[idx] is None:
        return default
    try:
        return float(row[idx])
    except (ValueError, TypeError):
        return default
