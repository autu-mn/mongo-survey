# API 说明

后端启动后，<http://127.0.0.1:8000/docs> 提供可在线调试的接口文档（由代码自动生成，与实现一致）。第一阶段共有 31 个接口；第二阶段完成后共有 50 个 HTTP 方法/路径组合。本文按页面和阶段分组说明；“访问模式”编号见[需求分析与界面设计](需求分析与界面设计.md)。

> 【V2：第二阶段修订】第 1–9 节保留第一次作业的接口记录；V2 新接口与示例见第 10–12 节。第 4 节关于发布后仍可改题、隐藏选项、`type_locked` 的描述只代表 V1，当行为冲突时以第 11 节的冻结规则为准。

## 1. 通用约定

| 项目 | 约定 |
|------|------|
| 前缀 | 所有接口以 `/api` 开头 |
| 格式 | 请求和响应均为 JSON（导出接口除外），字段名为驼峰式（`createdAt`） |
| 时间 | ISO 8601，带时区。响应中为 UTC，例如 `2026-10-21T10:04:00.123000Z`；请求中的截止时间必须带时区，例如 `2026-11-01T00:00:00+08:00` |
| 登录 | 请求头 `Authorization: Bearer <accessToken>` |
| 登录要求 | "必须"：未登录返回 401；"可选"：未登录也可以访问，但带了无效凭证仍返回 401 |
| 乐观锁 | 编辑页的接口可带请求头 `If-Match: <打开编辑页时读到的 updatedAt>`；与库中不一致时返回 409 `edit_conflict` |
| ID | 问卷、答卷 ID 为 24 位十六进制字符串；题目 ID 形如 `q_7f2c1a9e`，选项 ID 形如 `o_51ee03bd`，由后端生成 |

### 1.1 错误格式

所有错误返回同一种结构：

```json
{"code": "invalid_answer", "message": "至少选择 2 项", "details": [{"questionId": "q_51ee03bd", "message": "至少选择 2 项"}]}
```

`message` 可以直接展示给用户；`details` 在参数或问卷不合法时给出逐项错误。

| HTTP | code | 含义 |
|------|------|------|
| 401 | `login_required` / `token_expired` / `invalid_token` | 未登录 / 登录过期 / 凭证无效 |
| 401 | `bad_credentials` | 用户名或密码错误 |
| 404 | `survey_not_found` / `question_not_found` / `response_not_found` | 不存在，或不属于当前用户 |
| 409 | `username_taken` | 用户名已存在 |
| 409 | `invalid_transition` / `no_questions` / `deadline_passed` | 状态不允许该操作 / 没有题目不能发布 / 截止时间已过 |
| 409 | `edit_conflict` / `type_locked` | 问卷已在别处被修改 / 已发布的问卷不能改题型 |
| 409 | `survey_ended` / `already_submitted` | 问卷已结束（`details.reason` 为 `closed` / `expired` / `full`）/ 已提交过 |
| 422 | `validation_error` | 请求参数格式不合法 |
| 422 | `invalid_survey` | 问卷定义不合法（约束矛盾、跳转向前等），`details` 指出题目和字段 |
| 422 | `invalid_answer` | 答案不合法或不在作答路径上 |

## 2. 认证

| 方法 | 路径 | 登录 | 说明 | 访问模式 |
|------|------|------|------|---------|
| POST | `/api/auth/register` | 否 | 注册，返回 201 | P1 |
| POST | `/api/auth/login` | 否 | 登录 | P2 |
| GET | `/api/auth/me` | 必须 | 当前用户 | |

注册与登录的请求体相同：

```json
{"username": "alice", "password": "secret123"}
```

- `username`：3 至 32 个字符，不能包含空白；`password`：6 至 72 字节。
- 注册返回 `{"id", "username", "createdAt"}`；重名返回 409 `username_taken`。
- 登录返回：

```json
{"accessToken": "eyJhbGciOi...", "tokenType": "bearer", "expiresIn": 86400,
 "user": {"id": "6ad88e1b2696c59fe194ddcd", "username": "alice", "createdAt": "2026-10-21T10:04:00Z"}}
```

## 3. 问卷管理（创作者，均需登录）

