// 编辑页：题目卡片 + 跳转规则区。每次修改都把打开时读到的 updatedAt 作为 If-Match 发给后端（乐观锁）。

requireLogin();
renderNav();

const surveyId = pathParam(1);
const msg = document.getElementById("msg");
let survey = null;

const OPS = {
  single: [["eq", "选了"], ["ne", "没选"], ["in", "选了其中之一"]],
  multiple: [["includes", "包含"], ["includesAny", "包含任一"], ["includesAll", "包含全部"], ["equalsSet", "恰好是"]],
  number: [["eq", "等于"], ["ne", "不等于"], ["gt", "大于"], ["gte", "大于等于"], ["lt", "小于"], ["lte", "小于等于"], ["between", "介于"]],
};
const MULTI_VALUE_OPS = ["in", "includesAny", "includesAll", "equalsSet"];

async function edit(method, path, body, okText) {
  try {
    survey = await creatorCall(method, path, body, { "If-Match": survey.updatedAt });
    render();
    if (okText) flash(msg, h("div", { class: "banner ok" }, okText), 2500);
    return true;
  } catch (err) {
    const banner = errorBanner(err);
    if (err.code === "edit_conflict") banner.append(" ", h("button", { class: "small", onclick: load }, "重新加载"));
    flash(msg, banner, 0);
    return false;
  }
}

const base = () => `/api/surveys/${surveyId}`;
const isLocked = () => survey.status !== "draft";
const sorted = () => [...survey.questions].sort((a, b) => a.order - b.order);
const label = (q) => `Q${q.order} ${q.title}${q.hidden ? "（已隐藏）" : ""}`;

// ---------- 基本信息 ----------

function basicInfoCard() {
  const title = h("input", { type: "text", class: "grow", value: survey.title, maxlength: 200 });
  const desc = h("textarea", { class: "grow" }, survey.description);
  return h("div", { class: "card" },
    h("div", { class: "row" },
      h("h2", { style: "margin:0" }, "编辑问卷"), statusBadge(survey.displayStatus),
      h("span", { class: "spacer", style: "flex:1" }),
      h("a", { class: "btn", href: `/surveys/${surveyId}/preview` }, "预览"),
      h("a", { class: "btn", href: `/surveys/${surveyId}` }, "返回管理页"),
    ),
    isLocked() ? h("div", { class: "banner info", style: "margin-top:12px" },
      "问卷已发布：删除题目或选项会改为隐藏（统计中保留历史数据），不能修改题型。") : null,
    h("div", { class: "col" }, h("label", {}, "标题"), title),
    h("div", { class: "col" }, h("label", {}, "说明"), desc),
    h("button", { onclick: () => edit("PATCH", base(), { title: title.value.trim(), description: desc.value }, "已保存") }, "保存标题和说明"),
  );
}

// ---------- 题目卡片 ----------

function constraintInputs(type, c) {
  const num = (key, text, attrs = {}) => {
    const input = h("input", { type: "number", "data-key": key, value: c[key] ?? "", style: "width:90px", ...attrs });
    return h("span", {}, text, " ", input);
  };
  if (type === "multiple") return [num("minSelect", "至少选", { min: 0 }), num("maxSelect", "最多选", { min: 1 }), num("exactSelect", "必须选", { min: 1 })];
  if (type === "text") return [num("minLength", "最少字数", { min: 0 }), num("maxLength", "最多字数", { min: 1 })];
  if (type === "number") return [num("min", "最小值", { step: "any" }), num("max", "最大值", { step: "any" }),
    h("label", {}, h("input", { type: "checkbox", "data-key": "integerOnly", checked: !!c.integerOnly }), " 必须是整数")];
  return [];
}

function readConstraints(box) {
  const c = {};
  box.querySelectorAll("[data-key]").forEach((el) => {
    if (el.type === "checkbox") { if (el.checked) c[el.dataset.key] = true; }
    else if (el.value !== "") c[el.dataset.key] = Number(el.value);
  });
  return c;
}

