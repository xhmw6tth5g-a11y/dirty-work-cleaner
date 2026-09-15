from bottle import route, run, template, request, TEMPLATE_PATH
from dotenv import load_dotenv
import sys
import os
import tempfile
from pathlib import Path
from io import BytesIO
import shutil

import pandas as pd

load_dotenv()

# 统一改用绝对路径：原先的 './templates' / './modules' 依赖启动时的工作目录，
# 从其他目录启动（或在 IDE 里直接 Run）会找不到模板与模块。
BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH.insert(0, str(BASE_DIR / 'templates'))
sys.path.append(str(BASE_DIR / 'modules'))

# ===== 核心模块 =====
from module2_core import process
from paper_voucher_service import (
    build_paper_voucher_payload,
    build_paper_summary_df,
    build_paper_log_df,
)
from deepseek_service_paper import generate_paper_attachment_ai_review

from consistency_check_core import check_consistency
from consistency_ai_review import enrich_consistency_reviews

from ocr_bridge import (
    clean_ocr_text,
    build_voucher_ready_text,
    extract_voucher_no,
    extract_date,
    extract_amount,
    guess_expense_type,
)

from confirmation_address_review_final import process_address_review
from module5_enterprise_info_filler import process_company_info
from supporting_module_ai_v2 import run_supporting_pipeline
from DWCAIcenter import DWCAIcenter
from result_store import save_consistency, save_address, save_supporting

try:
    from paddleocr import PaddleOCR
except Exception:
    PaddleOCR = None

OCR_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_ocr_instance = None


def _to_bool(x):
    if x is None:
        return False
    return str(x).strip().lower() in {"1", "true", "yes", "y", "是", "on"}


def _form_text(name: str, default: str = "") -> str:
    """读取表单里的文本字段，并纠正 Bottle 的中文乱码。

    Bottle 的 POST 解析对非 multipart 的请求体是**按 latin1 硬解码**的
    （bottle.py 的 `POST` 属性里写死 `tonat(body, 'latin1')`），中文因此变成
    乱码：'系统总结' -> 'ç³»ç»Ÿæ€»ç»“'。
    带文件上传的表单走 multipart 分支，不受影响——本项目 8 个页面里只有
    AI 助手那个表单没写 enctype，所以只有它会中招。

    `getunicode()` 是 Bottle 自带的还原入口（latin1 解回再按 utf8 解），
    对已经正确的字符串会原样返回，两种情况都安全。
    新增 urlencoded 表单字段时，请一律走这个函数。
    """
    try:
        return request.forms.getunicode(name, default) or default
    except Exception:
        return request.forms.get(name, default) or default


def _safe_table(df: pd.DataFrame) -> str:
    return df.to_html(index=False, classes="result-table")


# 各模块跑完把结果交给全局 AI 助手。没有这一步，AI 助手拿不到任何数据，
# 对什么提问都只能回答"当前无法形成判断"。
_AI_RESULT_SINKS = {
    "consistency": save_consistency,
    "address": save_address,
    "supporting": save_supporting,
}


def _save_for_ai(kind: str, df) -> None:
    """把本次结果存进 AI 助手的暂存区。存档失败不应该影响页面本身。"""
    try:
        _AI_RESULT_SINKS[kind](df)
    except Exception:
        pass


def _file_ext(name: str) -> str:
    return Path(name or "").suffix.lower()