| 方法 | 路径 | 说明 | 访问模式 |
|------|------|------|---------|
| POST | `/api/surveys` | 新建草稿，返回 201 和问卷详情 | |
| GET | `/api/surveys` | 我的问卷列表，按创建时间倒序 | P3 |
| GET | `/api/surveys/{id}` | 问卷详情（含全部题目） | P4、P7 |
| DELETE | `/api/surveys/{id}` | 软删除，返回 204 | P6 |
| GET | `/api/surveys/{id}/settings` | 读取分享设置 | P10 |
| PUT | `/api/surveys/{id}/settings` | 保存分享设置（整体替换） | P11 |
| POST | `/api/surveys/{id}/publish` | 发布：草稿 → 已发布 | P11 |
| POST | `/api/surveys/{id}/close` | 关闭：已发布 → 已关闭 | P5 |
| POST | `/api/surveys/{id}/reopen` | 重新开放：已关闭 → 已发布 | P5 |
| POST | `/api/surveys/{id}/recount` | 按实际答卷数校准计数器 | |

**新建**：`{"title": "水果偏好调查", "description": "大约 1 分钟"}`，标题 1 至 200 字。

**列表项**：

```json
{"id": "6ad88e1a2696c59fe194ddcc", "title": "水果偏好调查", "slug": "wxvpiE9H",
 "status": "published", "displayStatus": "open", "responseCount": 7,
 "deadline": null, "maxResponses": 100, "createdAt": "...", "updatedAt": "..."}
```

`status` 为存储的状态（`draft` / `published` / `closed`）；`displayStatus` 为显示状态，在 `published` 的基础上实时区分 `open`（进行中）、`expired`（已截止）、`full`（已满额）。

**详情**在列表项的基础上增加 `description`、`settings`、`version`、`questionCount`（未隐藏的题数）、`publishedAt`、`closedAt`、`questions`（题目结构见[数据库设计](数据库设计.md)第 4 节）。

**分享设置**：

```json
{"requireLogin": true, "allowAnonymous": false, "allowMultipleSubmit": false,
 "deadline": "2026-11-01T00:00:00+08:00", "maxResponses": 200,
 "completion": {"message": "感谢参与！", "redirectUrl": "https://example.com"}}
```

- 省略的字段取默认值：需要登录、实名、每人一次、不限截止、不限上限。
- `allowMultipleSubmit=false` 时 `requireLogin` 必须为 `true`；`maxResponses` 至少为 1；`redirectUrl` 只能以 http / https 开头。

**发布的前提**：当前为草稿、至少一道未隐藏的题、截止时间未过；否则 409 并给出具体原因。重新开放同样要求截止时间未过。

## 4. 编辑页（创作者，均需登录，均支持 `If-Match`）

> 【V2：第二阶段修订】本节表格及下文关于发布后编辑的文字保留第一阶段原记录。当前题目内容、增删、顺序和跳转规则仅能在草稿中修改；已发布/已关闭问卷返回 409 `published_question_locked`。新增版本引用和复制操作见第 11 节。

| 方法 | 路径 | 说明 |
|------|------|------|
| PATCH | `/api/surveys/{id}` | 修改标题、说明 |
| POST | `/api/surveys/{id}/questions` | 添加题目，追加到末尾，返回 201 |
| PUT | `/api/surveys/{id}/questions/order` | 调整顺序 |
| PUT | `/api/surveys/{id}/questions/{qid}` | 修改题目 |
| DELETE | `/api/surveys/{id}/questions/{qid}` | 删除题目：草稿直接删除，已发布改为隐藏 |
| POST | `/api/surveys/{id}/questions/{qid}/restore` | 恢复已隐藏的题目 |
| PUT | `/api/surveys/{id}/questions/{qid}/logic` | 保存该题的跳转规则 |

以上接口都返回修改后的完整问卷详情，前端直接用它重新渲染。所有修改保存前都会对整份问卷做定义校验，不通过时返回 422 `invalid_survey`。

**添加 / 修改题目**：

```json
{"type": "multiple", "title": "你喜欢的水果", "description": "", "required": true,
 "options": [{"text": "苹果"}, {"optionId": "o_e45489d4", "text": "香蕉"}],
 "constraints": {"minSelect": 2, "maxSelect": 3}}
```

| 题型 `type` | 可用约束 `constraints` |
|------------|----------------------|
| `single` | 无 |
| `multiple` | `minSelect`、`maxSelect`、`exactSelect`（后者不能与前两者同时设置） |
| `text` | `minLength`、`maxLength`（不超过 5000） |
| `number` | `min`、`max`、`integerOnly` |

