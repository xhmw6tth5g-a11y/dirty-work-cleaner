import os
import re
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional

import pandas as pd

from bridge_service import extract_expense_type, extract_voucher_no, extract_voucher_amount

try:
    from paddleocr import PaddleOCR
except Exception:
    PaddleOCR = None

from ocr_bridge import extract_raw_text_from_result, clean_ocr_text, build_voucher_ready_text

OCR_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_ocr_instance = None


def _to_bool(x: Any) -> bool:
    if x is None:
        return False
    s = str(x).strip().lower()
    return s in {"1", "true", "yes", "y", "是", "on"}


def _to_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    s = str(x).strip()
    if not s:
        return None
    try:
        return float(s.replace(",", ""))
    except Exception:
        return None


def _to_int(x: Any, default: int = 0) -> int:
    try:
        return int(float(str(x).strip()))
    except Exception:
        return default


def _get_ocr():
    global _ocr_instance
    if _ocr_instance is None:
        if PaddleOCR is None:
            raise RuntimeError("当前服务器未安装 PaddleOCR，无法处理图片凭证。")
        _ocr_instance = PaddleOCR(
            lang="ch",
            use_textline_orientation=True,
        )
    return _ocr_instance


def _file_ext(filename: str) -> str:
    return Path(filename or "").suffix.lower()


def _read_text_upload(upload) -> str:
    return upload.file.read().decode("utf-8", errors="ignore")


def _ocr_image_upload(upload) -> str:
    ocr = _get_ocr()
    suffix = _file_ext(upload.filename) or ".png"

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(upload.file.read())
        tmp_path = tmp.name

    try:
        result = ocr.predict(tmp_path)
        raw_text = extract_raw_text_from_result(result)
        return clean_ocr_text(raw_text)
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


def extract_voucher_info(voucher_file, form) -> Dict[str, Any]:
    manual_voucher_no = str(form.get("voucher_no") or "").strip()
    manual_voucher_date = str(form.get("voucher_date") or "").strip()
    manual_expense_type = str(form.get("expense_type") or "").strip()
    manual_amount = _to_float(form.get("voucher_amount"))

    raw_voucher_text = ""
    standardized_voucher_text = ""

    if voucher_file and voucher_file.filename:
        ext = _file_ext(voucher_file.filename)
        if ext == ".txt":
            raw_voucher_text = clean_ocr_text(_read_text_upload(voucher_file))
            standardized_voucher_text = build_voucher_ready_text(raw_voucher_text)
        elif ext in OCR_IMAGE_EXTS:
            raw_voucher_text = _ocr_image_upload(voucher_file)
            standardized_voucher_text = build_voucher_ready_text(raw_voucher_text)
        else:
            raise ValueError(f"暂不支持的凭证文件类型：{ext}")

    voucher_no = extract_voucher_no(standardized_voucher_text) if standardized_voucher_text else manual_voucher_no
    expense_type = extract_expense_type(standardized_voucher_text) if standardized_voucher_text else manual_expense_type
    voucher_amount = extract_voucher_amount(standardized_voucher_text) if standardized_voucher_text else manual_amount

    if not voucher_no:
        voucher_no = manual_voucher_no
    if not expense_type:
        expense_type = manual_expense_type or "其他"
    if voucher_amount is None:
        voucher_amount = manual_amount

    voucher_date = manual_voucher_date
    if standardized_voucher_text and not voucher_date:
        m = re.search(r"(?:总账日期|发票日期)[:：]\s*([0-9\-]+)", standardized_voucher_text)
        if m:
            voucher_date = m.group(1)

    return {
        "voucher_no": voucher_no or "",
        "voucher_date": voucher_date or "",
        "expense_type": expense_type or "其他",
        "voucher_amount": voucher_amount,
        "raw_voucher_text": raw_voucher_text,
        "standardized_voucher_text": standardized_voucher_text,
    }


