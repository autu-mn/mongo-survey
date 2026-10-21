// 填写页（/survey/{slug}）与预览页（/surveys/{id}/preview）共用。
// 一屏一题；"下一题"由后端根据跳转规则计算，前端只记录走过的路径以便"上一题"。

const PREVIEW = location.pathname.startsWith("/surveys/");
const key = pathParam(1);  // 预览为问卷 ID，填写为 slug
const app = document.getElementById("app");

const endpoints = PREVIEW
  ? { load: `/api/surveys/${key}/preview`, next: `/api/surveys/${key}/preview/next` }
  : { load: `/api/public/surveys/${key}`, next: `/api/public/surveys/${key}/next`, submit: `/api/public/surveys/${key}/responses` };

let survey = null;
let byId = {};
const answers = {};   // questionId → 答案
const path = [];      // 已走过的题目，末尾为当前题

// ---------- 状态页（与流程图中的分支一一对应） ----------

function statePage(title, text, ...extra) {
  document.title = title;
  mount(app, h("div", { class: "card" }, h("h2", {}, title), text ? h("p", {}, text) : null, ...extra));
}

function header() {
  return h("div", {},
    PREVIEW ? h("div", { class: "banner info" }, "预览模式：可以按跳转规则走一遍，不会保存答卷。",
      h("a", { href: `/surveys/${key}/edit`, style: "margin-left:8px" }, "返回编辑")) : null,
    h("h2", {}, survey.title),
    survey.description ? h("p", { class: "muted" }, survey.description) : null,
    survey.allowAnonymous ? h("p", { class: "muted" }, "本问卷为匿名问卷，不会记录你的身份。") : null,
  );
}

// ---------- 题目 ----------

function hintFor(q) {
  const c = q.constraints || {};
  const parts = [];
  if (c.exactSelect) parts.push(`必须选择 ${c.exactSelect} 项`);
  if (c.minSelect) parts.push(`至少选择 ${c.minSelect} 项`);
  if (c.maxSelect) parts.push(`最多选择 ${c.maxSelect} 项`);
  if (c.minLength) parts.push(`至少 ${c.minLength} 字`);
  if (c.maxLength) parts.push(`最多 ${c.maxLength} 字`);
  if (c.min !== undefined) parts.push(`最小 ${c.min}`);
  if (c.max !== undefined) parts.push(`最大 ${c.max}`);
  if (c.integerOnly) parts.push("必须为整数");
  return parts.join("，");
}

function inputFor(q) {
  const prev = answers[q.questionId];
  if (q.type === "single" || q.type === "multiple") {
    const type = q.type === "single" ? "radio" : "checkbox";
    const inputs = q.options.map((o) => h("input", {
      type, name: q.questionId, value: o.optionId,
      checked: q.type === "single" ? prev === o.optionId : (prev || []).includes(o.optionId),
    }));
    return {
      node: h("div", {}, q.options.map((o, i) => h("label", { class: "fill-option" }, inputs[i], " ", o.text))),
      read: () => {
        const chosen = inputs.filter((x) => x.checked).map((x) => x.value);
        return q.type === "single" ? (chosen[0] ?? null) : chosen;
      },
    };
  }
  if (q.type === "text") {
    const ta = h("textarea", { class: "grow", style: "width:100%" }, prev ?? "");
    const counter = h("span", { class: "muted" });
    const update = () => { counter.textContent = `已输入 ${ta.value.trim().length} 字`; };
    ta.oninput = update; update();
    return { node: h("div", {}, ta, counter), read: () => ta.value };
  }
  const num = h("input", { type: "text", inputmode: "decimal", value: prev ?? "", style: "width:200px" });
  return { node: num, read: () => (num.value.trim() === "" ? null : num.value.trim()) };
}

