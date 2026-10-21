// 填写页（/survey/{slug}）与预览页（/surveys/{id}/preview）共用。
// 一屏一题；"下一题"由后端根据跳转规则计算，前端只记录走过的路径以便"上一题"。
// 左侧定位标记显示进度：已答为涂黑，当前为红框，被跳转跳过的为斜线。

const PREVIEW = location.pathname.startsWith("/surveys/");
const key = pathParam(1);  // 预览为问卷 ID，填写为 slug
const app = document.getElementById("app");

const endpoints = PREVIEW
  ? { load: `/api/surveys/${key}/preview`, next: `/api/surveys/${key}/preview/next` }
  : { load: `/api/public/surveys/${key}`, next: `/api/public/surveys/${key}/next`, submit: `/api/public/surveys/${key}/responses` };

const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

let survey = null;
let byId = {};
const answers = {};   // questionId → 答案
const path = [];      // 已走过的题目，末尾为当前题

// ---------- 页面骨架 ----------

function sheetHead() {
  return h("div", { class: "sheet-head" },
    h("h2", {}, survey.title),
    survey.description ? h("p", {}, survey.description) : null,
    survey.allowAnonymous ? h("p", {}, "匿名问卷，不会记录你的身份。") : null,
  );
}

function previewBar() {
  return PREVIEW ? h("div", { id: "msg" }, h("div", { class: "banner info" },
    "预览模式：按跳转规则走一遍，答卷不会保存。",
    h("a", { href: `/surveys/${key}/edit`, style: "margin-left:10px" }, "返回编辑"))) : null;
}

function statePage(title, text, ...extra) {
  document.title = title;
  mount(app, h("div", { class: "sheet-note" }, h("h2", {}, title), text ? h("p", {}, text) : null, ...extra));
}

function marks(currentId) {
  const current = currentId ? byId[currentId] : null;
  const onPath = new Set(path);
  return h("div", { class: "marks", "aria-hidden": "true" }, survey.questions.map((q) => {
    let state = "";
    if (q.questionId === currentId) state = "current";
    else if (onPath.has(q.questionId)) state = "done";
    else if (!current || q.number < current.number) state = "skipped";
    return h("i", { class: state, title: `第 ${q.number} 题` });
  }));
}

function skippedNumbers(currentNumber) {
  const onPath = new Set(path);
  return survey.questions.filter((q) => q.number < currentNumber && !onPath.has(q.questionId)).map((q) => q.number);
}

// ---------- 题目 ----------

function hintFor(q) {
  const c = q.constraints || {};
  const parts = [];
  if (c.exactSelect) parts.push(`选 ${c.exactSelect} 项`);
  if (c.minSelect && c.maxSelect) parts.push(`选 ${c.minSelect} 至 ${c.maxSelect} 项`);
  else if (c.minSelect) parts.push(`至少选 ${c.minSelect} 项`);
  else if (c.maxSelect) parts.push(`最多选 ${c.maxSelect} 项`);
  if (c.minLength && c.maxLength) parts.push(`${c.minLength} 至 ${c.maxLength} 字`);
  else if (c.minLength) parts.push(`至少 ${c.minLength} 字`);
  else if (c.maxLength) parts.push(`最多 ${c.maxLength} 字`);
  if (c.min !== undefined && c.max !== undefined) parts.push(`${c.min} 至 ${c.max}`);
  else if (c.min !== undefined) parts.push(`不小于 ${c.min}`);
  else if (c.max !== undefined) parts.push(`不大于 ${c.max}`);
  if (c.integerOnly) parts.push("填整数");
  if (q.type === "multiple" && !parts.length) parts.push("可多选");
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
      node: h("div", { role: q.type === "single" ? "radiogroup" : "group" }, q.options.map((o, i) =>
        h("label", { class: "option" + (q.type === "multiple" ? " square" : "") },
          inputs[i],
          h("span", { class: "mark", "aria-hidden": "true" }, LETTERS[i] || "", h("span", { class: "fillin" })),
          h("span", { class: "text" }, o.text)))),
      read: () => {
        const chosen = inputs.filter((x) => x.checked).map((x) => x.value);
        return q.type === "single" ? (chosen[0] ?? null) : chosen;
      },
      focus: () => inputs[0]?.focus(),
    };
  }
  if (q.type === "text") {
    const ta = h("textarea", { style: "width:100%", "aria-label": q.title }, prev ?? "");
    const counter = h("span", { class: "counter" });
    const update = () => { counter.textContent = `${ta.value.trim().length} 字`; };
    ta.oninput = update; update();
    return { node: h("div", {}, ta, counter), read: () => ta.value, focus: () => ta.focus() };
  }
  const num = h("input", { type: "text", inputmode: "decimal", value: prev ?? "", style: "width:220px", "aria-label": q.title });
  return { node: num, read: () => (num.value.trim() === "" ? null : num.value.trim()), focus: () => num.focus() };
}

