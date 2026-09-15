# confirmation_address_review_final.py
# 模块3：函证地址差异核实与说明生成模块（最终版后端）
#
# 功能：
# 1. 读取Excel/CSV输入
# 2. 规则预处理与初步地址比对
# 3. 可选接入导航API做地址核实（默认关闭，需自行配置）
# 4. 可选接入AI API生成差异原因与建议处理（默认关闭，需自行配置）
# 5. 导出Excel结果（汇总 + 明细 + 分Sheet）
#
# 输入字段建议：
# - 企业名称
# - 发函地址
# - 回函地址
# - KDC打回原因
# - 备注（可选）
#
# 使用示例：
# python confirmation_address_review_final.py

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

try:
    import requests
except Exception:
    requests = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None


# =========================
# 可配置项
# =========================
INPUT_FILE = "函证地址核查输入.xlsx"
OUTPUT_FILE = "函证地址核查结果.xlsx"

ENABLE_NAV_API = True
ENABLE_AI_EXPLANATION = True

# 导航API配置（高德地图）
# 文档思路：地址解析 / 地理编码
AMAP_API_KEY = os.getenv("AMAP_API_KEY", "")

# AI配置（DeepSeek兼容OpenAI SDK）
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# 规则阈值
SIMILARITY_HIGH = 0.82
SIMILARITY_MEDIUM = 0.58
DISTANCE_SAME_ADDR_METERS = 80
DISTANCE_NEAR_ADDR_METERS = 500


# =========================
# 数据结构
# =========================
@dataclass
class NavVerifyResult:
    success: bool
    geocode1: Optional[Tuple[float, float]] = None
    geocode2: Optional[Tuple[float, float]] = None
    formatted1: str = ""
    formatted2: str = ""
    distance_meters: Optional[float] = None
    conclusion: str = ""
    reason: str = ""


# =========================
# 基础工具
# =========================
def read_input_file(path: str) -> pd.DataFrame:
    lower = path.lower()
    if lower.endswith(".xlsx") or lower.endswith(".xls"):
        return pd.read_excel(path)
    if lower.endswith(".csv"):
        return pd.read_csv(path)
    raise ValueError("仅支持 xlsx/xls/csv 文件")


def normalize_text(text: object) -> str:
    if text is None:
        return ""
    if pd.isna(text):
        return ""
    return str(text).strip()


def clean_address(addr: str) -> str:
    addr = normalize_text(addr)
    if not addr:
        return ""

    addr = addr.replace(" ", "")
    addr = addr.replace("\u3000", "")
    addr = re.sub(r"[（）()]", "", addr)

    # 常见表述清洗
    replacements = {
        "中华人民共和国": "",
        "中国": "",
        "有限责任公司": "",
        "有限公司": "",
        "股份有限公司": "",
        "办公地址": "",
        "注册地址": "",
        "地址：": "",
        "地址:": "",
    }
    for k, v in replacements.items():
        addr = addr.replace(k, v)

    # 统一标点
    addr = addr.replace("，", "").replace(",", "").replace("。", "")
    return addr


def tokenize_address(addr: str) -> List[str]:
    """
    轻量分词：按省市区县路街号栋室等结构切碎。
    """
    a = clean_address(addr)
    if not a:
        return []

    parts = re.split(r"(省|市|区|县|镇|乡|街道|路|街|巷|号|栋|幢|层|室|园|大厦|广场)", a)
    tokens = []
    buf = ""
    for p in parts:
        if not p:
            continue
        buf += p
        if p in {"省", "市", "区", "县", "镇", "乡", "街道", "路", "街", "巷", "号", "栋", "幢", "层", "室", "园", "大厦", "广场"}:
            tokens.append(buf)
            buf = ""
    if buf:
        tokens.append(buf)

    # 去空
    tokens = [t for t in tokens if t]
    return tokens


def jaccard_similarity(a: str, b: str) -> float:
    sa = set(tokenize_address(a))
    sb = set(tokenize_address(b))
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(1, len(sa | sb))


