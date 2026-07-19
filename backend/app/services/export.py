from collections.abc import Iterable
from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell


def _safe_text(value: object) -> object:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def build_ledger_workbook(records: Iterable[dict], categories: list[dict]) -> bytes:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(title="经营记录")
    sheet.append(
        [
            "日期",
            "状态",
            "总收入",
            *[_safe_text(category["name"]) for category in categories],
            "洗车",
            "天气",
            "活动",
            "记录人",
            "最后修改人",
        ]
    )
    def money_cell(value: int) -> WriteOnlyCell:
        cell = WriteOnlyCell(sheet, value=int(value))
        cell.number_format = "€#,##0"
        return cell

    for record in records:
        amounts = {item["category_id"]: item["amount"] for item in record["items"]}
        sheet.append(
            [
                date.fromisoformat(record["date"]),
                record["is_open"],
                money_cell(record["daily_revenue"]),
                *[money_cell(amounts.get(category["id"], 0)) for category in categories],
                record["wash_count"],
                _safe_text(record["weather"]),
                _safe_text(record["activity"]),
                _safe_text(record["created_by_name"]),
                _safe_text(record["updated_by_name"]),
            ]
        )
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
