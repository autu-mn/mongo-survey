# API 说明

后端启动后，<http://127.0.0.1:8000/docs> 提供可在线调试的接口文档（由代码自动生成，与实现一致）。本文按页面分组说明全部 31 个接口；"访问模式"一列的编号见 [需求分析与界面设计](需求分析与界面设计.md)。

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