- 修改题目时，已有选项带 `optionId`，新选项不带。
- 请求中没有出现的旧选项：草稿中被删除（引用它的规则一并删除）；已发布时改为隐藏。
- 已发布的问卷不能修改题型（409 `type_locked`）。

**调整顺序**：`{"questionIds": ["q_1", "q_2", "q_4", "q_3"]}`，必须包含全部题目（含已隐藏）。调整后若有规则变成向前跳，返回 422 并指出是哪条。

**跳转规则**：

```json
{"rules": [
   {"when": {"op": "eq", "value": "o_82d302d4"}, "goto": "q_0622f5a9"},
   {"when": {"op": "eq", "value": "o_cfe84a65"}, "goto": "q_edcac1f3"}
 ],
 "defaultGoto": null}
```

| 题型 | `op` | `value` |
|------|------|---------|
| 单选 | `eq`、`ne` | optionId |
| 单选 | `in` | optionId 数组 |
| 多选 | `includes` | optionId |
| 多选 | `includesAny`、`includesAll`、`equalsSet` | optionId 数组 |
| 数字 | `eq`、`ne`、`gt`、`gte`、`lt`、`lte` | 数字 |
| 数字 | `between` | `[下限, 上限]` |

`goto` 为本题之后某道题的 ID 或 `END`；`defaultGoto` 为所有规则都不命中时的去向，`null` 表示按顺序进入下一题。文本题不能设置规则。

## 5. 预览（创作者，需登录）

| 方法 | 路径 | 说明 | 访问模式 |
|------|------|------|---------|
| GET | `/api/surveys/{id}/preview` | 填写者视角的问卷，草稿也可以 | P9 |
| POST | `/api/surveys/{id}/preview/next` | 计算下一题，不写库 | P9 |

请求和响应与第 6 节的 `next` 相同。

## 6. 填写（填写者）

| 方法 | 路径 | 登录 | 说明 | 访问模式 |
|------|------|------|------|---------|
| GET | `/api/public/surveys/{slug}` | 可选 | 填写入口：返回该显示哪个页面 | P12、P13、P19 |
| POST | `/api/public/surveys/{slug}/next` | 可选 | 校验当前题并计算下一题 | P14、P20 |
| POST | `/api/public/surveys/{slug}/responses` | 可选 | 提交答卷，返回 201 | P15、P21 |
| DELETE | `/api/public/surveys/{slug}/draft` | 必须 | 丢弃填写进度，重新开始，返回 204 | P21 |

"可选"表示由问卷的 `requireLogin` 设置决定：需要登录而未登录时，入口返回 `login_required`，提交返回 401。

**填写入口**：

```json
{"state": "ok", "reason": null,
 "survey": {"slug": "wxvpiE9H", "title": "水果偏好调查", "description": "...",
            "requireLogin": true, "allowAnonymous": false, "allowMultipleSubmit": false,
            "firstQuestionId": "q_308dbac9",
            "questions": [{"questionId": "q_308dbac9", "number": 1, "type": "single", "title": "你的性别",
                           "description": "", "required": true, "constraints": {},
                           "options": [{"optionId": "o_82d302d4", "text": "男"}]}]},
 "draft": {"path": ["q_308dbac9", "q_edcac1f3"], "answers": {"q_308dbac9": "o_cfe84a65"},
           "lastVisitedAt": "..."},
 "draftDiscarded": false}
```

| `state` | 含义 | `survey.questions` |
|---------|------|-------------------|
| `ok` | 可以填写 | 全部未隐藏的题（不含跳转规则） |
| `ended` | 已结束，`reason` 为 `closed` / `expired` / `full` | 空 |
| `login_required` | 需要登录 | 空 |
| `already_submitted` | 每人一次且已提交过 | 空 |

- 不存在、草稿、已删除的问卷返回 404。
- `draft` 只在已登录且 `state=ok` 时返回：`path` 末尾为下一道要答的题，`answers` 为已保存的答案。
- `draftDiscarded=true` 表示问卷被修改过，旧进度已作废。

**下一题**：

```json
请求 {"questionId": "q_308dbac9", "value": "o_82d302d4"}
响应 {"next": "q_0622f5a9"}
```