# Bottle 的 multipart 解析会丢弃文件名里的非 ASCII 字节，中文文件名会被改写。
# 实测：'抽样清单.xlsx' -> 'xlsx'（扩展名丢失），'模拟抽凭清单_一致性测试.xlsx' -> '_.xlsx'。
# 仅靠文件名后缀判断类型会误报「仅支持 xlsx / xls / csv」，因此加一层按文件头的嗅探兜底。
_KNOWN_EXTS = {".csv", ".xlsx", ".xls", ".txt"} | {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_SNIFF_MAP = {
    b"PK\x03\x04": ".xlsx",
    b"\xd0\xcf\x11\xe0": ".xls",
    b"\x89PNG\r\n": ".png",
    b"\xff\xd8\xff": ".jpg",
    b"BM": ".bmp",
}


def _sniff_ext(filename: str, data: bytes) -> str:
    """优先用文件名后缀；后缀不可信时按文件头 / 文本特征推断。"""
    ext = _file_ext(filename)
    if ext in _KNOWN_EXTS:
        return ext
    for magic, guess in _SNIFF_MAP.items():
        if data.startswith(magic):
            return guess
    try:
        data.decode("utf-8")
        return ".txt"
    except Exception:
        return ext


def _metric_card(title: str, value) -> str:
    return f"""
    <div class="metric-card">
        <div class="metric-title">{title}</div>
        <div class="metric-value">{value}</div>
    </div>
    """


def _read_upload_to_df(upload):
    if not upload or not upload.filename:
        raise ValueError("文件未上传")
    data = upload.file.read()
    ext = _sniff_ext(upload.filename, data)
    bio = BytesIO(data)
    if ext == ".csv":
        return pd.read_csv(bio)
    if ext in {".xlsx", ".xls"}:
        return pd.read_excel(bio)
    raise ValueError(f"仅支持 xlsx / xls / csv 文件（实际识别为：{ext or '未知'}）")


def _get_ocr():
    global _ocr_instance
    if _ocr_instance is None:
        if PaddleOCR is None:
            raise RuntimeError("当前服务器未安装 PaddleOCR，无法处理图片。")
        _ocr_instance = PaddleOCR(lang="ch", use_textline_orientation=True)
    return _ocr_instance


def _extract_raw_text_from_result(result) -> str:
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


def _ocr_upload(upload) -> str:
    data = upload.file.read()
    return _ocr_upload_bytes(data, _sniff_ext(upload.filename, data) or ".png")


def _ocr_upload_bytes(data: bytes, suffix: str = ".png") -> str:
    ocr = _get_ocr()
    suffix = suffix if suffix.startswith(".") else "." + suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        result = ocr.predict(tmp_path)
        raw_text = _extract_raw_text_from_result(result)
        return clean_ocr_text(raw_text)
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass


def _read_ocr_file(upload):
    data = upload.file.read()
    ext = _sniff_ext(upload.filename, data)
    if ext == ".txt":
        return clean_ocr_text(data.decode("utf-8", errors="ignore"))
    if ext in OCR_IMAGE_EXTS:
        return _ocr_upload_bytes(data, ext)
    raise ValueError(f"暂不支持的文件类型：{ext or '未知'}")


def _save_uploads_to_temp_dir(upload_list):
    temp_dir = tempfile.mkdtemp(prefix="dwc_upload_")
    saved_files = []
    for upload in upload_list:
        if upload and upload.filename:
            target = Path(temp_dir) / Path(upload.filename).name
            with open(target, "wb") as f:
                f.write(upload.file.read())
            saved_files.append(str(target))
    return temp_dir, saved_files


# ===== 首页 =====
@route('/')
def index():
    return template('index')


# ===== 凭证核查 =====
@route('/voucher')
def voucher():
    return template('voucher')


@route('/run_voucher', method='POST')
def run_voucher():
    try:
        voucher_file = request.files.get('voucher')

        payload = build_paper_voucher_payload(
            form=request.forms,
            voucher_file=voucher_file,
        )

        prefill_df = payload["prefill_df"]
        summary_df = build_paper_summary_df(payload)
        log_df = build_paper_log_df(payload)

        result_df, summary2_df, risk_df = process(prefill_df)

        try:
            ai_text = generate_paper_attachment_ai_review(
                result_df.iloc[0].to_dict(),
                log_df.iloc[0].to_dict()
            )
        except Exception as e:
            ai_text = f"AI调用失败：{e}"

        return template(
            'voucher',
            result=_safe_table(result_df),
            summary=_safe_table(summary_df),
            ai=ai_text
        )

    except Exception as e:
        return template('voucher', error=f"运行出错：{e}")


# ===== 一致性检查 =====
@route('/consistency')
def consistency():
    return template('consistency')


@route('/run_consistency', method='POST')
def run_consistency():
    try:
        sampling_file = request.files.get('sampling_file')
        voucher_file = request.files.get('voucher_file')
        enable_ai = _to_bool(request.forms.get('enable_ai'))
        amount_tolerance = float(str(request.forms.get('amount_tolerance') or '0.01').strip())

        if not sampling_file or not voucher_file:
            return template('consistency', error="请同时上传抽凭清单和实际凭证表")

        sampling_df = _read_upload_to_df(sampling_file)
        voucher_df = _read_upload_to_df(voucher_file)

        result_df, summary_df = check_consistency(sampling_df, voucher_df, amount_tolerance=amount_tolerance)

        if enable_ai:
            result_df = enrich_consistency_reviews(result_df)

        _save_for_ai("consistency", result_df)

        total_count = len(result_df)
        abnormal_df = result_df[result_df["一致性状态"] != "一致"].copy()
        abnormal_count = len(abnormal_df)
        abnormal_rate = f"{round((abnormal_count / total_count) * 100)}%" if total_count else "0%"

        def _count(status):
            return int((result_df["一致性状态"] == status).sum())

        metric_cards = "".join([
            _metric_card("总样本", total_count),
            _metric_card("异常数", abnormal_count),
            _metric_card("异常率", abnormal_rate),
            _metric_card("凭证缺失", _count("凭证缺失")),
            _metric_card("金额不一致", _count("金额不一致")),
        ])

        if total_count == 0:
            # 零行时必须单独说明。否则会走到下面的"整体一致"分支，
            # 把"什么都没读到"说成"没有异常"，对审计场景是误导。
            ai_text = """【结论】
未读取到可检查的样本。

【原因】
抽凭清单或实际凭证表为空，本次没有产生任何比对行。

【建议下一步】
确认上传文件的 Sheet 是否有数据；并检查抽凭清单的列名是否为
「凭证号 / 底稿金额 / 底稿日期」——若误用「凭证金额 / 凭证日期」，
匹配行会全部落入「需人工复核」。"""
        elif abnormal_df.empty:
            ai_text = """【结论】
当前样本整体一致，未见明显异常。

【原因】
抽凭清单与实际凭证记录未发现高优先级差异。

【建议下一步】
可继续后续底稿流程，并保留本次检查结果。"""
        else:
            top_status = abnormal_df["一致性状态"].value_counts().idxmax()
            top_vouchers = "，".join(abnormal_df["凭证号"].astype(str).head(8).tolist())
            ai_text = f"""【结论】
当前样本存在异常，优先关注 {top_status}。

【原因】
异常样本共 {abnormal_count} 条，主要涉及：{top_vouchers}。

【建议下一步】
优先核对异常样本与原始底稿来源，必要时补充凭证或修正底稿记录。"""

        return template(
            'consistency',
            metric_cards=metric_cards,
            summary_html=_safe_table(summary_df),
            detail_html=_safe_table(result_df),
            ai_text=ai_text,
        )

    except Exception as e:
        return template('consistency', error=f"运行出错：{e}")


# ===== OCR处理 =====
@route('/ocr')
def ocr_page():
    return template('ocr')


@route('/run_ocr', method='POST')
def run_ocr():
    try:
        uploads = []
        single = request.files.get('ocr_file')
        multi = request.files.getall('ocr_files')

        if single and single.filename:
            uploads.append(single)
        for f in multi:
            if f and f.filename:
                uploads.append(f)

        if not uploads:
            return template('ocr', error="请先上传文件")

        first = uploads[0]
        raw_text = _read_ocr_file(first)
        standard_text = build_voucher_ready_text(raw_text)

        voucher_no = extract_voucher_no(raw_text)
        voucher_date = extract_date(raw_text) or ""
        voucher_amount = extract_amount(raw_text)
        expense_type = guess_expense_type(raw_text)

        warnings = []
        if voucher_no == "AUTO":
            warnings.append("凭证号未稳定识别，已回退为 AUTO")
        if not voucher_date:
            warnings.append("日期未识别")
        if voucher_amount is None:
            warnings.append("金额未识别")
        if expense_type == "其他":
            warnings.append("费用类型未稳定识别")

        field_df = pd.DataFrame([{
            "凭证号": voucher_no,
            "日期": voucher_date,
            "金额": "" if voucher_amount is None else voucher_amount,
            "费用类型": expense_type,
        }])

        warning_html = "<ul>" + "".join([f"<li>{w}</li>" for w in warnings]) + "</ul>" if warnings else "<div>未发现明显识别异常</div>"

        return template(
            'ocr',
            upload_count=len(uploads),
            success_count=max(0, len(uploads) - (1 if warnings else 0)),
            warning_count=1 if warnings else 0,
            ocr_raw_text=raw_text,
            field_html=_safe_table(field_df),
            standard_text=standard_text,
            warning_html=warning_html,
        )

    except Exception as e:
        return template('ocr', error=f"运行出错：{e}")


# ===== 地址核查 =====
@route('/address')
def address():
    return template('address')


@route('/run_address', method='POST')
def run_address():
    temp_dir = None
    try:
        address_file = request.files.get('address_file')
        ai_enabled = _to_bool(request.forms.get('ai_enabled'))

        if not address_file or not address_file.filename:
            return template('address', error="请上传地址核查文件")

        df = _read_upload_to_df(address_file)
        result_df, summary_df = process_address_review(
            df=df,
            enable_nav_api=True,
            enable_ai_explanation=ai_enabled,
        )

        _save_for_ai("address", result_df)

        ai_text = "已基于规则比对、导航核实及AI说明生成当前结果。"
        if not ai_enabled:
            ai_text = "当前已关闭 AI 说明，结果仅基于规则比对与导航核实。"

        return template(
            'address',
            ai_text=ai_text,
            summary_html=_safe_table(summary_df),
            detail_html=_safe_table(result_df),
        )
    except Exception as e:
        return template('address', error=f"运行出错：{e}")


# ===== 企业信息填列 =====
@route('/company')
def company():
    return template('company')


@route('/run_company', method='POST')
def run_company():
    temp_dir = None
    try:
        uploads = request.files.getall('company_file')
        valid_uploads = [f for f in uploads if f and f.filename]

        if not valid_uploads:
            return template('company', error="请至少上传一个企业信息文件")

        temp_dir, _ = _save_uploads_to_temp_dir(valid_uploads)
        result_df, summary_df = process_company_info(temp_dir)

        return template(
            'company',
            summary_html=_safe_table(summary_df),
            result_html=_safe_table(result_df),
        )
    except Exception as e:
        return template('company', error=f"运行出错：{e}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


# ===== Supporting整理 =====
@route('/supporting')
def supporting():
    return template('supporting')


@route('/run_supporting', method='POST')
def run_supporting():
    source_dir = None
    try:
        uploads = request.files.getall('supporting_files')
        ai_enabled = _to_bool(request.forms.get('ai_enabled'))
        valid_uploads = [f for f in uploads if f and f.filename]

        if not valid_uploads:
            return template('supporting', error="请至少上传一个 supporting 文件")

        source_dir, _ = _save_uploads_to_temp_dir(valid_uploads)
        output_dir = os.path.join(source_dir, "supporting_output")
        output_excel = os.path.join(source_dir, "货币supporting底稿_AI收口版.xlsx")

        classified_df, workpaper_df, missing_df = run_supporting_pipeline(
            source_dir=source_dir,
            output_dir=output_dir,
            output_excel=output_excel,
            copy_instead_of_move=True,
            enable_ai_assist=ai_enabled,
        )

        _save_for_ai("supporting", workpaper_df)

        return template(
            'supporting',
            classify_html=_safe_table(classified_df),
            draft_html=_safe_table(workpaper_df),
            missing_html=_safe_table(missing_df if not missing_df.empty else pd.DataFrame([{"提示": "无缺失"}])),
        )
    except Exception as e:
        return template('supporting', error=f"运行出错：{e}")
    finally:
        # 保留输出目录用于调试时可以注释掉下一行
        if source_dir and os.path.exists(source_dir):
            shutil.rmtree(source_dir, ignore_errors=True)


# ===== DWCAIcenter =====
@route('/ai')
def ai():
    return template('ai')


@route('/run_ai', method='POST')
def run_ai():
    try:
        question = _form_text('question').strip()
        if not question:
            return template('ai', answer="请输入问题。")

        bot = DWCAIcenter()
        bot.load_default()
        answer = bot.ask(question)

        return template('ai', answer=answer)
    except Exception as e:
        return template('ai', answer=f"AI运行出错：{e}")


if __name__ == '__main__':
    # 启动参数改为环境变量可配，默认只监听本机、关闭 debug：
    #   DWC_HOST   默认 127.0.0.1（部署到服务器时设为 0.0.0.0）
    #   DWC_PORT   默认 8080
    #   DWC_DEBUG  默认关闭；本地调试设 1 打开（会连同热重载一起开）
    HOST = os.getenv('DWC_HOST', '127.0.0.1')
    PORT = int(os.getenv('DWC_PORT', '8080'))
    DEBUG = os.getenv('DWC_DEBUG', '').strip().lower() in {'1', 'true', 'yes', 'on'}

    print(f'Dirty Work Cleaner 启动中 —— http://{HOST}:{PORT}/')
    if HOST == '0.0.0.0' and DEBUG:
        print('警告：当前绑定全网卡且开启 debug，请勿暴露到公网。')

    run(host=HOST, port=PORT, debug=DEBUG, reloader=DEBUG)
