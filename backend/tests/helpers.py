"""通过 API 搭建测试数据的辅助函数。"""

from fastapi.testclient import TestClient


def create_survey(client: TestClient, headers: dict, title: str = "测试问卷") -> dict:
    r = client.post("/api/surveys", json={"title": title}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def add_question(client: TestClient, headers: dict, survey_id: str, **body) -> dict:
    r = client.post(f"/api/surveys/{survey_id}/questions", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def single(title, *texts, required=True):
    return {"type": "single", "title": title, "required": required,
            "options": [{"text": t} for t in texts]}


def multiple(title, *texts, required=True, **constraints):
    return {"type": "multiple", "title": title, "required": required,
            "options": [{"text": t} for t in texts], "constraints": constraints}


def text(title, required=False, **constraints):
    return {"type": "text", "title": title, "required": required, "constraints": constraints}


def number(title, required=True, **constraints):
    return {"type": "number", "title": title, "required": required, "constraints": constraints}


def set_logic(client, headers, survey_id, qid, rules, default_goto=None, expect=200):
    r = client.put(f"/api/surveys/{survey_id}/questions/{qid}/logic", headers=headers,
                   json={"rules": rules, "defaultGoto": default_goto})
    assert r.status_code == expect, r.text
    return r.json()


def rule(op, value, goto):
    return {"when": {"op": op, "value": value}, "goto": goto}


def opt(question: dict, text: str) -> str:
    """按选项文字取 optionId。"""
    return next(o["optionId"] for o in question["options"] if o["text"] == text)


def build_demo_survey(client: TestClient, headers: dict, publish: bool = True, settings: dict | None = None):
    """作业需求中的示例：
    Q1 性别（单选）：男 → Q3；女 → Q2；其他按顺序到 Q2
    Q2 喜欢的水果（多选，2 至 3 项）：包含葡萄 → 结束
    Q3 年龄（数字，0 至 120 整数）：小于 18 → 结束
    Q4 建议（文本，选填，最多 20 字）
    返回 (问卷详情, {"q1": 题目, ...})
    """
    s = create_survey(client, headers, "示例问卷")
    sid = s["id"]
    add_question(client, headers, sid, **single("你的性别", "男", "女", "其他"))
    add_question(client, headers, sid, **multiple("你喜欢的水果", "苹果", "香蕉", "西瓜", "葡萄",
                                                    minSelect=2, maxSelect=3))
    add_question(client, headers, sid, **number("年龄", min=0, max=120, integerOnly=True))
    s = add_question(client, headers, sid, **text("其他建议", maxLength=20))
    q1, q2, q3, q4 = s["questions"]
    set_logic(client, headers, sid, q1["questionId"],
              [rule("eq", opt(q1, "男"), q3["questionId"]), rule("eq", opt(q1, "女"), q2["questionId"])])
    set_logic(client, headers, sid, q2["questionId"], [rule("includes", opt(q2, "葡萄"), "END")])
    s = set_logic(client, headers, sid, q3["questionId"], [rule("lt", 18, "END")])
    if settings:
        r = client.put(f"/api/surveys/{sid}/settings", json=settings, headers=headers)
        assert r.status_code == 200, r.text
    if publish:
        r = client.post(f"/api/surveys/{sid}/publish", headers=headers)
        assert r.status_code == 200, r.text
        s = r.json()
    qs = dict(zip(["q1", "q2", "q3", "q4"], s["questions"]))
    return s, qs