- `value` 的类型：单选为 optionId；多选为 optionId 数组；文本为字符串；数字为数字或数字字符串；未作答为 `null`。
- `next` 为下一题 ID 或 `END`。答案不合法时返回 422 `invalid_answer`，`message` 为可直接显示的提示。
- 已登录时顺带保存进度。

**提交**：

```json
请求 {"answers": {"q_308dbac9": "o_cfe84a65", "q_edcac1f3": ["o_b64b7b13", "o_e45489d4"],
                 "q_0622f5a9": 25, "q_f03a076d": "多点水果"}}
响应 {"responseId": "6ad89dd9187bdabe0ef7d846",
      "completion": {"message": "提交成功，感谢你的参与！", "redirectUrl": null},
      "allowMultipleSubmit": false}
```

服务端从第一题重放整条路径：必答题缺失、答案不合法、出现路径之外的答案都返回 422，`details` 指出具体题目。其余失败：问卷已结束 409 `survey_ended`；已提交过 409 `already_submitted`。

## 7. 统计与导出（创作者，需登录）

| 方法 | 路径 | 说明 | 访问模式 |
|------|------|------|---------|
| GET | `/api/surveys/{id}/stats` | 整卷统计 | P16 |
| GET | `/api/surveys/{id}/stats/{qid}` | 单题统计 | P17 |
| GET | `/api/surveys/{id}/export.csv` | 导出 CSV（UTF-8 带 BOM，流式输出） | P18 |

```json
{"surveyId": "...", "title": "水果偏好调查", "totalResponses": 5,
 "questions": [
   {"questionId": "q_308dbac9", "order": 1, "type": "single", "title": "你的性别", "hidden": false,
    "answeredCount": 5, "skippedCount": 0,
    "options": [{"optionId": "o_82d302d4", "text": "男", "hidden": false, "count": 2, "ratio": 0.4}]},
   {"questionId": "q_0622f5a9", "order": 3, "type": "number", "title": "年龄", "hidden": false,
    "answeredCount": 4, "skippedCount": 1, "average": 27.5, "min": 15, "max": 40, "values": [25, 15, 40, 30]}
 ]}
```

- `ratio` 为"选择该项的人数 / 本题回答人数"；`skippedCount` 为被跳转跳过或选填未答的人数。
- 文本题只有 `values`。
- 已隐藏的题目和选项仍然返回，并标注 `hidden: true`。

## 8. 个人主页（需登录）

| 方法 | 路径 | 说明 | 访问模式 |
|------|------|------|---------|
| GET | `/api/me/participations` | 我参与的问卷 | P22、P23 |
| GET | `/api/me/responses/{responseId}` | 查看我的一份实名答卷 | P23 |

```json
{"inProgress": [{"slug": "pv9Tshfq", "title": "界面测试问卷", "displayStatus": "open",
                 "answeredCount": 1, "totalQuestions": 2, "lastVisitedAt": "...", "canContinue": true}],
 "submitted":  [{"responseId": "...", "slug": "wxvpiE9H", "title": "水果偏好调查",
                 "displayStatus": "open", "submittedAt": "..."}]}
```

- `submitted` 只包含实名答卷，匿名答卷不出现。
- 查看答卷时只能看自己的，否则返回 404。返回每道题的 `answered`、选择题的 `options[].chosen`、填空题的 `value`。

## 9. 其他

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查，返回 `{"status": "ok"}` |

页面路径（`/`、`/login`、`/survey/{slug}` 等）返回 HTML，不属于 API，见[系统说明](系统说明.md)第 4 节。

## 10. 【V2：第二阶段新增】独立题目、版本与共享

下列接口均需登录，使用现有 `Authorization: Bearer <token>`。题目身份 ID、版本 ID 是 24 位十六进制 MongoDB ObjectId。返回沿用驼峰字段；时间为带时区的 ISO 字符串。私有题目对非题主统一返回 404，避免暴露其存在。

