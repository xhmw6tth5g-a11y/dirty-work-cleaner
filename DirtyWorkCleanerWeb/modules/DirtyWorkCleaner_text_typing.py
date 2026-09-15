import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pandas as pd


@dataclass
class AttachmentItem:
    attachment_type: str
    number: str
    date: str
    need_review: bool
    reason: str = ""
    source_file: str = ""


DATE_PATTERN = re.compile(r"(20\d{2})[年\-/\.](\d{1,2})[月\-/\.](\d{1,2})日?")
API_PATTERN = re.compile(r"API\d{8,}")
NUMBER_PATTERN = re.compile(r"\d{8,20}")
TYPE_ORDER = ["增值税发票", "电子客票", "纸质火车票"]


def standardize_date(text: str) -> Optional[str]:
    m = DATE_PATTERN.search(text)
    if not m:
        return None
    y, mth, d = m.group(1), int(m.group(2)), int(m.group(3))
    return f"{y}-{mth:02d}-{d:02d}"


def extract_after_keyword(text: str, keyword: str, window: int = 60) -> str:
    idx = text.find(keyword)
    if idx == -1:
        return ""
    return text[idx: idx + window]


def deduplicate_preserve_order(values: List[str]) -> List[str]:
    return list(dict.fromkeys(v for v in values if v))


def parse_voucher(text: str) -> Tuple[Optional[str], Optional[str]]:
    voucher_no = None
    voucher_date = None

    m = API_PATTERN.search(text)
    if m:
        voucher_no = m.group(0)

    for kw in ["总账日期", "发票日期", "日期"]:
        seg = extract_after_keyword(text, kw, 40)
        dt = standardize_date(seg)
        if dt:
            voucher_date = dt
            break

    return voucher_no, voucher_date


def classify_attachment(text: str) -> str:
    if "铁路电子客票" in text or "电子发票（铁路电子客票）" in text or "电子发票(铁路电子客票)" in text:
        return "电子客票"
    if "增值税专用发票" in text or ("电子发票" in text and "发票号码" in text and "开票日期" in text) or "发票号码" in text:
        return "增值税发票"
    if "中国铁路" in text or "仅供报销使用" in text or "二等座" in text:
        return "纸质火车票"
    return "其他"


def extract_invoice_number(text: str) -> Optional[str]:
    seg = extract_after_keyword(text, "发票号码", 80)
    candidates = NUMBER_PATTERN.findall(seg)
    if not candidates:
        return None
    for target_len in [17, 20]:
        for c in candidates:
            if len(c) == target_len:
                return c
    return max(candidates, key=len)


def extract_invoice_date(text: str) -> Optional[str]:
    seg = extract_after_keyword(text, "开票日期", 40)
    return standardize_date(seg)


def parse_attachment(text: str, source_file: str) -> Optional[AttachmentItem]:
    att_type = classify_attachment(text)

    if att_type == "增值税发票":
        number = extract_invoice_number(text)
        date = extract_invoice_date(text)
        need_review = not (number and date)
        return AttachmentItem(
            attachment_type=att_type,
            number=number or "",
            date=date or "",
            need_review=need_review,
            reason="增值税发票编号或日期缺失" if need_review else "",
            source_file=source_file,
        )

    if att_type == "电子客票":
        number = extract_invoice_number(text)
        date = extract_invoice_date(text)
        need_review = not (number and date)
        return AttachmentItem(
            attachment_type=att_type,
            number=number or "",
            date=date or "",
            need_review=need_review,
            reason="电子客票编号或日期缺失" if need_review else "",
            source_file=source_file,
        )

    if att_type == "纸质火车票":
        return AttachmentItem(
            attachment_type=att_type,
            number="需进一步确认",
            date="需进一步确认",
            need_review=True,
            reason="纸质火车票需人工查看",
            source_file=source_file,
        )

    return None


def aggregate_items(items: List[AttachmentItem], field_name: str) -> str:
    grouped = {t: [] for t in TYPE_ORDER}
    for item in items:
        grouped[item.attachment_type].append(getattr(item, field_name))

    parts = []
    for t in TYPE_ORDER:
        vals = deduplicate_preserve_order(grouped[t])
        if vals:
            parts.append(f"{t}（{'、'.join(vals)}）")
    return "；".join(parts)


def build_result(voucher_text: str, attachment_files_data: List[Tuple[str, str]]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    voucher_no, voucher_date = parse_voucher(voucher_text)

    attachments: List[AttachmentItem] = []
    for file_name, text in attachment_files_data:
        item = parse_attachment(text, file_name)
        if item:
            attachments.append(item)

    review_reasons = []
    if not voucher_no:
        review_reasons.append("凭证号缺失")
    if not voucher_date:
        review_reasons.append("凭证日期缺失")

    for item in attachments:
        if item.need_review:
            review_reasons.append(f"{item.source_file}: {item.reason}")

    summary_df = pd.DataFrame([
        {
            "凭证号": voucher_no or "",
            "凭证日期": voucher_date or "",
            "附件编号": aggregate_items(attachments, "number"),
            "附件日期": aggregate_items(attachments, "date"),
            "附件数": len(attachments),
            "是否人工复核": "TRUE" if review_reasons else "FALSE",
            "复核原因": "；".join(review_reasons),
        }
    ])

    detail_rows = []
    for item in attachments:
        detail_rows.append(
            {
                "来源文件": item.source_file,
                "附件类型": item.attachment_type,
                "附件编号": item.number,
                "附件日期": item.date,
                "是否人工复核": "TRUE" if item.need_review else "FALSE",
                "原因": item.reason,
            }
        )

    details_df = pd.DataFrame(detail_rows)
    return summary_df, details_df
