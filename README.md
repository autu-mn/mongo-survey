# 基于 MongoDB 的问卷系统

数据库课程大作业（第一阶段）。注册用户可以创建问卷、设置题目和跳转规则、通过链接分发；填写者登录后按规则一题一题作答；创作者查看统计并导出数据。所有数据存储在 MongoDB 中。

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

## 运行测试

测试使用单独的数据库 `survey_system_test`，每个测试前后自动清空，不会影响正式数据。

```powershell
cd backend
.venv\Scripts\python -m pytest -v --cov=app --cov-report=term-missing
```

当前结果：242 个测试全部通过，代码覆盖率 98%。

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
    scripts/seed_demo.py 演示数据
    tests/               自动测试
  frontend/
    pages/               各页面 HTML
    static/              样式与脚本
  schema/                四个集合的 $jsonSchema
  docs/                  文档（见下表）
```

## 文档

| 文档 | 内容 |
|------|------|
| [项目完成报告](docs/项目完成报告.md) | 总结报告：目标、设计、AI 使用过程、测试结果、问题与解决 |
| [系统说明](docs/系统说明.md) | 功能、架构、页面、安全措施 |
| [需求分析与界面设计](docs/需求分析与界面设计.md) | 页面流程、各页面的信息和操作、访问模式 P1 至 P23 |
| [数据库设计](docs/数据库设计.md) | 集合、字段、索引、并发控制、设计理由 |
| [API 说明](docs/API说明.md) | 全部 31 个接口 |
| [关键逻辑说明](docs/关键逻辑说明.md) | 跳转逻辑、校验、提交流程、统计、断点续填 |
| [测试用例](docs/测试用例.md) | 约 100 条用例与结果 |
| [AI 使用日志](docs/AI使用日志.md) | 每次使用 AI 的提示词、结果与修改 |