| 方法 | 路径 | 请求与结果 | 访问模式 |
|---|---|---|---|
| GET | `/api/question-items?scope=mine&limit=50&offset=0` | 列本人题目；`scope=shared` 列他人公开及定向共享给我的题目；`limit` 为 1–100 | P24 |
| POST | `/api/question-items` | `{"content": QuestionIn}` 创建私有题目和第 1 版，或 `{"sourceVersionId": "..."}` 把有权读取的共享版本复制为自己的独立题目；二者只能选一 | P25 |
| GET | `/api/question-items/{itemId}/versions` | 按版本号列出全部版本，含 `parentVersionId` 与完整内容；题主或当前有共享访问权者可读 | P26 |
| POST | `/api/question-items/{itemId}/versions` | `{"parentVersionId": "...", "content": QuestionIn}` 从任意旧版分叉；省略 `content` 时复制父版正文，作为恢复旧版；只有题主可写，返回新版本 | P27 |
| PUT | `/api/question-items/{itemId}/sharing` | `{"visibility":"private|public|selected", "usernames":[...]}`；仅 `selected` 填非空用户名列表，用户名必须存在；只有题主可写 | P28 |

`QuestionIn` 字段仍沿用第 3 节的题目输入结构：`type/title/description/required/options/constraints`，不包含问卷内的题号、顺序、隐藏状态和跳转规则。新增题目时选项可不带 `optionId`，后端分配 ID；从旧版分叉时，保留的选项应带原 `optionId`。独立题目同样经过选项数量及题型约束校验。

版本返回示例：`{"id":"...","itemId":"...","versionNo":2,"parentVersionId":"...","content":{"type":"single","title":"你的年龄段","description":"","required":true,"options":[{"optionId":"o_...","text":"成年","hidden":false},{"optionId":"o_...","text":"未成年","hidden":false}],"constraints":{}},"createdAt":"..."}`。题目列表和共享更新返回身份信息及 `latestVersion`。版本号表示创建顺序，父版本 ID 表示分叉关系；恢复不会覆盖旧版。

常见错误：未登录 401 `login_required`；身份不可见或无权写 404 `question_item_not_found`；非法题目 422 `invalid_question`；父版本不属于本题 422 `invalid_parent_version`；指定用户名不存在 422 `unknown_share_user`；并发建版冲突重试失败 409 `version_conflict`。撤销共享会使他人后续读取及复制来源版本失败；他人已复制到自己名下的独立题目保留。问卷引用与既有问卷快照的当前行为见第 11 节。

### 10.1 创建题目与首版示例

请求：

```http
POST /api/question-items
Authorization: Bearer <token>
Content-Type: application/json

{
  "content": {
    "type": "single",
    "title": "你的年龄段",
    "description": "请选择一项",
    "required": true,
    "options": [{"text": "成年"}, {"text": "未成年"}],
    "constraints": {}
  }
}
```

响应 `201`。新题默认私有，后端为选项生成稳定 `optionId`：

```json
{
  "id": "<itemId>",
  "ownerId": "<userId>",
  "visibility": "private",
  "sharedUserIds": [],
  "latestVersion": {
    "id": "<versionId>",
    "itemId": "<itemId>",
    "versionNo": 1,
    "parentVersionId": null,
    "content": {
      "type": "single",
      "title": "你的年龄段",
      "description": "请选择一项",
      "required": true,
      "options": [
        {"optionId": "o_xxx", "text": "成年", "hidden": false},
        {"optionId": "o_yyy", "text": "未成年", "hidden": false}
      ],
      "constraints": {}
    },
    "createdAt": "2026-10-28T10:00:00Z"
  }
}
```

复制共享版本为自己的独立题目时，请求体改为 `{"sourceVersionId":"<versionId>"}`。新身份归当前用户，版本号重新从 1 开始，之后与原题的共享和版本树互不影响。

### 10.2 分叉、恢复和共享示例

从 v1 分叉并修改正文：

```json
{
  "parentVersionId": "<v1Id>",
  "content": {
    "type": "single",
    "title": "今年你的年龄段",
    "description": "",
    "required": true,
    "options": [
      {"optionId": "o_xxx", "text": "成年", "hidden": false},
      {"optionId": "o_yyy", "text": "未成年", "hidden": false}
    ],
    "constraints": {}
  }
}
```

恢复 v1 时仍调用同一路径，但只传 `{"parentVersionId":"<v1Id>"}`。返回的是一个新的版本号，例如 v4，`parentVersionId` 指向 v1；v1、v2、v3 均不修改。

定向共享请求：

```json
{"visibility":"selected", "usernames":["bob", "teacher2"]}
```

公开时使用 `{"visibility":"public","usernames":[]}`；撤销时使用 `{"visibility":"private","usernames":[]}`。不能把题目共享给自己，未知用户名返回 422。