def extract_core_address_features(addr: str) -> Dict[str, str]:
    """
    提取一些关键地址特征，便于规则比对。
    """
    a = clean_address(addr)

    def _search(pattern: str) -> str:
        m = re.search(pattern, a)
        return m.group(1) if m else ""

    province = _search(r"(.+?省)")
    city = _search(r"(.*?市)")
    district = _search(r"(.*?(?:区|县))")
    road = _search(r"([^省市区县]{1,20}?(?:路|街|大道|巷))")
    number = _search(r"(\d{1,5}号)")
    building = _search(r"((?:[A-Za-z]栋|\d+栋|\d+幢))")
    floor_room = _search(r"((?:\d+层|\d+室))")

    return {
        "province": province,
        "city": city,
        "district": district,
        "road": road,
        "number": number,
        "building": building,
        "floor_room": floor_room,
    }


def compare_core_features(a: str, b: str) -> Dict[str, object]:
    fa = extract_core_address_features(a)
    fb = extract_core_address_features(b)

    same_city = bool(fa["city"] and fb["city"] and fa["city"] == fb["city"])
    same_district = bool(fa["district"] and fb["district"] and fa["district"] == fb["district"])
    same_road = bool(fa["road"] and fb["road"] and fa["road"] == fb["road"])
    same_number = bool(fa["number"] and fb["number"] and fa["number"] == fb["number"])
    same_building = bool(fa["building"] and fb["building"] and fa["building"] == fb["building"])

    return {
        "same_city": same_city,
        "same_district": same_district,
        "same_road": same_road,
        "same_number": same_number,
        "same_building": same_building,
        "features_a": fa,
        "features_b": fb,
    }


# =========================
# 规则比对
# =========================
def classify_rule(send_addr: str, reply_addr: str) -> Tuple[str, str, float, str]:
    """
    返回：
    - 规则比对结果：一致 / 疑似一致 / 不一致 / 信息不足
    - 差异类型
    - 相似度
    - 规则说明
    """
    s = clean_address(send_addr)
    r = clean_address(reply_addr)

    if not s or not r:
        return "信息不足", "地址缺失", 0.0, "至少一方地址为空，无法完成规则比对"

    if s == r:
        return "一致", "完全一致", 1.0, "清洗后地址完全一致"

    sim = jaccard_similarity(s, r)
    feature_cmp = compare_core_features(s, r)

    if (
        feature_cmp["same_city"]
        and feature_cmp["same_district"]
        and feature_cmp["same_road"]
        and feature_cmp["same_number"]
    ):
        if feature_cmp["same_building"]:
            return "一致", "核心字段一致", sim, "城市、区县、道路、门牌及楼栋均一致"
        return "疑似一致", "楼栋/楼层差异", sim, "核心地址字段一致，但楼栋或楼层信息存在差异"

    if sim >= SIMILARITY_HIGH:
        return "疑似一致", "格式/表述差异", sim, "地址整体高度相似，疑似为同址不同表述"

    if sim >= SIMILARITY_MEDIUM:
        return "疑似一致", "部分字段差异", sim, "地址存在部分核心字段相同，但仍需进一步核实"

    return "不一致", "明显地址差异", sim, "地址相似度较低，规则判断为明显差异"


# =========================
# 导航API核实（高德）
# =========================
def _ensure_requests():
    if requests is None:
        raise RuntimeError("当前环境未安装 requests，无法调用导航API。")


