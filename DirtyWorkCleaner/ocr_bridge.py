import re
from typing import Optional


def extract_raw_text_from_result(result) -> str:
    """
    从 PaddleOCR 新版 predict() 结果中提取识别文本。
    """
    lines = []
    for block in result:
        if isinstance(block, dict):
            texts = block.get("rec_texts", [])
            for t in texts:
                if t:
                    lines.append(str(t))
        else:
            try:
                texts = getattr(block, "rec_texts", [])
                for t in texts:
                    if t:
                        lines.append(str(t))
            except Exception:
                pass
    return "\n".join(lines)


def clean_ocr_text(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = text.replace(" ", "")
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def extract_voucher_no(text: str) -> str:
    m = re.search(r"API\d{6,}", text)
    return m.group(0) if m else "AUTO"


def extract_date(text: str) -> Optional[str]:
    m = re.search(r"(20\d{2})[\/\-.年](\d{1,2})[\/\-.月](\d{1,2})", text)
    if not m:
        return None
    y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
    return f"{y}-{mo:02d}-{d:02d}"


def extract_amount(text: str) -> Optional[float]:
    """
    优先抓合计/借方合计/本币金额借方附近的金额；
    抓不到再回退到文中最大金额。
    """
    patterns = [
        r"(?:本币金额借方|借方合计|本币金额借方合计|合计)[:：]?\s*([\d,]+\.\d{2})",
    ]
    for p in patterns:
        matches = re.findall(p, text)
        if matches:
            values = [float(x.replace(",", "")) for x in matches]
            return max(values)

    nums = re.findall(r"([\d,]+\.\d{2})", text)
    if nums:
        vals = [float(x.replace(",", "")) for x in nums]
        return max(vals)
    return None


def guess_expense_type(text: str) -> str:
    candidates = [
        "差旅费", "管理费用", "销售费用", "研发费用", "制造费用", "运输费", "折旧", "摊销", "内部结转"
    ]
    for c in candidates:
        if c in text:
            return c
    if "差旅" in text:
        return "差旅费"
    if "管理费" in text:
        return "管理费用"
    if "销售费" in text:
        return "销售费用"
    if "研发支出" in text or "研发费" in text:
        return "研发费用"
    return "其他"


def extract_company_name(text: str) -> str:
    """
    极简公司名抽取：抓‘单位：xxx公司’或‘单位：xxx有限公司’。
    抓不到就给占位值。
    """
    m = re.search(r"单位[:：]?([^\n]{2,30}?公司)", text)
    if m:
        return m.group(1)
    return "某企业"


def build_voucher_ready_text(clean_text: str) -> str:
    voucher_no = extract_voucher_no(clean_text)
    date = extract_date(clean_text) or ""
    amount = extract_amount(clean_text)
    expense_type = guess_expense_type(clean_text)
    company_name = extract_company_name(clean_text)

    amount_str = f"{amount:.2f}" if amount is not None else ""

    normalized = f"""应付立账会计凭证
凭证号码 {voucher_no}
总账日期：{date}
发票日期：{date}
制单单位：{company_name}
凭证金额：{amount_str}
摘要：{expense_type}报销
"""
    return normalized


def save_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
