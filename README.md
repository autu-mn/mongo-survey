# 基于 MongoDB 的问卷系统

数据库课程大作业（第一、二阶段完成版）。注册用户可以创建问卷、设置题目和跳转规则、通过链接分发；第二阶段增加独立题目版本、共享、多个命名题库、问卷快照冻结、引用查询与同版跨卷统计。所有业务数据存储在 MongoDB 中。

## 环境要求

| 软件 | 版本 | 说明 |
|------|------|------|
| Python | 3.11 或以上 | 开发时使用 3.11.9 |
| MongoDB | 7.0 或以上 | 开发时使用 9.0.2，单机部署即可（不需要副本集） |

## 快速开始

以下命令均在 Windows PowerShell 中执行。macOS / Linux 把 `.venv\Scripts\python` 换成 `.venv/bin/python` 即可。

**1. 确认 MongoDB 已启动**

```powershell
mongosh --eval "db.runCommand({ping: 1})"
```

**2. 安装依赖**

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

**3. 配置（可选）**

默认连接 `mongodb://127.0.0.1:27017`，数据库名 `survey_system`。需要修改时复制配置模板并编辑：

```powershell
copy .env.example .env
```

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `MONGO_URI` | `mongodb://127.0.0.1:27017` | MongoDB 连接地址 |
| `MONGO_DB` | `survey_system` | 数据库名 |
| `JWT_SECRET` | `change-me-in-production` | 登录凭证的签名密钥，部署时必须修改 |
| `JWT_EXPIRE_MINUTES` | `1440` | 登录有效期（分钟） |
| `BCRYPT_ROUNDS` | `12` | 密码哈希强度 |
| `HMAC_SECRET` | `change-me-hmac-secret` | 生成匿名填写者标识的密钥，部署时必须修改，**修改后已有匿名答卷的"每人一次"判断会失效** |
| `DRAFT_TTL_DAYS` | `30` | 填写进度多少天未访问后自动删除 |

**4. 初始化数据库**

建集合、注册 `$jsonSchema` 校验器、建索引。后端启动时也会自动执行；修改 `schema/` 中的校验规则或索引后，可以手动再执行一次（可重复执行）：

```powershell
.venv\Scripts\python -m app.db
```

从第一阶段数据库升级时，应先备份，再执行可重复迁移：

> 以下迁移命令只针对已有第一阶段数据执行。全新安装只需初始化数据库，不要对空库执行迁移作为“建库”步骤。

```powershell
.venv\Scripts\python -m scripts.migrate_stage2 --check
.venv\Scripts\python -m scripts.backup_mongo --output ..\backups\stage2-before.zip
.venv\Scripts\python -m scripts.backup_mongo --verify ..\backups\stage2-before.zip
.venv\Scripts\python -m scripts.migrate_stage2 --apply --backup ..\backups\stage2-before.zip
.venv\Scripts\python -m scripts.migrate_stage2 --audit --backup ..\backups\stage2-before.zip
```

迁移保留原用户、问卷、答卷和草稿；旧答卷不会被推测性补写题目版本。

迁移设计、备份核对数量和实际执行结果见[迁移执行记录](docs/第二阶段/迁移执行记录.md)。迁移脚本支持 `--check` 只读预检，并可在中断后重复执行；正式执行前请保留备份文件。

**5. 启动**

```powershell
.venv\Scripts\python -m uvicorn app.main:app --reload
```

- 网页：<http://127.0.0.1:8000/>
- 接口文档（可在线调试）：<http://127.0.0.1:8000/docs>

**6. 生成演示数据（可选）**

保持后端运行，另开一个终端：

```powershell
cd backend
.venv\Scripts\python scripts\seed_demo.py
```

会创建作业需求中的示例问卷"水果偏好调查"（含单选、多选、数字跳转）和 6 份答卷。演示账号的密码均为 `123456`：