def amap_geocode(address: str) -> Tuple[Optional[Tuple[float, float]], str]:
    """
    使用高德地理编码。
    返回：
    - (lng, lat) 或 None
    - 格式化地址说明
    """
    _ensure_requests()

    if not AMAP_API_KEY:
        raise RuntimeError("未检测到 AMAP_API_KEY 环境变量。")

    url = "https://restapi.amap.com/v3/geocode/geo"
    params = {
        "key": AMAP_API_KEY,
        "address": address,
    }

    resp = requests.get(url, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    if str(data.get("status")) != "1":
        return None, f"高德返回失败：{data.get('info', 'unknown')}"

    geocodes = data.get("geocodes", [])
    if not geocodes:
        return None, "高德未返回地址解析结果"

    geo = geocodes[0]
    loc = geo.get("location", "")
    if not loc or "," not in loc:
        return None, "高德返回的坐标格式异常"

    lng_str, lat_str = loc.split(",")
    lng, lat = float(lng_str), float(lat_str)

    formatted = " ".join(
        [
            normalize_text(geo.get("province", "")),
            normalize_text(geo.get("city", "")),
            normalize_text(geo.get("district", "")),
            normalize_text(geo.get("formatted_address", "")),
        ]
    ).strip()

    return (lng, lat), formatted


def haversine_meters(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    r = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def nav_verify_addresses(send_addr: str, reply_addr: str) -> NavVerifyResult:
    try:
        geo1, fmt1 = amap_geocode(send_addr)
        geo2, fmt2 = amap_geocode(reply_addr)

        if not geo1 or not geo2:
            return NavVerifyResult(
                success=False,
                formatted1=fmt1,
                formatted2=fmt2,
                conclusion="需人工进一步核实",
                reason="导航API未能稳定解析其中至少一个地址",
            )

        dist = haversine_meters(geo1[0], geo1[1], geo2[0], geo2[1])

        if dist <= DISTANCE_SAME_ADDR_METERS:
            return NavVerifyResult(
                success=True,
                geocode1=geo1,
                geocode2=geo2,
                formatted1=fmt1,
                formatted2=fmt2,
                distance_meters=dist,
                conclusion="一致",
                reason=f"两地址解析后距离约 {dist:.1f} 米，可视为同址",
            )

        if dist <= DISTANCE_NEAR_ADDR_METERS:
            return NavVerifyResult(
                success=True,
                geocode1=geo1,
                geocode2=geo2,
                formatted1=fmt1,
                formatted2=fmt2,
                distance_meters=dist,
                conclusion="疑似一致",
                reason=f"两地址解析后距离约 {dist:.1f} 米，可能为同园区/近址",
            )

        return NavVerifyResult(
            success=True,
            geocode1=geo1,
            geocode2=geo2,
            formatted1=fmt1,
            formatted2=fmt2,
            distance_meters=dist,
            conclusion="不一致",
            reason=f"两地址解析后距离约 {dist:.1f} 米，差异较大",
        )

    except Exception as e:
        return NavVerifyResult(
            success=False,
            conclusion="需人工进一步核实",
            reason=f"导航API调用失败：{e}",
        )


# =========================
# AI说明生成
# =========================
def get_ai_client():
    if OpenAI is None:
        raise RuntimeError("当前环境未安装 openai SDK，无法调用AI。")
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("未检测到 DEEPSEEK_API_KEY 环境变量。")
    return OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)


def build_ai_prompt(row: Dict[str, object]) -> str:
    return f"""
你是审计函证差异说明助手。请基于以下结构化信息，输出严格JSON，生成：
1. 综合结论
2. 自动生成原因
3. 建议处理

要求：
- 使用中文
- 语言简洁、专业、克制
- 面向项目组填写说明口径
- 只基于提供信息判断，不得编造
- 如果证据不足，应保守输出“需人工进一步核实”
- 不要使用“舞弊”“违规”等严重定性

输出格式：
{{
  "综合结论": "...",
  "自动生成原因": "...",
  "建议处理": "..."
}}

输入信息：
企业名称：{row.get("企业名称", "")}
发函地址：{row.get("发函地址", "")}
回函地址：{row.get("回函地址", "")}
KDC打回原因：{row.get("KDC打回原因", "")}
规则比对结果：{row.get("规则比对结果", "")}
差异类型：{row.get("差异类型", "")}
规则相似度：{row.get("规则相似度", "")}
规则说明：{row.get("规则说明", "")}
导航核实结果：{row.get("导航核实结果", "")}
导航说明：{row.get("导航说明", "")}
导航距离(米)：{row.get("导航距离(米)", "")}
""".strip()


def fallback_explanation(row: Dict[str, object]) -> Dict[str, str]:
    rule_res = normalize_text(row.get("规则比对结果", ""))
    nav_res = normalize_text(row.get("导航核实结果", ""))
    diff_type = normalize_text(row.get("差异类型", ""))

    if nav_res == "一致" or rule_res == "一致":
        return {
            "综合结论": "一致",
            "自动生成原因": "经比对，发函地址与回函地址核心地址信息一致，差异主要系表述方式不同或格式差异。",
            "建议处理": "建议项目组按地址表述差异说明，并继续后续流程。",
        }

    if nav_res == "疑似一致" or rule_res == "疑似一致":
        return {
            "综合结论": "疑似一致",
            "自动生成原因": f"经比对，两地址存在{diff_type or '表述差异'}，核心位置信息相近，但仍建议结合项目实际情况确认。",
            "建议处理": "建议项目组补充说明差异原因，并提交经理复核。",
        }

    if rule_res == "信息不足":
        return {
            "综合结论": "需人工进一步核实",
            "自动生成原因": "当前地址信息不完整或无法稳定比对，暂不足以形成明确说明。",
            "建议处理": "建议项目组补充地址信息后再判断。",
        }

    return {
        "综合结论": "不一致",
        "自动生成原因": "经比对，发函地址与回函地址差异较大，现有信息下难以认定为同一地址。",
        "建议处理": "建议项目组进一步核实地址来源、主体关系及差异原因后再提交。",
    }


def ai_generate_explanation(row: Dict[str, object]) -> Dict[str, str]:
    client = get_ai_client()
    prompt = build_ai_prompt(row)

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": "你是严谨、克制、专业的审计函证差异说明助手。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        stream=False,
    )

    text = (response.choices[0].message.content or "").strip()
    try:
        data = json.loads(text)
        return {
            "综合结论": normalize_text(data.get("综合结论", "")),
            "自动生成原因": normalize_text(data.get("自动生成原因", "")),
            "建议处理": normalize_text(data.get("建议处理", "")),
        }
    except Exception:
        return fallback_explanation(row)


