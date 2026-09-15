from pathlib import Path
import re
from paddleocr import PaddleOCR

from ocr_bridge import (
    extract_raw_text_from_result,
    clean_ocr_text,
    build_voucher_ready_text,
    save_text,
)

# 轻量一点的配置，适合初赛演示

ocr = PaddleOCR(
    lang="ch",
    use_textline_orientation=True,
)

img_path = "voucher_real_01.jpg"

result = ocr.predict(img_path)

raw_text = extract_raw_text_from_result(result)
clean_text = clean_ocr_text(raw_text)
voucher_ready_text = build_voucher_ready_text(clean_text)

print("=== OCR原始清洗文本 ===")
print(clean_text)
print("\n=== 标准化凭证文本（可喂给模块1/2） ===")
print(voucher_ready_text)

save_text("ocr_output.txt", clean_text)
save_text("voucher_ocr_ready.txt", voucher_ready_text)

print("\n已生成：")
print("- ocr_output.txt")
print("- voucher_ocr_ready.txt")
