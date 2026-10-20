# AI 使用日志

> 记录规则：每次向 AI 提问都记录一条，按时间顺序追加，不事后补写。
> 字段说明：Prompt 为原文；Result 写得到了什么；是否修改、修改内容写自己做的调整及原因。

使用工具：Cursor（Agent 模式，模型 Claude Opus）

---

### #1 2026-10-20 Cursor（Plan 模式）

**Prompt:**
> @大作业一.md 带着我规划和构思如何完成这个作业，需要输出和记录那些东西，依次做什么

**Result:**
AI 阅读作业要求后生成了一份第一阶段实施计划，内容包括：评分权重分析、技术栈建议（Python + FastAPI + PyMongo）、目录结构、三个集合（users / surveys / responses）的初步设计、跳转规则数据结构、API 草案、测试覆盖清单、AI 日志格式，以及为第二阶段预留的扩展点，并拆成 11 个待办事项。

**是否修改:** 是

**修改内容:**
- 补充了本机环境信息：MongoDB 已在本地安装并在后台运行（实际版本 9.0.2，计划里写的是 MongoDB 7）。
- 增加了执行要求：每完成一个待办事项就汇报进度，我确认后才进行下一步，避免 AI 一次性生成全部代码导致我无法审查。

---

### #2 2026-10-20 Cursor（Agent 模式）

**Prompt:**
> 基于 MongoDB 的问卷系统 —— 第一阶段完成规划。Implement the plan as specified……（执行计划的第一个待办：初始化）

**Result:**
- 检查环境：Python 3.11.9、Git 2.46、mongosh 2.12.0、MongoDB 9.0.2。
- 生成目录骨架：`backend/app/{models,routers,services}`、`backend/tests`、`frontend`、`schema`、`docs`。
- 生成 `requirements.txt`、`config.py`（用 pydantic-settings 读取 `.env`）、`.env.example`、最小可运行的 `main.py`（含 `/health` 接口）、`.gitignore`。
- 创建本日志文件，初始化 Git 仓库。

**是否修改:** 否

**修改内容:**
审查后确认无需修改。

---

### #3 2026-10-20 Cursor（Agent 模式）

**Prompt:**
> 确认（同意进入第二个待办：设计 users/surveys/responses 三个集合、$jsonSchema、索引，写数据库设计文档草稿）

**Result:**
- `schema/users.schema.json`、`schema/surveys.schema.json`、`schema/responses.schema.json`：三个集合的 `$jsonSchema`，顶层与嵌套对象均 `additionalProperties: false`。
- `backend/app/db.py`：读取 schema 文件，新集合用 `create_collection(validator=...)`、已有集合用 `collMod` 更新校验器，并按声明式列表建索引；可重复执行。`main.py` 启动时自动调用。
- 关键设计决定：
  - 题目内嵌在问卷中，题目和选项使用稳定字符串 ID；
  - 跳转规则存为数据 `{when: {op, value}, goto}`，按题型限定运算符，只允许向后跳以杜绝环；
  - 答卷单独成集合，存 `path`（实际作答路径）和 `surveyVersion`；
  - 用唯一部分索引 `{surveyId, submitterKey}`（仅 `singleSubmission: true` 生效）在数据库层保证"每人只能填一次"，匿名问卷的 `submitterKey` 用 HMAC 生成。
- `backend/tests/test_schema.py`：13 个测试，验证合法文档可写入、非法状态/题型/约束字段/运算符被拒绝、用户名和 slug 唯一、部分唯一索引生效，全部通过。
- `docs/数据库设计.md`：设计文档草稿，包含示例文档、字段说明、索引表、冗余取舍、校验分工、为什么不用关系型结构、第二阶段扩展点。

**是否修改:** 待审查

**修改内容:**
（审查后填写）