function showQuestion(qid, error) {
  const q = byId[qid];
  const input = inputFor(q);
  const errBox = h("div", { class: "error" }, error || "");
  const total = survey.questions.length;

  const next = async () => {
    const value = input.read();
    try {
      const r = await api("POST", endpoints.next, { questionId: qid, value });
      answers[qid] = value;
      if (r.next === "END") showFinish();
      else { path.push(r.next); showQuestion(r.next); }
    } catch (err) {
      errBox.textContent = err.message;
    }
  };

  const back = () => {
    answers[qid] = input.read();
    path.pop();
    showQuestion(path[path.length - 1]);
  };

  mount(app, header(), h("div", { class: "card fill-question" },
    h("p", { class: "muted" }, `第 ${q.number} 题 / 共 ${total} 题（根据你的回答，部分题目可能被跳过）`),
    h("h3", {}, q.title, q.required ? h("span", { class: "error" }, " *") : null),
    q.description ? h("p", { class: "muted" }, q.description) : null,
    hintFor(q) ? h("p", { class: "muted" }, hintFor(q)) : null,
    input.node,
    errBox,
    h("div", { class: "actions" },
      path.length > 1 ? h("button", { onclick: back }, "上一题") : h("span"),
      h("button", { class: "primary", onclick: next }, "下一题")),
  ));
}

function showFinish(error) {
  const errBox = error ? errorBanner(error) : null;
  const back = h("button", { onclick: () => showQuestion(path[path.length - 1]) }, "上一题");
  if (PREVIEW) {
    mount(app, header(), h("div", { class: "card" },
      h("h3", {}, "预览结束"),
      h("p", {}, "实际作答路径：", path.map((id) => `Q${byId[id].number}`).join(" → ")),
      h("div", { class: "actions" }, back, h("button", { class: "primary", onclick: () => location.reload() }, "重新预览"))));
    return;
  }
  mount(app, header(), h("div", { class: "card" },
    h("h3", {}, "已完成全部题目"),
    h("p", { class: "muted" }, `共回答 ${path.length} 道题，确认无误后提交。`),
    errBox,
    h("div", { class: "actions" }, back, h("button", { class: "primary", onclick: submit }, "提交"))));
}

async function submit() {
  // 只提交当前路径上的答案；改答后不再经过的题不提交
  const payload = {};
  for (const id of path) if (answers[id] !== undefined) payload[id] = answers[id];
  try {
    const r = await api("POST", endpoints.submit, { answers: payload });
    showDone(r);
  } catch (err) {
    if (err.code === "invalid_answer" && err.details?.[0]) {
      const bad = err.details[0].questionId;
      const at = path.indexOf(bad);
      if (at >= 0) { path.length = at + 1; showQuestion(bad, err.details[0].message); return; }
    }
    if (["survey_ended", "already_submitted", "login_required"].includes(err.code)) {
      statePage("无法提交", err.message);
      return;
    }
    showFinish(err);
  }
}

function showDone(r) {
  const url = r.completion.redirectUrl;
  statePage("提交成功", r.completion.message || "感谢您的填写！",
    h("div", { class: "row" },
      r.allowMultipleSubmit ? h("button", { onclick: () => location.reload() }, "再填一次") : null,
      url ? h("a", { class: "btn primary", href: url, rel: "noopener noreferrer" }, "继续") : null));
}

// ---------- 入口 ----------

function start() {
  byId = Object.fromEntries(survey.questions.map((q) => [q.questionId, q]));
  document.title = survey.title;
  if (!survey.firstQuestionId) { statePage(survey.title, "该问卷还没有题目。"); return; }
  path.push(survey.firstQuestionId);
  showQuestion(survey.firstQuestionId);
}

async function init() {
  if (PREVIEW) requireLogin();
  try {
    const data = await api("GET", endpoints.load);
    if (PREVIEW) { survey = data; start(); return; }

    survey = data.survey;
    if (data.state === "ok") start();
    else if (data.state === "ended") statePage("问卷已结束", `「${survey.title}」${ENDED_TEXT[data.reason]}，感谢关注。`);
    else if (data.state === "already_submitted") statePage("你已填写过", `你已经提交过「${survey.title}」，该问卷每人只能填写一次。`);
    else if (data.state === "login_required") statePage(survey.title, "该问卷需要登录后填写。",
      h("a", { class: "btn primary", href: loginUrl() }, "登录 / 注册"));
  } catch (err) {
    if (!PREVIEW && ["token_expired", "invalid_token"].includes(err.code)) { init(); return; }  // 旧凭证已被清除，按未登录重试
    if (err.status === 404) statePage("问卷不存在", "链接无效，或问卷尚未发布、已被删除。");
    else if (err.status === 401 && PREVIEW) location.href = loginUrl();
    else statePage("出错了", err.message);
  }
}

init();