# =========================
# 主处理流程
# =========================
REQUIRED_COLUMNS = ["企业名称", "发函地址", "回函地址", "KDC打回原因"]


def prepare_input_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    for col in REQUIRED_COLUMNS:
        if col not in out.columns:
            out[col] = ""

    if "备注" not in out.columns:
        out["备注"] = ""

    for col in REQUIRED_COLUMNS + ["备注"]:
        out[col] = out[col].apply(normalize_text)

    return out


def process_address_review(
    df: pd.DataFrame,
    enable_nav_api: bool = ENABLE_NAV_API,
    enable_ai_explanation: bool = ENABLE_AI_EXPLANATION,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    out = prepare_input_df(df)

    rule_results = []
    diff_types = []
    sims = []
    rule_reasons = []

    nav_results = []
    nav_reasons = []
    nav_dists = []

    final_conclusions = []
    generated_reasons = []
    actions = []

    for _, row in out.iterrows():
        rule_res, diff_type, sim, rule_reason = classify_rule(
            row.get("发函地址", ""),
            row.get("回函地址", ""),
        )
        rule_results.append(rule_res)
        diff_types.append(diff_type)
        sims.append(round(sim, 3))
        rule_reasons.append(rule_reason)

        if enable_nav_api:
            nav = nav_verify_addresses(row.get("发函地址", ""), row.get("回函地址", ""))
            nav_results.append(nav.conclusion)
            nav_reasons.append(nav.reason)
            nav_dists.append(round(nav.distance_meters, 1) if nav.distance_meters is not None else "")
        else:
            nav_results.append("")
            nav_reasons.append("未启用导航API")
            nav_dists.append("")

    out["规则比对结果"] = rule_results
    out["差异类型"] = diff_types
    out["规则相似度"] = sims
    out["规则说明"] = rule_reasons
    out["导航核实结果"] = nav_results
    out["导航说明"] = nav_reasons
    out["导航距离(米)"] = nav_dists

    for _, row in out.iterrows():
        row_dict = row.to_dict()
        if enable_ai_explanation:
            try:
                ai_res = ai_generate_explanation(row_dict)
            except Exception:
                ai_res = fallback_explanation(row_dict)
        else:
            ai_res = fallback_explanation(row_dict)

        final_conclusions.append(ai_res["综合结论"])
        generated_reasons.append(ai_res["自动生成原因"])
        actions.append(ai_res["建议处理"])

    out["综合结论"] = [normalize_conclusion(x) for x in final_conclusions]
    out["自动生成原因"] = generated_reasons
    out["建议处理"] = actions

    # 统一清洗，防止历史脏值污染汇总sheet
    out["综合结论"] = out["综合结论"].apply(normalize_conclusion)

    summary_df = (
        out.groupby("综合结论")
        .agg(
            数量=("企业名称", "count"),
            涉及企业=("企业名称", lambda x: "；".join([str(i) for i in x if str(i).strip()])),
        )
        .reset_index()
        .sort_values(by="数量", ascending=False)
        .reset_index(drop=True)
    )

    return out, summary_df



def normalize_conclusion(text: object) -> str:
    """
    将AI可能输出的脏结论归一化到固定类别，避免汇总sheet污染。
    """
    t = normalize_text(text)
    if not t:
        return "需人工进一步核实"

    if "疑似" in t:
        return "疑似一致"
    if "不一致" in t:
        return "不一致"
    if "一致" in t:
        return "一致"
    if "人工" in t or "进一步核实" in t or "核实" in t:
        return "需人工进一步核实"
    return "需人工进一步核实"


def safe_sheet_name(name: object) -> str:
    r"""
    Excel sheet名不允许包含: \ / * ? : [ ]
    同时避免空白sheet名。
    """
    text = normalize_text(name)
    if not text:
        text = "未分类"
    text = re.sub(r'[\\/*?:\[\]]', "_", text)
    text = text[:31]
    return text or "未分类"

# =========================
# 导出
# =========================
SHEET_ORDER = ["需人工进一步核实", "不一致", "疑似一致", "一致"]


def export_result_excel(result_df: pd.DataFrame, summary_df: pd.DataFrame, output_file: str):
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="汇总", index=False)

        used_sheet_names = {"汇总"}

        for status in SHEET_ORDER:
            sub = result_df[result_df["综合结论"] == status]
            if not sub.empty:
                sheet_name = safe_sheet_name(status)
                if sheet_name not in used_sheet_names:
                    sub.to_excel(writer, sheet_name=sheet_name, index=False)
                    used_sheet_names.add(sheet_name)

        others = [
            x for x in result_df["综合结论"].dropna().unique().tolist()
            if normalize_conclusion(x) not in SHEET_ORDER
        ]
        for status in others:
            sub = result_df[result_df["综合结论"] == status]
            if not sub.empty:
                sheet_name = safe_sheet_name(status)
                if sheet_name not in used_sheet_names:
                    sub.to_excel(writer, sheet_name=sheet_name, index=False)
                    used_sheet_names.add(sheet_name)

        result_df.to_excel(writer, sheet_name="全部明细", index=False)


