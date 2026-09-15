"""进程级核查结果暂存。

**为什么需要它**

Web 版的各条路由只把结果渲染进页面返回给浏览器，不写任何文件；
而全局 AI 助手（DWCAIcenter）需要读到"刚跑完那一步"的结果才能做解释。
两者之间原本没有任何通道，导致 AI 助手拿到的永远是空数据。

本模块充当这个转接头：路由跑完把 DataFrame 放进来，AI 助手读出去。

**为什么是内存而不是落盘**

审计执行是逐项作业，助手回答的应该是"最近一次"的结论，而不是历史文件里
任意一份。保持进程内、只留最新一次，语义最准，也不会在磁盘上留下
客户敏感数据（计划书 5.3 的最小化处理原则）。

只对本进程有效：适合单进程原型部署；将来若换多进程 WSGI 服务器，
把这里的读写换成 Redis 或数据库即可，调用方不用改。
"""

from datetime import datetime
from typing import Dict, Optional

import pandas as pd

# 与 DWCAIcenter 期待的三个数据来源一一对应
_KEYS = ("consistency", "address", "supporting")

_results: Dict[str, Optional[pd.DataFrame]] = {k: None for k in _KEYS}
_saved_at: Dict[str, Optional[str]] = {k: None for k in _KEYS}


def _normalize(df) -> Optional[pd.DataFrame]:
    """只接受 DataFrame；空表也算有效结果（"跑了但没异常"本身就是结论）。"""
    if not isinstance(df, pd.DataFrame):
        return None
    return df.copy()


def save(key: str, df) -> bool:
    """存入某个模块的最近一次结果，返回是否真的存进去了。"""
    if key not in _KEYS:
        raise KeyError("未知结果槽位：%s（可选：%s）" % (key, ", ".join(_KEYS)))
    clean = _normalize(df)
    _results[key] = clean
    _saved_at[key] = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if clean is not None else None
    return clean is not None


def save_consistency(df) -> bool:
    """存一致性检查结果（对应 AI 助手读的"全部明细"）。"""
    return save("consistency", df)


def save_address(df) -> bool:
    """存函证地址核查结果。"""
    return save("address", df)


def save_supporting(df) -> bool:
    """存 supporting 底稿。"""
    return save("supporting", df)


def get(key: str) -> Optional[pd.DataFrame]:
    return _results.get(key)


def get_results() -> Dict[str, Optional[pd.DataFrame]]:
    """返回三个槽位的当前值；没跑过的模块是 None。"""
    return dict(_results)


def stats() -> Dict[str, Optional[dict]]:
    """每个槽位的行数与存入时间，供"系统状态"类问题快速回答。"""
    out: Dict[str, Optional[dict]] = {}
    for k in _KEYS:
        df = _results[k]
        out[k] = None if df is None else {
            "rows": int(len(df)),
            "columns": list(map(str, df.columns))[:12],
            "saved_at": _saved_at[k],
        }
    return out


def clear() -> None:
    """清空全部槽位（测试或多项目切换时用）。"""
    for k in _KEYS:
        _results[k] = None
        _saved_at[k] = None
