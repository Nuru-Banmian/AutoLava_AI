from collections.abc import Iterable
from datetime import date
from io import BytesIO

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell


def _safe_text(value: object) -> object:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def build_ledger_workbook(records: Iterable[dict]) -> bytes:
    records = list(records)
    workbook = Workbook(write_only=True)
    summary = workbook.create_sheet(title="经营记录")
    summary.append(
        [
            "日期",
            "状态",
            "总收入",
            "洗车",
            "天气",
            "活动",
            "记录人",
            "最后修改人",
        ]
    )

    detail = workbook.create_sheet(title="收入明细")
    detail.append(["日期", "收入项目", "计入总额", "排序", "金额"])

    def money_cell(sheet, value: int) -> WriteOnlyCell:
        cell = WriteOnlyCell(sheet, value=int(value))
        cell.number_format = "€#,##0"
        return cell

    for record in records:
        summary.append(
            [
                date.fromisoformat(record["date"]),
                record["is_open"],
                money_cell(summary, record["daily_revenue"]),
                record["wash_count"],
                _safe_text(record["weather"]),
                _safe_text(record["activity"]),
                _safe_text(record["created_by_name"]),
                _safe_text(record["updated_by_name"]),
            ]
        )
        for item in sorted(
            record["items"], key=lambda value: (value["sort_order"], value["id"])
        ):
            detail.append(
                [
                    date.fromisoformat(record["date"]),
                    _safe_text(item["category_name"]),
                    item["include_in_total"],
                    item["sort_order"],
                    money_cell(detail, item["amount"]),
                ]
            )
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