# =========================
# 运行入口
# =========================
def main():
    if not Path(INPUT_FILE).exists():
        demo_df = pd.DataFrame([
            {
                "企业名称": "某科技有限公司",
                "发函地址": "上海市浦东新区XX路100号A栋",
                "回函地址": "上海市浦东新区XX路100号",
                "KDC打回原因": "地址不一致，请说明原因",
                "备注": "",
            },
            {
                "企业名称": "某贸易有限公司",
                "发函地址": "北京市朝阳区XX街88号",
                "回函地址": "上海市闵行区YY路66号",
                "KDC打回原因": "地址差异较大，请进一步核实",
                "备注": "",
            },
        ])
        demo_df.to_excel(INPUT_FILE, index=False)
        print(f"未检测到输入文件，已自动生成模板：{INPUT_FILE}")
        print("请先填入数据后重新运行。")
        return

    df = read_input_file(INPUT_FILE)
    result_df, summary_df = process_address_review(
        df,
        enable_nav_api=ENABLE_NAV_API,
        enable_ai_explanation=ENABLE_AI_EXPLANATION,
    )
    export_result_excel(result_df, summary_df, OUTPUT_FILE)

    print("=== 模块3：函证地址差异核查汇总 ===")
    print(summary_df.to_string(index=False))
    print(f"\n已导出：{OUTPUT_FILE}")

    print("\n当前配置：")
    print(f"- ENABLE_NAV_API = {ENABLE_NAV_API}")
    print(f"- ENABLE_AI_EXPLANATION = {ENABLE_AI_EXPLANATION}")


if __name__ == "__main__":
    main()