## 11. 【V2：第二阶段新增】命名题库与问卷版本引用

所有接口需登录，题库只由所有者管理。题库成员是题目身份 ID；同一个题目可同时在多个题库，删除题库不删除题目、版本或问卷。失去共享权限的题目在已收录题库详情中以 `available:false` 标示，不能重新选用。

| 方法 | 路径 | 输入与结果 | 访问模式 |
|---|---|---|---|
| GET / POST | `/api/question-banks` | 列本人题库；POST `{"name":"常用题"}` 创建命名题库 | P29 |
| GET / PUT / DELETE | `/api/question-banks/{bankId}` | 详情含成员和可用状态；PUT `{"name":"新名称"}` 改名；DELETE 只删题库，返回 204 | P29 |
| PUT / DELETE | `/api/question-banks/{bankId}/items/{itemId}` | 收录或移出指定题目身份；重复收录不重复计数 | P29 |
| POST | `/api/surveys/{id}/questions/from-library` | `{"versionId":"..."}` 将有权使用的具体版本追加到草稿问卷；保留选项 ID，生成新的问卷内题目 ID | P30 |
| PUT | `/api/surveys/{id}/questions/{qid}/from-library` | 同一请求体，将草稿中已有题目替换为指定版本；保留本卷题目 ID、顺序和隐藏状态，清空该题旧跳转规则 | P30 |
| POST | `/api/surveys/{id}/questions/{qid}/save-to-library` | `{}` 或 `{"bankId":"..."}`；将未关联题目保存为身份和首版，可同时收录到本人的题库。已关联题目复用原身份/版本；返回 `itemId`、`versionId`、`survey` | P31 |
| POST | `/api/surveys/{id}/copy` | 将本人的问卷复制成新草稿，返回新问卷详情；新 ID、slug，`responseCount=0`，保留原题目快照和来源 | P32 |
| GET | `/api/question-items/{itemId}/usage` | `ownSurveys` 列本人未删除问卷及使用的版本 ID；`otherSurveyCount` 仅给其他人的未删除问卷数量，按问卷去重 | P33 |

选题和保存已有题目可带 `If-Match: <updatedAt>` 检测并发编辑。题目关联版本后，草稿中不能直接改它的正文，须先创建新版本，再用替换接口选入；使用他人共享题时也可通过第 10 节的创建接口复制成自己的独立题目。已发布或已关闭问卷的题目、选项、顺序、隐藏状态和跳转规则一律冻结，这些编辑请求返回 409 `published_question_locked`；需要修改时调用 `/copy` 创建草稿。第一阶段允许发布后继续修改题目的旧预期已在测试中按新需求更新。

发布草稿时，未关联题目自动建立私有题目身份和不可变首版，问卷保存版本来源 ID；发布与写入来源在同一次原子问卷更新中完成。若并发修改导致更新失败，预先创建的来源版本可在重试时复用。旧答卷不反推版本 ID。已发布的第一阶段遗留问卷调用“保存到题库”时仅补来源元数据，不改题目内容或问卷版本号。共享撤销后已有问卷的快照、原链接及填写路径保持可用。

常见错误：无权访问题库 404 `question_bank_not_found`；同名题库 409 `bank_name_taken`；源版本不可访问 404 `question_item_not_found`；已关联题目原位改内容 409 `versioned_question_locked`；并发编辑 409 `edit_conflict`。

### 11.1 题库详情响应示例

```json
{
  "id": "<bankId>",
  "name": "课堂常用",
  "itemCount": 2,
  "createdAt": "2026-10-28T10:10:00Z",
  "updatedAt": "2026-10-28T10:12:00Z",
  "items": [
    {
      "itemId": "<itemId>",
      "available": true,
      "item": {"id": "<itemId>", "visibility": "private", "latestVersion": {"versionNo": 2}}
    },
    {
      "itemId": "<revokedSharedItemId>",
      "available": false,
      "item": null
    }
  ]
}
```

`available:false` 表示题目曾被收录，但当前用户已没有新使用权限。它不会被题库接口悄悄删除；前端可以显示失权状态并允许用户手动移出。

### 11.2 从题库选题与保存现有题

选入问卷只提交版本 ID，不提交题目文字，避免客户端把预览内容改掉：

