
# DWCAIcenter.py（强化版：去“弱智回答”，强审计风格）

import json, os
from pathlib import Path
import pandas as pd
from typing import Dict, Any, Optional

try:
    from openai import OpenAI
except:
    OpenAI = None


# ===== 模块标准命名（关键升级）=====
MODULE_CATALOG = {
    "module1": "模块1：凭证结构化（OCR）",
    "module2": "模块2：一致性检查（抽凭 / Docu）",
    "module3": "模块3：完整性核查（附件 / 金额覆盖）",
    "module4": "模块4：函证地址核查",
    "module5": "模块5：企业信息核查",
    "module6": "模块6：supporting整理",
    "module7": "模块7：DWCAIcenter（系统AI助手）",
}

# ===== 强约束AI提示词 =====
SYSTEM_PROMPT = """
你是DWCAIcenter，一个审计执行助手。

回答规则（必须遵守）：
1. 第一行必须给“明确结论”
2. 禁止说“根据上下文”“当前数据”等废话
3. 禁止复述字段
4. 必须像审计人员说话
5. 输出结构必须是：

【结论】
【原因】
【建议下一步】

如果数据不足，直接说：
“当前无法形成判断”
"""

def get_client():
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        return None
    return OpenAI(api_key=key, base_url="https://api.deepseek.com")


def normalize(x):
    if x is None:
        return ""
    try:
        if pd.isna(x):
            return ""
    except:
        pass
    return str(x)


class DWCAIcenter:

    def __init__(self):
        self.consistency = None
        self.address = None
        self.supporting = None

    def load_default(self):
        """加载核查结果：先取进程内暂存，取不到再回退读磁盘文件。

        Web 版的各条路由只把结果渲染进页面、不落盘，所以进程内暂存是
        Web 流程下的唯一数据来源；磁盘回退是为命令行用法保留的
        （先用 CLI 脚本跑出结果文件，再启动本助手）。
        """
        self.consistency = None
        self.address = None
        self.supporting = None

        try:
            from result_store import get_results
            stored = get_results()
        except Exception:
            stored = {}

        self.consistency = stored.get("consistency")
        self.address = stored.get("address")
        self.supporting = stored.get("supporting")

        if self.consistency is None and Path("一致性检查结果_分Sheet_AI版.xlsx").exists():
            self.consistency = pd.read_excel("一致性检查结果_分Sheet_AI版.xlsx", sheet_name="全部明细")

        if self.address is None and Path("函证地址核查结果.xlsx").exists():
            self.address = pd.read_excel("函证地址核查结果.xlsx", sheet_name="全部明细")

        if self.supporting is None and Path("货币supporting底稿_AI收口版.xlsx").exists():
            self.supporting = pd.read_excel("货币supporting底稿_AI收口版.xlsx")

    def _status_line(self) -> str:
        """把已加载的结果汇总成一句话；一条都没有时返回空串。"""
        parts = []

        if self.consistency is not None and "一致性状态" in self.consistency.columns:
            abnormal = int((self.consistency["一致性状态"] != "一致").sum())
            parts.append("一致性检查 %d 条样本（异常 %d 条）" % (len(self.consistency), abnormal))
        elif self.consistency is not None:
            parts.append("一致性检查 %d 条样本" % len(self.consistency))

        if self.address is not None:
            parts.append("函证地址核查 %d 条" % len(self.address))

        if self.supporting is not None:
            parts.append("supporting 底稿 %d 条" % len(self.supporting))

        return "；".join(parts)

    # ===== 强规则回答（核心升级）=====
    def quick_answer(self, q: str):

        # 系统模块
        if "模块" in q:
            return "\n".join(MODULE_CATALOG.values())

        # 总结
        if "总结" in q or "系统" in q:
            status = self._status_line()
            if not status:
                return "【结论】系统尚未形成可分析结果\n【原因】未加载模块数据\n【建议下一步】请先导入核查结果"
            return (
                "【结论】本次会话已完成：%s\n"
                "【原因】上述统计只覆盖已执行过的模块，未执行的模块不计入。\n"
                "【建议下一步】如需定位具体异常，可直接问「重点异常有哪些」。" % status
            )

        # Docu
        if "docu" in q.lower():
            if self.consistency is None:
                return "【结论】无法判断\n【原因】一致性数据未加载\n【建议下一步】请加载一致性结果"

            if "一致性状态" not in self.consistency.columns or "凭证号" not in self.consistency.columns:
                return "【结论】无法判断\n【原因】一致性结果缺少「凭证号 / 一致性状态」列\n【建议下一步】请确认导入的是本系统导出的结果"

            bad = self.consistency[self.consistency["一致性状态"].isin(["凭证缺失","金额不一致","需人工复核"])]
            if bad.empty:
                return "【结论】当前样本可进入Docu\n【原因】未发现异常\n【建议下一步】可继续流程"

            lst = "，".join(bad["凭证号"].astype(str).head(10))
            return f"【结论】部分样本不宜进入Docu\n【原因】存在异常：{lst}\n【建议下一步】优先核查异常样本"

        return None

    def ask(self, q: str):

        fast = self.quick_answer(q)
        if fast:
            return fast

        payload = {
            "consistency": self.consistency.head(5).to_dict() if self.consistency is not None else None,
            "address": self.address.head(5).to_dict() if self.address is not None else None,
        }

        client = get_client()
        if not client:
            return json.dumps(payload, ensure_ascii=False, indent=2)

        prompt = f"问题：{q}\n数据：{json.dumps(payload, ensure_ascii=False)}"

        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role":"system","content":SYSTEM_PROMPT},
                {"role":"user","content":prompt}
            ],
            temperature=0.1
        )

        return resp.choices[0].message.content


def main():
    c = DWCAIcenter()
    c.load_default()

    print("DWCAIcenter 已启动")

    while True:
        q = input("你：")
        if q == "exit":
            break
        print(c.ask(q))


if __name__ == "__main__":
    main()
