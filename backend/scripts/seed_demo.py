"""通过 HTTP API 生成演示数据（需要先启动后端）。

    python scripts/seed_demo.py [http://127.0.0.1:8000]

生成：
- 创作者 demo_owner / 123456，问卷"水果偏好调查"（作业需求中的示例，含单选、多选、数字跳转）
- 填写者 user1 至 user6 / 123456，各提交一份答卷
"""

import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PASSWORD = "123456"


def login(c: httpx.Client, username: str) -> dict:
    c.post("/api/auth/register", json={"username": username, "password": PASSWORD})  # 已存在时忽略
    r = c.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['accessToken']}"}


def check(r: httpx.Response) -> dict:
    if r.is_error:
        raise SystemExit(f"{r.request.method} {r.request.url} -> {r.status_code} {r.text}")
    return r.json()


def main():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        owner = login(c, "demo_owner")
        for old in check(c.get("/api/surveys", headers=owner)):
            if old["title"] == "水果偏好调查":  # 重复运行时先删除上次生成的演示问卷
                c.delete(f"/api/surveys/{old['id']}", headers=owner)
        s = check(c.post("/api/surveys", headers=owner, json={
            "title": "水果偏好调查", "description": "大约 1 分钟，感谢参与！"}))
        sid = s["id"]

        def add(body):
            return check(c.post(f"/api/surveys/{sid}/questions", headers=owner, json=body))

        add({"type": "single", "title": "你的性别", "required": True,
             "options": [{"text": "男"}, {"text": "女"}, {"text": "其他"}]})
        add({"type": "multiple", "title": "你喜欢的水果", "required": True,
             "options": [{"text": t} for t in ("苹果", "香蕉", "西瓜", "葡萄")],
             "constraints": {"minSelect": 2, "maxSelect": 3}})
        add({"type": "number", "title": "年龄", "required": True,
             "constraints": {"min": 0, "max": 120, "integerOnly": True}})
        s = add({"type": "text", "title": "其他建议", "required": False, "constraints": {"maxLength": 200}})
        q1, q2, q3, q4 = s["questions"]
        qs = {"q1": q1, "q2": q2, "q3": q3, "q4": q4}
        oid = {o["text"]: o["optionId"] for q in (q1, q2) for o in q["options"]}

        def logic(q, rules):
            check(c.put(f"/api/surveys/{sid}/questions/{q['questionId']}/logic", headers=owner,
                        json={"rules": rules, "defaultGoto": None}))

        logic(q1, [{"when": {"op": "eq", "value": oid["男"]}, "goto": q3["questionId"]},
                   {"when": {"op": "eq", "value": oid["女"]}, "goto": q2["questionId"]}])
        logic(q2, [{"when": {"op": "includes", "value": oid["葡萄"]}, "goto": "END"}])
        logic(q3, [{"when": {"op": "lt", "value": 18}, "goto": "END"}])

        check(c.put(f"/api/surveys/{sid}/settings", headers=owner, json={
            "requireLogin": True, "allowAnonymous": False, "allowMultipleSubmit": False,
            "deadline": None, "maxResponses": 100,
            "completion": {"message": "提交成功，感谢你的参与！", "redirectUrl": None}}))
        s = check(c.post(f"/api/surveys/{sid}/publish", headers=owner))

        fills = [
            {"q1": "女", "q2": ["苹果", "香蕉"], "q3": 25, "q4": "希望食堂多供应水果"},
            {"q1": "男", "q3": 15},
            {"q1": "男", "q3": 40, "q4": "无"},
            {"q1": "其他", "q2": ["苹果", "葡萄"]},
            {"q1": "女", "q2": ["苹果", "西瓜", "香蕉"], "q3": 30},
            {"q1": "男", "q3": 22, "q4": "西瓜最好吃"},
        ]
        login(c, "user7")
        for i, plan in enumerate(fills, start=1):
            user = login(c, f"user{i}")
            answers = {}
            for k, v in plan.items():
                q = qs[k]
                if q["type"] == "single":
                    v = oid[v]
                elif q["type"] == "multiple":
                    v = [oid[x] for x in v]
                answers[q["questionId"]] = v
            check(c.post(f"/api/public/surveys/{s['slug']}/responses", headers=user, json={"answers": answers}))

        print(f"问卷：{s['title']}（{len(fills)} 份答卷）")
        print(f"管理页：{BASE}/surveys/{sid}")
        print(f"填写链接：{BASE}/survey/{s['slug']}")
        print("账号：demo_owner / user1..user6 / user7（未填写），密码均为 123456")


if __name__ == "__main__":
    main()