```http
POST /api/surveys/<surveyId>/questions/from-library
If-Match: 2026-10-28T10:20:00Z

{"versionId":"<versionId>"}
```

返回 `201` 和更新后的问卷详情。新题在问卷中获得新的 `questionId`、排在末尾，`sourceItemId/sourceVersionId` 指向来源，跳转规则初始为空。替换接口返回 `200`，保留原本卷题目 ID、顺序和隐藏状态，但清空该题旧规则，避免规则值继续引用旧版选项。

把现有题保存到指定题库：

```json
{"bankId":"<bankId>"}
```

响应包含 `itemId`、`versionId` 和更新后的 `survey`。重复保存已关联题时复用原身份和版本，不重复建题。

### 11.3 引用查询响应示例

```json
{
  "itemId": "<itemId>",
  "ownSurveys": [
    {
      "surveyId": "<surveyId>",
      "title": "课堂反馈",
      "status": "published",
      "versionIds": ["<v1Id>", "<v2Id>"]
    }
  ],
  "otherSurveyCount": 3
}
```

同一份问卷多次使用同一题目时，`otherSurveyCount` 仍只加 1；本人问卷的版本 ID 去重后返回。软删除问卷不计入结果。

## 12. 【V2：第二阶段新增】题目详情与跨卷统计

| 方法 | 路径 | 结果与权限 | 访问模式 |
|---|---|---|---|
| GET | `/api/question-items/{itemId}` | 题目身份、最新版本、`canSelectNew`；题主额外得到 `sharedUsernames` 供共享表单回显 | P26/P28 |
| GET | `/api/question-items/{itemId}/versions/{versionId}/stats` | 当前用户**自己未删除问卷**中，同一具体版本的可归版答案；返回 `answeredCount`、`unattributedCount`、`ownerSurveyCount` 和按题型整理的分布/数值 | P34 |

新提交答卷的 `answers[]` 在对应问卷快照有固定来源时写入 `questionVersionId`。统计只汇总该 ID 精确相等、且答案的问卷内 `questionId` 属于本次查询版本的答案；不能核实版本的旧答案只计入 `unattributedCount`，不进入分布、平均值。原 `/api/surveys/{id}/stats` 和 CSV 路径保持原口径。无权访问的题目/版本返回 404。共享撤销后，拥有该题既有未删除问卷的用户可查看历史、引用和本人统计；`canSelectNew=false`，新选题和复制源版本仍被拒绝。

### 12.1 选择题跨卷统计响应示例

```json
{
  "itemId": "<itemId>",
  "versionId": "<versionId>",
  "versionNo": 1,
  "type": "single",
  "title": "你的年龄段",
  "ownerSurveyCount": 2,
  "answeredCount": 18,
  "unattributedCount": 3,
  "options": [
    {"optionId": "o_xxx", "text": "成年", "hidden": false, "count": 15, "ratio": 0.8333},
    {"optionId": "o_yyy", "text": "未成年", "hidden": false, "count": 3, "ratio": 0.1667}
  ],
  "values": [],
  "average": null,
  "min": null,
  "max": null
}
```

多选题的 `count` 是该选项被选择的次数，`ratio=count/answeredCount`，各选项比例之和可以超过 100%。数字题通过 `average/min/max` 返回汇总，并在 `values` 中保留可归版值；文本题通过 `values` 返回内容。`unattributedCount` 只作提示，绝不混入这些结果。

### 12.2 V2 权限和错误码补充

| 场景 | HTTP / code | 原因 |
|---|---|---|
| 非题主创建版本或修改共享 | 404 `question_item_not_found` | 不暴露私有题目的存在和所有者 |
| 父版本属于另一题 | 422 `invalid_parent_version` | 版本树不能跨题目连接 |
| 已发布/已关闭问卷改题、排序、规则或选题 | 409 `published_question_locked` | V2 要求发布快照冻结 |
| 草稿中原位改已关联题正文 | 409 `versioned_question_locked` | 应创建新版本并显式替换 |
| 使用已撤销的共享版本做新引用 | 404 `question_item_not_found` | 撤销阻止新的使用 |
| 已有本人问卷在撤销后查看历史/本人统计 | 200，`canSelectNew=false` | 保留旧引用解释能力，不恢复新使用权限 |
| 查询不属于该题目的版本统计 | 404 `question_version_not_found` | 防止拼接 item/version ID |
