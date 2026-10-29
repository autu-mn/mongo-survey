// 【第二阶段新增】独立题目创建及版本分叉共用表单；选项保留旧 ID。
function questionContentForm(initial = {}) {
  const type = h("select", {}, Object.entries(TYPE_TEXT).map(([key, label]) =>
    h("option", { value: key, selected: key === (initial.type || "single") }, label)));
  const title = h("input", { type: "text", class: "grow", maxlength: 500,
    value: initial.title || "", placeholder: "题目标题", "aria-label": "题目标题" });
  const description = h("input", { type: "text", class: "grow", maxlength: 2000,
    value: initial.description || "", placeholder: "说明（选填）", "aria-label": "题目说明" });
  const required = h("input", { type: "checkbox", checked: !!initial.required });
  const optionList = h("div", { class: "col" });
  const optionArea = h("div", {});
  const constraints = h("div", { class: "row" });
  function optionLine(option = {}) {
    const input = h("input", { type: "text", class: "grow", value: option.text || "",
      maxlength: 200, placeholder: "选项内容", "aria-label": "选项内容" });
    const line = h("div", { class: "option-line" }, input,
      h("button", { type: "button", class: "small danger", onclick: () => line.remove() }, "移除"));
    line.dataset.optionId = option.optionId || "";
    line.read = () => ({ ...(line.dataset.optionId ? { optionId: line.dataset.optionId } : {}), text: input.value.trim() });
    optionList.append(line);
  }
  const initialOptions = (initial.options || []).filter((o) => !o.hidden);
  (initialOptions.length ? initialOptions : [{}, {}]).forEach(optionLine);
  optionArea.append(h("label", {}, "选项"), optionList,
    h("button", { type: "button", class: "small", onclick: () => optionLine() }, "+ 添加选项"));
  function numberField(key, label, value) {
    return h("label", {}, label, " ", h("input", { type: "number", "data-key": key,
      value: value ?? "", style: "width:90px", step: "any" }));
  }
  function refreshType() {
    optionArea.hidden = !["single", "multiple"].includes(type.value);
    const c = initial.type === type.value ? (initial.constraints || {}) : {};
    const fields = type.value === "multiple" ? [["minSelect", "至少选"], ["maxSelect", "最多选"], ["exactSelect", "必须选"]]
      : type.value === "text" ? [["minLength", "最少字数"], ["maxLength", "最多字数"]]
        : type.value === "number" ? [["min", "最小值"], ["max", "最大值"]] : [];
    mount(constraints, fields.map(([key, label]) => numberField(key, label, c[key])),
      type.value === "number" ? h("label", {}, h("input", { type: "checkbox", "data-key": "integerOnly",
        checked: !!c.integerOnly }), " 必须为整数") : null);
  }
  type.addEventListener("change", refreshType);
  refreshType();
  return {
    node: h("div", { class: "col" },
      h("div", { class: "row" }, type, title), description,
      h("label", {}, required, " 必答"), optionArea, constraints),
    read() {
      const c = {};
      constraints.querySelectorAll("[data-key]").forEach((el) => {
        if (el.type === "checkbox") { if (el.checked) c[el.dataset.key] = true; }
        else if (el.value !== "") c[el.dataset.key] = Number(el.value);
      });
      return { type: type.value, title: title.value.trim(), description: description.value.trim(),
        required: required.checked, options: optionArea.hidden ? [] : [...optionList.children].map((el) => el.read()).filter((o) => o.text),
        constraints: c };
    },
  };
}