function showQuestion(qid, error) {
  const q = byId[qid];
  const input = inputFor(q);
  const errBox = h("div", { class: "error", role: "alert" }, error || "");
  const skipped = skippedNumbers(q.number);

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

  const hint = hintFor(q);
  mount(app, previewBar(), sheetHead(), h("div", { class: "answer-sheet" },
    marks(qid),
    h("div", { class: "fill-question" },
      h("p", { class: "progress" },
        `第 ${q.number} 题，共 ${survey.questions.length} 题`,
        skipped.length ? `；根据你的回答，第 ${skipped.join("、")} 题已跳过` : ""),
      h("h3", {}, h("span", { class: "qno" }, q.number), h("span", {}, q.title),
        q.required ? h("span", { class: "req" }, "必答") : null),
      q.description || hint ? h("p", { class: "hint" }, [q.description, hint].filter(Boolean).join("。")) : null,
      h("div", { class: "body" }, input.node),
      errBox,
      h("div", { class: "actions" },
        path.length > 1 ? h("button", { onclick: back }, "上一题") : h("span"),
        h("button", { class: "primary", onclick: next }, "下一题")),
    ),
  ));
  input.focus();
}

function showFinish(error) {
  const back = h("button", { onclick: () => showQuestion(path[path.length - 1]) }, "上一题");
  const route = h("div", { class: "path" }, path.map((id) => h("span", { class: "tag" }, `第 ${byId[id].number} 题`)));
  const content = PREVIEW
    ? [h("h3", {}, "预览结束"), h("p", { class: "muted" }, "本次经过的题目："), route,
        h("div", { class: "actions", style: "margin-left:0" }, back,
          h("button", { class: "primary", onclick: () => location.reload() }, "重新预览"))]
    : [h("h3", {}, "全部题目已答完"), h("p", { class: "muted" }, `你回答了 ${path.length} 道题，确认后提交。`), route,
        error ? errorBanner(error) : null,
        h("div", { class: "actions", style: "margin-left:0" }, back,
          h("button", { class: "primary", onclick: submit }, "提交答卷"))];
  mount(app, previewBar(), sheetHead(), h("div", { class: "answer-sheet" },
    marks(null), h("div", { class: "fill-question" }, ...content)));
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
      statePage("答卷未能提交", err.message);
      return;
    }
    showFinish(err);
  }
}

function showDone(r) {
  const url = r.completion.redirectUrl;
  statePage("答卷已提交", r.completion.message || "感谢你的填写。",
    h("div", { class: "row" },
      r.allowMultipleSubmit ? h("button", { onclick: () => location.reload() }, "再填一份") : null,
      url ? h("a", { class: "btn primary", href: url, rel: "noopener noreferrer" }, "继续前往") : null));
}

// ---------- 入口 ----------

function start() {
  byId = Object.fromEntries(survey.questions.map((q) => [q.questionId, q]));
  document.title = survey.title;
  if (!survey.firstQuestionId) { statePage(survey.title, "这份问卷还没有题目。"); return; }
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
    else if (data.state === "ended") statePage("问卷已结束", `「${survey.title}」${ENDED_TEXT[data.reason]}，不再接收新的答卷。`);
    else if (data.state === "already_submitted") statePage("你已提交过答卷", `「${survey.title}」每人只能填写一次。`);
    else if (data.state === "login_required") statePage(survey.title, "这份问卷需要登录后填写，登录后会自动回到这里。",
      h("div", { class: "row" }, h("a", { class: "btn primary", href: loginUrl() }, "登录或注册")));
  } catch (err) {
    if (!PREVIEW && ["token_expired", "invalid_token"].includes(err.code)) { init(); return; }  // 旧凭证已被清除，按未登录重试
    if (err.status === 404) statePage("找不到这份问卷", "链接可能有误，或者问卷还没发布、已被删除。请向发送链接的人确认。");
    else if (err.status === 401 && PREVIEW) location.href = loginUrl();
    else statePage("页面加载失败", err.message);
  }
}

init();