function optionEditor(q) {
  const box = h("div", {});
  const addLine = (opt) => {
    const input = h("input", { type: "text", class: "grow", value: opt?.text || "", maxlength: 200 });
    const line = h("div", { class: "option-line" }, input,
      h("button", { class: "small danger", onclick: () => line.remove() }, "删除"));
    line.dataset.optionId = opt?.optionId || "";
    line.read = () => ({ optionId: line.dataset.optionId || null, text: input.value.trim() });
    box.append(line);
  };
  (q.options || []).filter((o) => !o.hidden).forEach(addLine);
  const hiddenOpts = (q.options || []).filter((o) => o.hidden);
  return {
    node: h("div", { class: "col" }, h("label", {}, "选项"), box,
      hiddenOpts.length ? h("span", { class: "muted" }, "已隐藏的选项：", hiddenOpts.map((o) => o.text).join("、")) : null,
      h("div", {}, h("button", { class: "small", onclick: () => addLine(null) }, "+ 添加选项"))),
    read: () => [...box.children].map((line) => line.read()).filter((o) => o.text),
  };
}

function questionCard(q, index, list) {
  const typeSel = h("select", { disabled: isLocked() },
    Object.entries(TYPE_TEXT).map(([k, v]) => h("option", { value: k, selected: k === q.type }, v)));
  const title = h("input", { type: "text", class: "grow", value: q.title, maxlength: 500 });
  const desc = h("input", { type: "text", class: "grow", value: q.description || "", placeholder: "题目说明（选填）" });
  const required = h("input", { type: "checkbox", checked: q.required });
  const isChoice = ["single", "multiple"].includes(q.type);
  const options = isChoice ? optionEditor(q) : null;
  const consBox = h("div", { class: "row" }, constraintInputs(q.type, q.constraints || {}));

  const save = () => {
    const type = typeSel.value;
    const toChoice = ["single", "multiple"].includes(type);
    // 草稿中把填空题改成选择题时，先给两个默认选项，保存后再在卡片中修改
    const opts = toChoice ? (options ? options.read() : [{ text: "选项 1" }, { text: "选项 2" }]) : [];
    return edit("PUT", `${base()}/questions/${q.questionId}`, {
      type, title: title.value.trim(), description: desc.value, required: required.checked,
      options: opts, constraints: type === q.type ? readConstraints(consBox) : {},
    }, "题目已保存");
  };

  const move = (delta) => {
    const ids = list.map((x) => x.questionId);
    const j = index + delta;
    [ids[index], ids[j]] = [ids[j], ids[index]];
    edit("PUT", `${base()}/questions/order`, { questionIds: ids }, "顺序已调整");
  };

  return h("div", { class: "card question-card" + (q.hidden ? " is-hidden" : "") },
    h("div", { class: "row" },
      h("strong", {}, `Q${q.order}`), h("span", { class: "badge" }, TYPE_TEXT[q.type]),
      q.hidden ? h("span", { class: "badge hidden" }, "已隐藏") : null,
      h("span", { style: "flex:1" }),
      h("button", { class: "small", disabled: index === 0, onclick: () => move(-1) }, "上移"),
      h("button", { class: "small", disabled: index === list.length - 1, onclick: () => move(1) }, "下移"),
      q.hidden
        ? h("button", { class: "small", onclick: () => edit("POST", `${base()}/questions/${q.questionId}/restore`, undefined, "已恢复") }, "恢复")
        : h("button", {
          class: "small danger",
          onclick: () => confirm(isLocked() ? "问卷已发布，该题将被隐藏（统计中保留）。继续？" : "确定删除该题？指向它的跳转规则也会被删除。")
            && edit("DELETE", `${base()}/questions/${q.questionId}`, undefined, isLocked() ? "已隐藏" : "已删除"),
        }, isLocked() ? "隐藏" : "删除"),
    ),
    h("div", { class: "row", style: "margin-top:10px" }, typeSel, title),
    h("div", { class: "row", style: "margin-top:8px" }, desc, h("label", {}, required, " 必答")),
    options ? h("div", { style: "margin-top:10px" }, options.node) : null,
    consBox.children.length ? h("div", { style: "margin-top:6px" }, consBox) : null,
    h("div", { style: "margin-top:10px" }, h("button", { class: "primary", onclick: save }, "保存本题")),
    q.type in OPS ? logicBox(q) : h("p", { class: "muted" }, "文本填空题不设置跳转，答完后按顺序进入下一题。"),
  );
}

// ---------- 跳转规则区 ----------

function targetSelect(q, current, withDefault) {
  const later = sorted().filter((x) => x.order > q.order);
  return h("select", {},
    withDefault ? h("option", { value: "" }, "按顺序进入下一题") : null,
    later.map((x) => h("option", { value: x.questionId, selected: x.questionId === current }, label(x))),
    h("option", { value: "END", selected: current === "END" }, "结束问卷"),
  );
}

