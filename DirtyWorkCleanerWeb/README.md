# Dirty Work Cleaner —— Web 版

面向审计执行流程的辅助审阅工具。把凭证、附件、抽凭清单等资料的信息识别、规则核查、
一致性勾稽、异常提示和结果解释，从「人工逐笔处理」转为「系统预处理 + 人工复核」。

> **定位边界**：本系统是执行辅助工具，不是结论形成工具。
> 系统输出的摘要与建议不构成正式审计意见，关键判断由人工复核确认。

---

## 1. 目录结构

`DirtyWorkCleanerWeb/` 内部：

```
app.py                 单文件路由：8 个页面 + 7 条 POST 处理路由
modules/               业务模块（20 个 .py），运行时由 app.py 加载
templates/             Bottle SimpleTemplate 模板（9 个，CSS/JS 内联）
static/                空目录（预留，当前无独立静态资源）
routes/                空目录（预留，当前路由都写在 app.py）
requirements.txt       依赖清单（已实测版本组合）
.env.example           环境变量模板
run.bat                Windows 一键启动
```

上游脚本原型与测试样例位于同级目录 `../DirtyWorkCleaner/`。

---

## 2. 快速开始

### 方式一：一键启动（推荐）

双击 `run.bat`。首次运行会自动建虚拟环境 `.venv`、装依赖，然后启动并打开浏览器。
之后每次直接双击即可。

### 方式二：手动启动

```bat
cd DirtyWorkCleanerWeb
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
.venv\Scripts\python.exe app.py
```

看到 `Dirty Work Cleaner 启动中 —— http://127.0.0.1:8080/` 即为启动成功。

### 方式三：IDE 里直接 Run `app.py`

`app.py` 用 `Path(__file__).parent` 定位模板和模块目录，不依赖启动时的工作目录；
服务启动代码包在 `if __name__ == '__main__':` 内，因此可以安全地被 import。

### 配置 API Key

```bat
cd DirtyWorkCleanerWeb
copy .env.example .env
```

然后编辑 `.env` 填入 `DEEPSEEK_API_KEY`（AI 相关功能）与 `AMAP_API_KEY`
（地址核查的坐标核实）。两者都不是必需的——未配置时对应功能会给出提示或降级运行。
`.env` 已被 `.gitignore` 排除，不会被提交。

### 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DWC_HOST` | `127.0.0.1` | 部署到云服务器时改为 `0.0.0.0` |
| `DWC_PORT` | `8080` | 监听端口 |
| `DWC_DEBUG` | 关闭 | 设 `1` 打开调试与热重载。**仅本地使用** |

> ⚠️ 服务默认只监听本机且关闭调试。部署到服务器时请显式设置 `DWC_HOST=0.0.0.0`，
> 但**不要同时开启 `DWC_DEBUG`**——调试模式不应对外暴露。

---

## 3. 功能与路由对照

| 页面 | GET | POST | 核心模块 |
|---|---|---|---|
| 首页工作台 | `/` | — | `templates/index.html` |
| 凭证核查 | `/voucher` | `/run_voucher` | `paper_voucher_service` + `module2_core` |
| 一致性检查 | `/consistency` | `/run_consistency` | `consistency_check_core` + `consistency_ai_review` |
| OCR 处理 | `/ocr` | `/run_ocr` | `ocr_bridge`（图片需 PaddleOCR） |
| 地址核查 | `/address` | `/run_address` | `confirmation_address_review_final` |
| 企业信息填列 | `/company` | `/run_company` | `module5_enterprise_info_filler` |
| Supporting 整理 | `/supporting` | `/run_supporting` | `supporting_module_ai_v2` |
| 全局 AI 助手 | `/ai` | `/run_ai` | `DWCAIcenter` |

主流程：**OCR → 凭证核查 → 一致性检查 → AI 解释 → 人工复核**。

---

## 4. 技术架构

- **后端**：Python + Bottle（轻量级 WSGI 框架），开发服务器为单进程 WSGIRefServer
- **前端**：服务端渲染的 HTML + 内联 CSS/JS，无前端构建步骤
- **识别**：PaddleOCR（可选依赖）
- **判定**：「规则优先、模型辅助」——`module2_core` 的规则引擎出结论，
  大模型负责原因解释、异常归纳和下一步建议；模型置信度低于阈值时回退规则结论
- **大模型**：DeepSeek，经 OpenAI 兼容接口调用
- **地图**：高德地理编码，用于函证地址与工商注册地址的坐标距离核实

---

## 5. 设计边界与注意事项

当前版本的明确边界，也是后续改进方向：

1. **中文文件名。**
   Bottle 的 multipart 解析会丢弃文件名中的非 ASCII 字节。
   实测 `抽样清单.xlsx` 在服务端被读成 `xlsx`（扩展名丢失），页面会报
   「仅支持 xlsx / xls / csv 文件」。`app.py` 已增加按文件头的类型嗅探兜底，
   但**使用英文文件名可完全规避**。

2. **跨模块状态。**
   7 个功能页面彼此独立运行，结果不跨页面持久化，不存在「上游结果自动带入下游」的
   会话状态。一致性检查需要自行上传两个文件，而不是自动承接凭证核查的输出。
   会话级的结果承接是下一步工作。

3. **全局 AI 助手的数据来源。**
   `DWCAIcenter.load_default()` 从当前工作目录读取生成的结果 xlsx，
   而 Web 版各路由的结果默认只存在内存中。将结果落盘后助手即可读取，
   这是与上一条同源的改造点。

4. **一致性检查的输入列名要求。**
   抽样清单侧读的是 `底稿金额` / `底稿日期`；若误用凭证口径列名
   （`凭证金额` / `凭证日期`），所有匹配行都会落到「需人工复核」。

5. **模块副本。**
   `modules/` 与 `../DirtyWorkCleaner/` 下的业务模块内容一致（上游为脚本原型，
   此处为 Web 运行时依赖）。**修改业务逻辑只改 `modules/`**，
   否则会出现改了不生效、或两份逐渐漂移的问题。

6. **大模型调用超时。**
   当前未设置请求超时。网络异常时单个请求可能长时间挂起，而开发服务器是单进程同步
   模型，期间整个站点无响应。生产部署建议前置 WSGI 容器并补上超时设置。

7. **金额覆盖规则的容差。**
   `module2_core.judge_amount` 的实际判定容差为 **95%（或绝对差 ≤ 50 元）**，
   即 5% 以内的缺口也会判为「已覆盖」。这一容差是显式的设计选择，可按业务口径调整。

---

## 6. 开发约定

- **修改业务逻辑**：只改 `DirtyWorkCleanerWeb/modules/`，不要改 `DirtyWorkCleaner/` 下的副本。
- **修改页面**：改 `templates/*.html`。模板语法是 Bottle SimpleTemplate：
  行首 `%` 触发代码行，`{{表达式}}` 输出并转义，`{{!表达式}}` 输出不转义。
  **不要把 `% if` / `% else` / `% end` 写在同一行里**，Bottle 会解析错误。
- **不要提交**：`.env`、密钥文件、`__pycache__/`、运行时生成的 xlsx。
  这些已在仓库根目录 `.gitignore` 中排除。

---

## 7. 版本控制

仓库根目录为 git 仓库（分支 `main`），根目录 `README.md` 提供项目总览。