| 账号 | 身份 |
|------|------|
| `demo_owner` | 创作者，拥有示例问卷 |
| `user1` 至 `user6` | 已填写过示例问卷 |
| `user7` | 未填写，可用来体验填写流程 |

## 【V2：第二阶段新增】题目库功能快速体验

登录后从顶部导航进入“我的题库”：

1. 创建一个命名题库，例如“课堂常用”。
2. 创建独立题目，系统自动保存为私有题目 v1；可在题目详情建立 v2、从旧版分叉或恢复。
3. 在共享设置中选择私有、全站登录用户可用或指定用户名可用。
4. 新建问卷，在草稿编辑页点击“从题库选题”，预览并选择具体版本。
5. 发布后题目内容和规则只读；需要改题时在管理页点击“复制为新草稿”。
6. 从题目详情查看版本历史、引用情况和“仅本人问卷”的同版跨卷统计。

题目分享权限只控制别人能否把题用于**新的问卷**。撤销共享不会破坏别人已有问卷；已有问卷始终按发布时保存的完整快照填写。

## 运行测试

测试使用单独的数据库 `survey_system_test`，每个测试前后自动清空，不会影响正式数据。

```powershell
cd backend
.venv\Scripts\python -m pytest -v --cov=app --cov-report=term-missing
```

第二阶段最终结果：268 个测试全部通过，代码覆盖率 96%（1954 条语句，未覆盖 80 条）。完整原始输出保存在[`pytest-output-stage2.txt`](docs/test-results/pytest-output-stage2.txt)，测试步骤、输入、预期输出和实际结果见[测试用例](docs/测试用例.md)。第一阶段的 242 项、98% 记录保留在文档中作为阶段基线；两阶段数字不可直接相加。

## 目录结构

```
project1/
  backend/
    app/
      main.py            应用入口、路由注册、页面托管
      config.py          配置项
      db.py              连接、建集合、注册校验器、同步索引
      deps.py            登录依赖（必须登录 / 可选登录）
      security.py        密码哈希、JWT、匿名标识
      errors.py          统一错误格式
      models/            请求与响应模型
      repositories/      全部 MongoDB 读写（按集合划分）
      services/          业务逻辑（跳转引擎、答案校验、提交、统计等）
      routers/           接口
    scripts/               演示数据、备份和第二阶段幂等迁移
    tests/               自动测试
  frontend/
    pages/               各页面 HTML
    static/              样式与脚本
  schema/                七个集合的 $jsonSchema
  docs/                  文档（见下表）
```

## 文档

| 文档 | 内容 |
|------|------|
| [项目完成报告（V1）](docs/项目完成报告.md) | 第一阶段原版报告，保持原结构和内容 |
| [项目完成报告（V2）](docs/项目完成报告_V2.md) | 第二阶段独立报告，按 V1 架构说明需求演进、迁移、实现和验证 |
| [系统说明](docs/系统说明.md) | 功能、架构、页面、安全措施 |
| [需求分析与界面设计](docs/需求分析与界面设计.md) | 统一页面流程、各页面的信息和操作、访问模式 P1 至 P34 |
| [数据库设计](docs/数据库设计.md) | 集合、字段、索引、并发控制、设计理由 |
| [API 说明](docs/API说明.md) | 第一阶段接口与第二阶段新增接口，共 50 个方法/路径组合 |
| [关键逻辑说明](docs/关键逻辑说明.md) | 跳转逻辑、校验、提交流程、统计、断点续填 |
| [测试用例](docs/测试用例.md) | 约 100 条用例与结果 |
| [AI 使用日志](docs/AI使用日志.md) | 每次使用 AI 的提示词、结果与修改 |
| [第二阶段变更清单](docs/第二阶段变更清单.md) | 每个新增/修改文件、原因、需求和验证结果 |
| [第二阶段基线说明](docs/第二阶段/基线说明.md) | 第二阶段开始前的代码、数据和未提交改动保护记录 |
| [迁移执行记录](docs/第二阶段/迁移执行记录.md) | 迁移前备份、数量核对、幂等执行和审计结果 |