function valueEditor(q, op, value) {
  const visible = q.options.filter((o) => !o.hidden || o.optionId === value || (Array.isArray(value) && value.includes(o.optionId)));
  if (q.type !== "number" && MULTI_VALUE_OPS.includes(op)) {
    const boxes = visible.map((o) => h("input", { type: "checkbox", value: o.optionId, checked: Array.isArray(value) && value.includes(o.optionId) }));
    return { node: h("span", { class: "checks" }, visible.map((o, i) => h("label", {}, boxes[i], " ", o.text))),
      read: () => boxes.filter((b) => b.checked).map((b) => b.value) };
  }
  if (q.type !== "number") {
    const sel = h("select", {}, visible.map((o) => h("option", { value: o.optionId, selected: o.optionId === value }, o.text)));
    return { node: sel, read: () => sel.value };
  }
  if (op === "between") {
    const [lo, hi] = Array.isArray(value) ? value : ["", ""];
    const a = h("input", { type: "number", step: "any", value: lo, style: "width:80px" });
    const b = h("input", { type: "number", step: "any", value: hi, style: "width:80px" });
    return { node: h("span", {}, a, " 至 ", b), read: () => [Number(a.value), Number(b.value)] };
  }
  const n = h("input", { type: "number", step: "any", value: typeof value === "number" ? value : "", style: "width:100px" });
  return { node: n, read: () => (n.value === "" ? null : Number(n.value)) };
}

function ruleRow(q, rule, rows) {
  const opSel = h("select", {}, OPS[q.type].map(([k, v]) => h("option", { value: k, selected: k === rule?.when.op }, v)));
  let editor = valueEditor(q, opSel.value, rule?.when.value);
  const valueSlot = h("span", {}, editor.node);
  opSel.onchange = () => { editor = valueEditor(q, opSel.value, null); valueSlot.replaceChildren(editor.node); };
  const goto = targetSelect(q, rule?.goto, false);
  const row = h("div", { class: "logic-row" }, "如果答案", opSel, valueSlot, "则跳到", goto,
    h("button", { class: "small danger", onclick: () => row.remove() }, "删除"));
  row.read = () => ({ when: { op: opSel.value, value: editor.read() }, goto: goto.value });
  rows.append(row);
}

function logicBox(q) {
  const rows = h("div", {});
  q.logic.forEach((r) => ruleRow(q, r, rows));
  const defaultGoto = targetSelect(q, q.defaultGoto, true);
  const save = () => edit("PUT", `${base()}/questions/${q.questionId}/logic`, {
    rules: [...rows.children].map((r) => r.read()),
    defaultGoto: defaultGoto.value || null,
  }, "跳转规则已保存");
  return h("div", { class: "logic-box" },
    h("strong", {}, "跳转规则"), h("span", { class: "muted" }, "（按顺序匹配，命中第一条即跳转；只能跳到后面的题）"),
    h("div", { style: "margin-top:8px" }, rows),
    h("div", { class: "logic-row" }, h("button", { class: "small", onclick: () => ruleRow(q, null, rows) }, "+ 添加规则")),
    h("div", { class: "logic-row" }, "否则跳到", defaultGoto),
    h("button", { onclick: save }, "保存跳转规则"),
  );
}

// ---------- 添加题目 ----------

function addQuestionCard() {
  const typeSel = h("select", {}, Object.entries(TYPE_TEXT).map(([k, v]) => h("option", { value: k }, v)));
  const title = h("input", { type: "text", class: "grow", placeholder: "题目标题" });
  const add = () => {
    const type = typeSel.value;
    const body = { type, title: title.value.trim(), required: type !== "text" };
    if (type === "single" || type === "multiple") body.options = [{ text: "选项 1" }, { text: "选项 2" }];
    edit("POST", `${base()}/questions`, body, "题目已添加");
  };
  return h("div", { class: "card" }, h("h3", {}, "添加题目"),
    h("div", { class: "row" }, typeSel, title, h("button", { class: "primary", onclick: add }, "添加")),
    h("p", { class: "muted" }, "选择题会先生成两个默认选项，添加后在题目卡片中修改。"));
}

function render() {
  const list = sorted();
  mount(document.getElementById("app"),
    basicInfoCard(),
    list.length ? list.map((q, i) => questionCard(q, i, list)) : h("div", { class: "card muted" }, "还没有题目。"),
    addQuestionCard(),
  );
}

async function load() {
  try {
    survey = await creatorCall("GET", base());
    msg.replaceChildren();
    render();
  } catch (err) {
    mount(document.getElementById("app"), errorBanner(err));
  }
}

load();