def build_paper_voucher_payload(form, voucher_file=None) -> Dict[str, Any]:
    voucher_info = extract_voucher_info(voucher_file, form)

    attachment_exists = str(form.get("attachment_exists") or "yes").strip().lower()
    has_attachment = attachment_exists in {"yes", "true", "1", "是", "有"}

    attachment_count = _to_int(form.get("attachment_count"), 0)
    attachment_type = str(form.get("attachment_type") or "").strip()
    is_homogeneous = _to_bool(form.get("is_homogeneous"))
    representative_mode = _to_bool(form.get("representative_mode"))
    representative_count = _to_int(form.get("representative_count"), 0)

    representative_avg_amount = _to_float(form.get("representative_avg_amount"))
    estimated_attachment_amount = _to_float(form.get("estimated_attachment_amount"))

    amount_covered_manual = str(form.get("amount_covered_manual") or "").strip()
    obvious_anomaly = _to_bool(form.get("obvious_anomaly"))
    need_manual_review = _to_bool(form.get("need_manual_review"))
    notes = str(form.get("notes") or "").strip()

    voucher_amount = voucher_info["voucher_amount"]

    computed_attachment_amount = estimated_attachment_amount
    if computed_attachment_amount is None and representative_mode and representative_avg_amount is not None and attachment_count > 0:
        computed_attachment_amount = round(representative_avg_amount * attachment_count, 2)

    if computed_attachment_amount is None and amount_covered_manual == "yes" and voucher_amount is not None:
        computed_attachment_amount = voucher_amount

    if computed_attachment_amount is None and amount_covered_manual == "no":
        computed_attachment_amount = 0.0

    no_attachment_class = not has_attachment or attachment_count == 0

    if no_attachment_class:
        process_status = "无附件，不进入Docu"
    elif representative_mode:
        process_status = "代表性录入"
    else:
        process_status = "待处理"

    module1_review_flag = need_manual_review or obvious_anomaly

    summary_reason_parts = []
    if no_attachment_class:
        summary_reason_parts.append("无附件，不进入Docu")
    if representative_mode:
        summary_reason_parts.append("采用代表性录入")
    if obvious_anomaly:
        summary_reason_parts.append("人工标记存在异常")
    if need_manual_review:
        summary_reason_parts.append("人工标记需复核")
    if notes:
        summary_reason_parts.append(f"备注：{notes}")

    prefill_row = {
        "凭证号": voucher_info["voucher_no"],
        "费用类型": voucher_info["expense_type"],
        "凭证金额": voucher_amount,
        "是否提供凭证": True,
        "附件金额合计": computed_attachment_amount,
        "是否使用抽样": representative_mode,
        "附件总数量": attachment_count,
        "抽样平均金额": representative_avg_amount,
        "处理状态": process_status,
        "模块1是否人工复核": module1_review_flag,
        "是否无附件类": no_attachment_class,
        "原始凭证文本": voucher_info["standardized_voucher_text"] or voucher_info["raw_voucher_text"],
    }

    return {
        "voucher_info": voucher_info,
        "attachment_exists": has_attachment,
        "attachment_count": attachment_count,
        "attachment_type": attachment_type,
        "is_homogeneous": is_homogeneous,
        "representative_mode": representative_mode,
        "representative_count": representative_count,
        "representative_avg_amount": representative_avg_amount,
        "estimated_attachment_amount": computed_attachment_amount,
        "amount_covered_manual": amount_covered_manual,
        "obvious_anomaly": obvious_anomaly,
        "need_manual_review": need_manual_review,
        "notes": notes,
        "prefill_df": pd.DataFrame([prefill_row]),
        "summary_reason": "；".join(summary_reason_parts),
    }


def build_paper_summary_df(payload: Dict[str, Any]) -> pd.DataFrame:
    v = payload["voucher_info"]
    review_flag = "TRUE" if payload["need_manual_review"] or payload["obvious_anomaly"] else "FALSE"

    return pd.DataFrame([{
        "凭证号": v["voucher_no"],
        "凭证日期": v["voucher_date"],
        "附件类型": payload["attachment_type"],
        "附件数": payload["attachment_count"],
        "是否同质": "TRUE" if payload["is_homogeneous"] else "FALSE",
        "代表性录入": "TRUE" if payload["representative_mode"] else "FALSE",
        "代表性录入数量": payload["representative_count"],
        "附件估计金额": payload["estimated_attachment_amount"],
        "是否人工复核": review_flag,
        "复核原因": payload["summary_reason"],
    }])


def build_paper_log_df(payload: Dict[str, Any]) -> pd.DataFrame:
    v = payload["voucher_info"]

    return pd.DataFrame([{
        "凭证号": v["voucher_no"],
        "费用类型": v["expense_type"],
        "附件类型": payload["attachment_type"],
        "附件金额合计": payload["estimated_attachment_amount"],
        "附件数量": payload["attachment_count"],
        "模块1是否人工复核": payload["need_manual_review"] or payload["obvious_anomaly"],
        "模块1复核原因": payload["summary_reason"],
        "代表性录入": payload["representative_mode"],
        "代表性录入数量": payload["representative_count"],
        "是否同质": payload["is_homogeneous"],
        "人工确认覆盖": payload["amount_covered_manual"],
        "是否发现异常": payload["obvious_anomaly"],
        "备注": payload["notes"],
    }])
