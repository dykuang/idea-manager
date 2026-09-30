# IdeaMiner

[English](#ideaminer) · [简体中文](#ideaminer中文)

IdeaMiner is a local-first research idea manager built with React, TypeScript, FastAPI, SQLite FTS5, and Cytoscape.js. It captures ideas without rewriting the original text, organizes them into projects, and visualizes how they develop and connect.

Your SQLite database is the canonical source of truth. The core application runs locally and does not require an account, cloud database, or API key.

![IdeaMiner overview showing projects, filters, tags, stages, and research idea cards](docs/ideaminer-overview.png)

_A privacy-safe example library. Your own ideas remain in the SQLite database beside your local installation._

## When IdeaMiner earns its place

- **A promising thought arrives before the project exists.** Capture it in `random_chat`; IdeaMiner preserves the original wording while you later refine it, tag it, and move it into a research project.
- **One hypothesis keeps branching.** Turn alternatives, experiments, evidence, and objections into linked descendant ideas, then use Lineage view to see how the reasoning evolved instead of losing it in a long document.
- **The interesting connection crosses project boundaries.** Drag several cards into Dream, add an optional question, and use an agent to propose a new synthesis while keeping every source idea traceable.
- **Your research must remain local.** Keep the canonical library in SQLite, reference nearby papers or code by file path without copying their contents, and write notes with Markdown and LaTeX.
- **A collaborator wants to build on your thinking.** Export a project as JSON so they can import and integrate its ideas and relations, or export readable Markdown for discussion.

For example: capture “Could prediction change with temporal scale?”, grow separate children for modeling, evaluation, and counterarguments, attach the relevant paper paths, and let the weekly review bring the most promising unfinished branch back into focus.

## Features

- Idea CRUD with immutable original captures and editable Markdown/LaTeX notes
- Projects, project groups, recycle bin, move/copy actions, and bulk cleanup
- Tags, tag groups, deterministic group colors, co-occurrence Tag Map, and bulk tag management
- FTS5 keyword search, filters, related-idea suggestions, graph view, and lineage tracking
- Scalable Focus browser with a compact navigator, stable reading pane, density control, and keyboard navigation
- Local-file references that store paths and metadata without embedding file contents
- Figure galleries with captions, ordering, and a per-idea cover image
- Clipboard paste and drag/drop for local PNG, JPEG, WebP, GIF, and SVG figures
- JSON import/export and Markdown export
- Micro-experiment logs with idea links, searchable results, repeat detection, figures, and metadata
- Weekly Review with deterministic Research Gap Radar, experiment follow-up, and cross-project Serendipity suggestions
- Local semantic discovery, lineage exploration, and cross-project Dream synthesis
- Optional Agent workspace with separate OpenAI, Anthropic, DeepSeek, Qwen, and local profiles
- Optional MCP bridge for using the same library from Codex

## Project wiki

The [IdeaMiner project wiki](docs/wiki/Home.md) covers installation, research workflows, Research Intelligence, agents and Dream, privacy and backups, Remote Sync, updates, development, and troubleshooting.

## Interface modes

IdeaMiner includes two saved interface modes. **Classic** keeps the original layout. **Studio** offers a denser three-pane research workspace with a persistent navigator and idea inspector. Choose a mode from **Appearance** in the top bar. Studio also supports light, dark, or system appearance and comfortable, compact, or dense idea lists. Your preferences are stored in this browser and do not change the SQLite library.

Press **Ctrl+K** (or **Cmd+K** on macOS) to search ideas and run commands such as opening Graph, Lineage, Review, Agent, and Dream, managing projects or tags, and importing or exporting data.

## Quick start on Windows

### Requirements

Install these once:

- [Python 3.11 or newer](https://www.python.org/downloads/windows/) — enable **Add Python to PATH** during installation
- [Node.js LTS](https://nodejs.org/) — includes npm

Then:

1. Download and extract this repository, or clone it with Git.
2. Double-click **`start-ideaminer.bat`**.
3. On the first run, allow the setup window to create `.venv` and install the locked dependencies.
4. Keep the IdeaMiner command window open while using the app.

The browser normally opens at [http://127.0.0.1:5173](http://127.0.0.1:5173). If another IdeaMiner copy is running, the launcher automatically chooses free web/API ports and connects only to this folder's backend. The command window prints the exact database and addresses. Later starts skip installation and open much faster. To stop cleanly, use **Quit** in IdeaMiner or press `Ctrl+C` in its command window.

## Manual setup on Windows, macOS, or Linux

From a terminal in the repository:

```bash
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS or Linux
source .venv/bin/activate
```

Install and run:

```bash
python -m pip install -r backend/requirements.txt
npm ci
python launcher.py
```

The coordinated launcher starts FastAPI on port 8000 and Vite on port 5173, opens the browser, and shuts both services down together.

## First launch and storage

IdeaMiner automatically creates `data/ideaminer.db` on first launch, including the built-in `random_chat` and `recycle` projects. That database, its backups, `.env` files, dependencies, and build artifacts are ignored by Git.

Never commit the `data` directory contents: they can contain idea text, agent history, file paths, and other private research material. The repository intentionally includes only `data/.gitkeep`.

For backups, stop IdeaMiner and copy `data/ideaminer.db` somewhere safe. For sharing selected knowledge with another IdeaMiner user, use **Export → JSON** and let the recipient use **Import**.

### Research figures

Open an idea to add a figure with **Add figures**, drag image files onto its Figures area, or copy an image and press **Ctrl+V** (or **Cmd+V**) while the idea is open. PNG, JPEG, WebP, GIF, and SVG files are supported. Add captions, reorder figures, and choose one cover figure; collapsed cards show a small figure count.

Pasted and uploaded images are copied into the local `data/assets/ideas/` directory (next to `data/ideaminer.db`); they are not sent to a cloud service or an Agent automatically. Existing linked files continue to point to their original location, and detaching any file does not delete it. Back up `data/assets/` along with `data/ideaminer.db` to preserve internally stored figures. The assets folder is ignored by Git.

## Agent connections

The application works fully without an LLM. To use the optional Agent or Dream tools, open **Agent** and choose the **OpenAI**, **Anthropic**, **DeepSeek**, **Qwen**, or **Local** tab. Enter the key once, choose a model and thinking effort, leave **Remember this credential in the operating system vault** checked, and save the profile.

Each provider keeps its own endpoint, model, thinking effort, and credential, so switching tabs does not require retyping keys. Secrets live in the current operating-system user's credential vault—not SQLite, browser storage, the profile file, backups, or exports. Non-secret profile choices are stored beside the database. **Forget saved profile** removes one provider's saved settings and credential. The Local tab supports OpenAI-compatible Responses endpoints and an optional key.

The included `.env.example` is a reference list for unattended or portable configuration; IdeaMiner does not automatically load it. You can set those values in your shell or operating-system environment instead of saving an in-app profile.

Original `raw_text` captures are excluded from online Agent context. Selected working notes and explicitly selected compatible local files may be sent to the configured provider for a run.

### Advanced agent workflows

- **Grow an idea without overwriting its history:** open an idea, run **Elaborate**, and choose **Save as new**. The result becomes a child in the same project with a `develops-into` relation; choose **Update original** only when the response should replace the current working version.
- **Discover and record connections:** run the Agent in **Connect** mode over all ideas, one project, or a project group. It can propose typed relations with explanations; apply only the useful proposals so the graph—not a fragile reference such as “Idea #4”—remains the source of truth.
- **Dream across boundaries:** drag two to eight cards, even from different projects, into the **Dream** tray. Add an optional prompt such as “combine these into a testable study,” choose a destination project, and review the proposed descendants. Accepted results receive the `dreams` tag and `inspired-by` links to every source card.
- **Stress-test before committing:** use **Critique** to expose assumptions and missing evidence, or **Synthesize** to turn a cluster of ideas into a coherent direction. Agent-created ideas, edits, and relations remain proposals until you accept them.
- **Follow the idea track:** use **Lineage** for parent-to-descendant development, **Graph** for wider conceptual links, and stages plus the weekly **Review** to decide which branches should advance, pause, or reconnect.

Example: elaborate a broad hypothesis into separate modeling and evaluation children, connect the evaluation branch to a calibration idea from another project, then Dream those cards into a new experiment. The resulting idea retains visible links to its sources, so months later you can still reconstruct why it exists.

## Everyday workflow

- Create a project, or use `random_chat` for temporary captures.
- Write notes with Markdown and KaTeX (`$...$` inline and `$$...$$` for display equations).
- Use `develops-into` relations and the **Lineage** view to follow an idea track.
- Open **Tags → settings → Tag map** to see tag co-occurrence in the selected scope.
- Deleted ideas first move to **Recycle**. Deleting them there is permanent.
- Agent and Dream results remain reviewable proposals until you apply them.

## Import and export

**Export → JSON** produces a versioned library file containing groups, projects, ideas, original captures, tags, timestamps, and typed relations. Import previews conflicts and can skip, copy, or update matching ideas inside one SQLite transaction.

Markdown export is intended for reading. Local attachment contents are never bundled; exports contain only library records and references.

## Remote project file sync

Open **Remote** to save an SSH connection profile, check reachability, and compare a project folder with its remote copy. Profiles use the current user's SSH configuration, keys, and agent; private keys and passphrases are never stored by IdeaMiner. Add and verify the server fingerprint in `~/.ssh/known_hosts` through a trusted channel first. IdeaMiner rejects unknown or changed host keys.

Each run is a push or pull. Review the file comparison before transferring; changed files are unchecked until selected, identical files are skipped, and destination-only files are preserved unless you explicitly select deletion. Sync includes the project workspace and linked attachments. SQLite, ideas, and relations remain local to each machine. A project without a workspace can use **Browse** to choose its local folder.

## Optional Codex integration

`ideaminer_mcp.py` is the stable stdio entry point for the included MCP server. The reusable Codex skill source is under `integrations/codex/ideaminer`. Point your local MCP configuration at this repository's Python interpreter and `ideaminer_mcp.py`, with the working directory set to the repository root.

For the Windows web installer, use the Start Menu's **Connect Codex MCP** shortcut after installing Codex CLI. It registers the packaged MCP server against the same user library as the app.

The MCP bridge reads and writes the same SQLite database and supports projects, search, capture, editing with optimistic concurrency, typed relations, move/copy, attachments, and review checkpoints. It does not expose permanent deletion.

## Development

With the environment and packages installed:

```bash
# Backend tests
python -m pytest backend/tests -q

# Frontend development server only
npm run dev

# Type-check and production build
npm run build
```

Useful local addresses:

- Web interface: [http://127.0.0.1:5173](http://127.0.0.1:5173)
- API documentation: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Health check: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

## Architecture

- `src/` — React + TypeScript interface
- `backend/app/` — FastAPI routes, SQLite schema/migrations, search, agents, and MCP tools
- `backend/tests/` — API and MCP protocol tests
- `data/` — ignored local library state
- `launcher.py` — coordinated API/frontend lifecycle and in-app Quit support
- `integrations/` — optional Codex skill source

`ideas.raw_text` preserves the original capture. Editable content and revisions live separately. FTS5 indexes searchable text, while `idea_embeddings` is isolated so a different semantic-vector implementation can be added without changing idea records.

## Troubleshooting

- **Python was not found:** install Python 3.11+ and enable its PATH option, then reopen the launcher.
- **npm was not found:** install Node.js LTS and reopen the launcher.
- **PowerShell blocks activation:** activation is unnecessary when using `start-ideaminer.bat`; it calls the environment's Python directly.
- **Dependency installation failed:** confirm internet access, delete the incomplete `.venv` or `node_modules`, and run the launcher again.
- **A port is already in use:** quit any older IdeaMiner process using ports 8000 or 5173.
- **The browser did not open:** wait for the launcher to report readiness, then visit `http://127.0.0.1:5173` manually.

## License

Copyright 2026 Dongyang Kuang. Licensed under the [Apache License 2.0](LICENSE).

---

# IdeaMiner（中文）

IdeaMiner 是一款本地优先（local-first）的研究想法管理工具，基于 React、TypeScript、FastAPI、SQLite FTS5 和 Cytoscape.js 构建。它可以在完整保留最初灵感字句的前提下记录想法，将其按项目清晰归类，并直观呈现想法的演进脉络与关联网络。

本地 SQLite 数据库是应用的唯一真实数据源（Single Source of Truth）。核心功能完全在本地运行，无需注册账号、无需云端数据库，也不强制要求 API Key。

项目 Wiki：[安装与快速开始](docs/wiki/Getting-Started.md)、[研究工作流](docs/wiki/Ideas-and-Research-Workflow.md)、[研究智能功能](docs/wiki/Research-Intelligence.md)、[隐私与备份](docs/wiki/Data-Privacy-and-Backup.md)、[SSH 远程同步](docs/wiki/Remote-Sync.md)、[开发指南与常见问题](docs/wiki/Developer-Guide.md)。

![IdeaMiner 概览，展示项目、筛选器、标签、阶段和研究想法卡片](docs/ideaminer-overview.png)

_注：截图为注重隐私的示例想法库。你记录的所有想法均安全保存在本地安装目录下的 SQLite 数据库中。_

## 适用场景

- **灵感初现，项目尚无雏形：** 随时在 `random_chat`（随手记）中捕捉想法；IdeaMiner 会完整保留原始措辞，方便日后随时补充细节、添加标签，再整理归入正式的研究项目。
- **单一假设不断衍生分支：** 将备选方案、实验设计、实证论据与反驳意见拆解为相互关联的子想法；借助 Lineage（谱系）视图清晰纵览推演全过程，避免思维逻辑被淹没在冗长文档中。
- **跨越项目边界的灵感碰撞：** 将多张卡片拖入 Dream（造梦）托盘，提出一个引导性问题，借助 Agent 综合提炼出全新方向，同时每张来源卡片均清晰可溯。
- **研究资产严格保持本地化：** 核心数据沉淀在本地 SQLite 中；通过文件路径直接关联本地论文或代码，无需复制或搬运文件本体；支持使用 Markdown 与 LaTeX 自由撰写笔记与公式。
- **与协作者共享思考脉络：** 将项目导出为 JSON 格式，方便协作者导入并完整还原想法与关系网络；亦可导出排版清晰的 Markdown 用于讨论与阅读。

例如：随手记下“预测是否会随时间尺度发生变化？”，围绕它分别派生出建模、评估与反驳视角的子想法，附上相关论文路径；之后通过每周 Review（回顾），让最有潜力的未完分支重新回到你的视野中。

## 核心特性

- **想法管理：** 原始记录不可变，工作笔记支持 Markdown 与 LaTeX（KaTeX）自由编辑与增删改查
- **层级组织：** 支持项目、项目组与回收站机制，提供灵活的移动、复制及批量清理操作
- **标签体系：** 支持标签组、确定性分组配色、标签共现图（Tag Map）与批量标签维护
- **检索与关联：** 内置 SQLite FTS5 全文搜索、多维筛选、关联推荐、全局关系图谱（Graph）与演进谱系（Lineage）
- **Focus 沉浸浏览：** 提供紧凑导航栏、稳定的主阅读区、信息密度调节与键盘快捷操作
- **本地文件引用：** 仅记录文件路径与元数据，无需复制或嵌入大体积文件
- **数据流转：** 支持全量/项目级结构化 JSON 导入导出，以及适合阅读的 Markdown 导出
- **深度启发：** 定期 Review 回顾、本地语义发现、跨项目 Dream 创意综合
- **可选 Agent 工作区：** 为 OpenAI、Anthropic、DeepSeek、通义千问（Qwen）与 Local 本地模型提供独立的配置与凭据隔离
- **可选 MCP 协议桥接：** 支持在 Codex 等支持 MCP 的工具中直接访问并操作同一个本地想法库

## Windows 快速开始

### 环境要求

请先在系统中安装以下基础环境（仅需配置一次）：

- [Python 3.11 或更高版本](https://www.python.org/downloads/windows/) —— 安装时请务必勾选 **Add Python to PATH**
- [Node.js LTS](https://nodejs.org/) —— 包含 npm 包管理器

然后：

1. 下载并解压本仓库，或通过 Git 克隆到本地。
2. 双击运行 **`start-ideaminer.bat`**。
3. 首次启动时，程序会自动创建 `.venv` 虚拟环境并安装所需依赖，请稍作等待。
4. 使用期间请保持控制台窗口处于运行状态。

启动成功后，浏览器通常会自动打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)。若本地已运行其他 IdeaMiner 实例，启动器会自动检测并分配空闲的 Web/API 端口，且仅连接当前目录对应的后端服务。控制台会打印实际使用的数据库路径与访问地址。后续启动会跳过依赖安装，开启速度大幅提升。若需退出，可在应用界面点击 **Quit**，或在控制台按 `Ctrl+C` 正常停止。

## Windows、macOS 或 Linux 手动设置

在仓库根目录下打开终端执行：

```bash
python -m venv .venv
```

激活虚拟环境：

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS 或 Linux
source .venv/bin/activate
```

安装依赖并启动：

```bash
python -m pip install -r backend/requirements.txt
npm ci
python launcher.py
```

内置启动器会自动在 8000 端口启动 FastAPI、在 5173 端口启动 Vite，并自动唤起浏览器；在退出时会统一联动关闭两项后台服务。

## 首次启动与存储

IdeaMiner 首次启动时会自动在 `data/ideaminer.db` 初始化数据库，并预置内置的 `random_chat`（随手记）和 `recycle`（回收站）项目。该数据库文件、备份、`.env` 配置、环境依赖和构建产物均已在 Git 中忽略。

切勿提交 `data` 目录中的内容：其中可能包含想法文本、Agent 对话历史、本地文件路径等个人敏感研究资料。仓库仅保留占位文件 `data/.gitkeep`。

如需备份数据，在停止 IdeaMiner 后直接将 `data/ideaminer.db` 复制保存至安全位置即可。若需与其他用户分享部分内容，建议使用 **Export → JSON** 导出，由接收方通过 **Import** 导入。

## Agent 连接

IdeaMiner 无需大语言模型即可独立完整使用。若需启用可选的 Agent 或 Dream（造梦）功能，可打开 **Agent** 界面，在 **OpenAI**、**Anthropic**、**DeepSeek**、**Qwen** 或 **Local** 标签页中配置。填入 API Key，选择模型与思考力度（Thinking Effort），勾选 **Remember this credential in the operating system vault**（记住系统凭据），点击保存配置即可。

各供应商的接口端点（Endpoint）、模型、思考力度及认证凭据相互独立存储，切换标签无需重复输入密钥。API 密钥安全存放在当前用户的系统凭据保险库（Credential Vault）中，绝不会写入 SQLite、浏览器本地存储、配置文件、备份或导出文件。非敏感配置项则保存在数据库同级目录。点击 **Forget saved profile** 即可单独清空当前供应商的配置与凭据。Local 标签页支持兼容 OpenAI 规范的端点，并支持免密或填入自定义 Key。

仓库提供的 `.env.example` 仅作为无人值守部署或便携配置的环境变量参考，应用启动时不会自动加载该文件。你也可以直接在 Shell 或系统环境变量中配置对应参数，代替应用内保存。

隐私保护原则：不可变的 `raw_text` 原始记录绝不会被带入在线 Agent 的上下文。单次调用中，仅用户显式选定的工作笔记内容及兼容的本地关联文件，才会被发送给所配置的模型服务商。

### 高级 Agent 工作流

- **无损推进与衍生想法：** 打开某个想法卡片，运行 **Elaborate**（扩写深化）并选择 **Save as new**（存为新想法）。生成内容将作为同项目下的子想法保存，并自动建立 `develops-into` 衍生关系；仅在确实希望用生成内容替换当前笔记时，才选择 **Update original**（更新原想法）。
- **智能挖掘并沉淀关联：** 在全部想法、特定项目或项目组范围内以 **Connect**（关联）模式运行 Agent。它能分析并推荐带有理由阐述的类型化关系；按需采纳推荐关系，让知识图谱而非“想法 #4”这种易失效的纯文字引用成为可信结构。
- **跨边界灵感碰撞（Dream）：** 将跨项目的 2~8 张卡片拖入 **Dream**（造梦）托盘，输入引导提示（如“将这些切入点融合成一个可落地的实验方案”），指定目标项目后生成方案。采纳后的新想法将自动打上 `dreams` 标签，并与所有来源卡片建立 `inspired-by`（启发自）溯源关联。
- **定稿前严谨压力测试：** 使用 **Critique**（批判审视）剖析潜在假设与证据薄弱点，或使用 **Synthesize**（综合归纳）把零碎想法聚合成清晰纲领。所有由 Agent 生成的新想法、修改与关联在用户明确采纳前均为待确认的建议草案。
- **全局追踪思考演进轨迹：** 通过 **Lineage**（谱系）查看自父代至后代的推理推演路线，通过 **Graph**（图谱）把握更广泛的概念网络；结合阶段（Stage）标记与每周 **Review**（回顾），明确哪些分支应继续推进、暂缓沉淀或交叉并网。

例如：将一个宽泛的假设逐步拆解为建模与评估两个子分支，把评估分支与另一项目里的校准方案建立连接，再将两处卡片拖入 Dream 催生新的实验构想。新想法完整保留指向上游来源的清晰链条，即使数月后再看，也能轻松复现其诞生脉络。

## 日常工作流

- 创建专属研究项目，或利用内置的 `random_chat` 随手捕捉零碎灵感。
- 笔记支持富文本撰写：支持标准 Markdown 与 KaTeX 数学公式（行内公式 `$...$`，块级公式 `$$...$$`）。
- 善用 `develops-into` 衍生关系与 **Lineage** 视图，还原思考从萌芽到深化的发展主线。
- 通过 **Tags → Settings → Tag map** 直观分析当前范围内的标签共现网络。
- 软删除保护机制：删除的想法优先移入 **Recycle**（回收站），仅在回收站内二次操作才会彻底清除。
- 审慎采纳机制：所有 Agent 拓展与 Dream 造梦结果均以建议形式呈现，经审核确认后方才写入库中。

## 导入与导出

**Export → JSON**：导出包含版本信息的结构化库文件，完整涵盖项目组、项目、想法条目、原始捕捉文本、标签、时间戳及类型化关系网。导入时支持变更预览与冲突比对，并在单一 SQLite 事务中安全执行跳过、复制或更新合并。

**Markdown 导出**：专为阅读与交流分享优化。注意本地附件仅导出路径与元数据引用，绝不会打包文件本体内容。

## 可选的 Codex 集成

`ideaminer_mcp.py` 是内置 MCP（Model Context Protocol）服务器的标准 stdio 入口；配套的可复用 Codex Skill 源码位于 `integrations/codex/ideaminer`。在本地 MCP 配置中，将命令指定为此仓库 Python 虚拟环境中的解释器及 `ideaminer_mcp.py`，工作目录设为仓库根目录即可。

对于通过 Windows Web 安装包部署的用户，安装 Codex CLI 后，只需点击开始菜单中的 **Connect Codex MCP** 快捷方式，即可将打包好的 MCP 服务与应用本地数据库自动对齐。

MCP 桥接支持项目/想法检索、快速捕捉、带乐观锁并发控制的编辑、类型化关系管理、移动/复制、附件元数据关联与 Review 检查点；出于数据安全考量，MCP 接口不提供硬删除能力。

## 开发指南

完成环境与依赖安装后，可执行以下命令：

```bash
# 后端测试
python -m pytest backend/tests -q

# 仅启动前端开发服务器
npm run dev

# 类型检查和生产构建
npm run build
```

本地常用服务入口：

- Web 界面：[http://127.0.0.1:5173](http://127.0.0.1:5173)
- API 交互文档 (Swagger UI)：[http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- 服务健康检查：[http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

## 系统架构

- `src/` —— React + TypeScript 前端界面
- `backend/app/` —— FastAPI 路由、SQLite 模式定义与迁移、检索、Agent 与 MCP 工具逻辑
- `backend/tests/` —— API 与 MCP 协议测试用例
- `data/` —— 本地数据库与状态（已配置 Git 忽略）
- `launcher.py` —— 统一协同 API 与前端的生命周期，支持界面一键退出
- `integrations/` —— 可选的 Codex Skill 源码

`ideas.raw_text` 字段严格保存最初输入的原始捕获内容，与后续的可编辑工作笔记及修订历史隔离存储。全文检索通过 SQLite FTS5 建立索引；语义向量表 `idea_embeddings` 采用解耦设计，方便未来拓展或更换向量模型，而无需变动想法核心数据结构。

## 常见问题与排查

- **未检测到 Python：** 请安装 Python 3.11 或更新版本，安装时务必勾选 **Add Python to PATH**，随后重新运行启动脚本。
- **未检测到 npm：** 请安装 Node.js LTS 版本，随后重新运行启动脚本。
- **PowerShell 脚本执行策略拦截：** 若使用 `start-ideaminer.bat` 则无需手动激活虚拟环境，脚本会直接调用 `.venv` 内的 Python。
- **依赖安装失败：** 请检查网络连接；若因中断导致损坏，可删除未完成的 `.venv` 或 `node_modules` 目录后重新启动安装。
- **端口冲突/已被占用：** 若提示 8000 或 5173 端口被占用，请先退出后台遗留的旧 IdeaMiner 进程。
- **浏览器未自动唤起：** 待启动终端提示服务就绪后，手动打开浏览器访问 `http://127.0.0.1:5173` 即可。

## 开源协议

基于 [Apache License 2.0](LICENSE) 协议开源。Copyright 2026 Dongyang Kuang。
