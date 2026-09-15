# module5_enterprise_info_filler.py
# 模块5：企业信息录入自动化（精简版）
#
# 功能：
# 1. 读取企业信息截图，或直接读取OCR文本模拟文件
# 2. 抽取企业核心字段
# 3. 导出可直接用于底稿填列的Excel
#
# 支持输入：
# - raw_company_screenshots/ 下的 png/jpg/jpeg/webp/bmp
# - raw_company_screenshots/ 下的 txt（用于模拟OCR结果测试）
#
# 输出：
# - 企业信息底稿填列结果.xlsx
#
# 运行：
# py module5_enterprise_info_filler.py

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

import pandas as pd

try:
    from paddleocr import PaddleOCR
except Exception:
    PaddleOCR = None


INPUT_DIR = "raw_company_screenshots"
OUTPUT_FILE = "企业信息底稿填列结果.xlsx"
SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
SUPPORTED_TEXT_EXTS = {".txt"}


def normalize_text(x) -> str:
    if x is None:
        return ""
    try:
        if pd.isna(x):
            return ""
    except Exception:
        pass
    return str(x).strip()


def clean_ocr_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", "", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def standardize_date(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"((?:19|20)\d{2})[年\-/\.](\d{1,2})[月\-/\.](\d{1,2})", text)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        return f"{y}-{mo:02d}-{d:02d}"
    m2 = re.search(r"((?:19|20)\d{2})[年\-/\.](\d{1,2})", text)
    if m2:
        y, mo = m2.group(1), int(m2.group(2))
        return f"{y}-{mo:02d}"
    return text.strip()


def extract_raw_text_from_result(result) -> str:
    lines: List[str] = []
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


def get_ocr():
    if PaddleOCR is None:
        raise RuntimeError("未安装 paddleocr，无法直接识别截图。可先用 .txt 模拟文件测试。")
    return PaddleOCR(lang="ch", use_textline_orientation=True)


def read_source_text(ocr, path: Path) -> str:
    if path.suffix.lower() in SUPPORTED_TEXT_EXTS:
        return clean_ocr_text(path.read_text(encoding="utf-8", errors="ignore"))
    if path.suffix.lower() in SUPPORTED_IMAGE_EXTS:
        result = ocr.predict(str(path))
        raw = extract_raw_text_from_result(result)
        return clean_ocr_text(raw)
    return ""


def find_company_name(text: str) -> str:
    patterns = [
        r"(?:企业名称|公司名称)[:：]?([^\n]{2,80})",
        r"^([^\n]{2,80}(?:有限公司|股份有限公司|集团有限公司|有限责任公司))",
    ]
    for p in patterns:
        m = re.search(p, text, flags=re.MULTILINE)
        if m:
            return m.group(1).strip()
    matches = re.findall(r"([^\n]{2,80}(?:有限公司|股份有限公司|集团有限公司|有限责任公司))", text)
    return matches[0].strip() if matches else ""


def find_credit_code(text: str) -> str:
    patterns = [
        r"(?:统一社会信用代码|社会信用代码|信用代码)[:：]?([0-9A-Z]{18})",
        r"\b([0-9A-Z]{18})\b",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1).strip()
    return ""


def find_legal_person(text: str) -> str:
    patterns = [
        r"(?:法定代表人|法人代表|法定代表)[:：]?([^\n]{2,20})",
        r"(?:法人)[:：]?([^\n]{2,20})",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1).strip()
    return ""


def find_established_date(text: str) -> str:
    patterns = [
        r"(?:成立日期|成立时间|注册时间)[:：]?((?:19|20)\d{2}[年\-/\.]\d{1,2}[月\-/\.]\d{1,2}日?)",
        r"(?:成立日期|成立时间|注册时间)[:：]?((?:19|20)\d{2}[年\-/\.]\d{1,2}[月\-/\.])",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return standardize_date(m.group(1))
    return ""


def find_registered_capital(text: str) -> str:
    m = re.search(r"(?:注册资本)[:：]?([^\n]{1,40})", text)
    return m.group(1).strip() if m else ""


def find_business_status(text: str) -> str:
    m = re.search(r"(?:经营状态|企业状态|登记状态)[:：]?([^\n]{1,20})", text)
    if m:
        return m.group(1).strip()
    for kw in ["存续", "在业", "开业", "注销", "吊销", "迁出"]:
        if kw in text:
            return kw
    return ""


def find_registered_address(text: str) -> str:
    patterns = [
        r"(?:注册地址|住所|企业地址|经营场所)[:：]?([^\n]{5,150})",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1).strip()
    return ""


def parse_company_info(text: str) -> Dict[str, str]:
    return {
        "企业名称": find_company_name(text),
        "统一社会信用代码": find_credit_code(text),
        "法定代表人": find_legal_person(text),
        "成立日期": find_established_date(text),
        "注册资本": find_registered_capital(text),
        "经营状态": find_business_status(text),
        "注册地址": find_registered_address(text),
    }


def process_company_info(input_dir: str = INPUT_DIR):
    base = Path(input_dir)
    if not base.exists():
        raise FileNotFoundError(f"未找到输入目录：{input_dir}")

    files = [
        p for p in base.iterdir()
        if p.is_file() and (p.suffix.lower() in SUPPORTED_IMAGE_EXTS or p.suffix.lower() in SUPPORTED_TEXT_EXTS)
    ]
    if not files:
        raise FileNotFoundError(f"目录 {input_dir} 中未发现可处理文件（图片或txt）")

    need_ocr = any(p.suffix.lower() in SUPPORTED_IMAGE_EXTS for p in files)
    ocr = get_ocr() if need_ocr else None

    rows = []
    for f in files:
        text = read_source_text(ocr, f)
        info = parse_company_info(text)
        rows.append({
            "来源文件": f.name,
            "企业名称": info["企业名称"],
            "统一社会信用代码": info["统一社会信用代码"],
            "法定代表人": info["法定代表人"],
            "成立日期": info["成立日期"],
            "注册资本": info["注册资本"],
            "经营状态": info["经营状态"],
            "注册地址": info["注册地址"],
            "OCR文本预览": text[:300],
        })

    result_df = pd.DataFrame(rows)

    summary_rows = []
    for col in ["企业名称", "统一社会信用代码", "法定代表人", "成立日期", "注册地址"]:
        filled = int(result_df[col].astype(str).str.strip().replace("nan", "").ne("").sum())
        summary_rows.append({
            "字段": col,
            "已识别数量": filled,
            "总数量": len(result_df),
            "识别率": round(filled / len(result_df), 3) if len(result_df) else 0,
        })
    summary_df = pd.DataFrame(summary_rows)

    return result_df, summary_df


def export_result(result_df: pd.DataFrame, summary_df: pd.DataFrame, output_file: str = OUTPUT_FILE):
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="汇总", index=False)
        result_df.to_excel(writer, sheet_name="底稿填列结果", index=False)


def main():
    result_df, summary_df = process_company_info(INPUT_DIR)
    export_result(result_df, summary_df, OUTPUT_FILE)

    print("=== 模块5：企业信息底稿填列汇总 ===")
    print(summary_df.to_string(index=False))
    print(f"\n已导出：{OUTPUT_FILE}")


if __name__ == "__main__":
    main()
