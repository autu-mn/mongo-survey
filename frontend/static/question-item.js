// 【第二阶段新增】题目详情：版本、共享、引用及本人同版跨卷统计。
requireLogin();
renderNav();
const itemId = pathParam(1);
const itemMsg = document.getElementById("msg");
const itemApp = document.getElementById("app");
const itemBase = `/api/question-items/${itemId}`;
let item = null;
let versions = [];
let usage = null;
const itemError = (err) => flash(itemMsg, errorBanner(err), 0);

function preview(version) {
  const c = version.content;
  return h("div", { class: "version-preview" },
    h("strong", {}, c.title), h("span", { class: "tag" }, TYPE_TEXT[c.type]),
    c.required ? h("span", { class: "tag" }, "必答") : null,
    c.description ? h("p", { class: "muted" }, c.description) : null,
    c.options.length ? h("ol", {}, c.options.map((o) => h("li", {}, o.text, o.hidden ? "（已隐藏）" : ""))) : null,
    Object.keys(c.constraints).length ? h("p", { class: "muted" },
      "约束：" + Object.entries(c.constraints).map(([key, value]) => `${key}=${value}`).join("、")) : null);
}

function renderHistory(owner) {
  const byId = Object.fromEntries(versions.map((v) => [v.id, v.versionNo]));
  return h("div", { class: "card" }, h("h3", {}, "版本历史"),
    h("p", { class: "muted" }, "版本号是创建顺序；父版本显示分叉关系。旧版本会一直保留。"),
    versions.map((v) => h("div", { class: "version-row" },
      h("div", { class: "row" }, h("strong", {}, `v${v.versionNo}`),
        h("span", { class: "muted" }, v.parentVersionId ? `来自 v${byId[v.parentVersionId] || "?"}` : "初始版本"),
        h("span", { class: "muted" }, fmtTime(v.createdAt)),
        owner ? h("button", { class: "small", onclick: async () => {
          if (!confirm(`从 v${v.versionNo} 的原内容创建一个新版本？旧版本不会被覆盖。`)) return;
          try { await creatorCall("POST", `${itemBase}/versions`, { parentVersionId: v.id }); await loadItem(); }
          catch (err) { itemError(err); }
        } }, "恢复为新版本") : null), preview(v))));
}

function renderFork() {
  const parent = h("select", { "aria-label": "分叉来源版本" }, versions.map((v) =>
    h("option", { value: v.id, selected: v.id === versions.at(-1).id }, `v${v.versionNo} · ${v.content.title}`)));
  const slot = h("div", {});
  let form;
  const refresh = () => { form = questionContentForm(versions.find((v) => v.id === parent.value).content); mount(slot, form.node); };
  parent.addEventListener("change", refresh);
  refresh();
  return h("div", { class: "card" }, h("h3", {}, "从旧版创建新版本"),
    h("p", { class: "muted" }, "选择任意父版本，修改内容后保存。草稿问卷不会自动换版，需在编辑页明确替换。"),
    h("div", { class: "col" }, h("label", {}, "父版本"), parent), slot,
    h("button", { class: "primary", onclick: async () => {
      try { await creatorCall("POST", `${itemBase}/versions`,
        { parentVersionId: parent.value, content: form.read() }); await loadItem(); }
      catch (err) { itemError(err); }
    } }, "创建新版本"));
}

function renderSharing() {
  const visibility = h("select", {}, [
    ["private", "私有"], ["public", "全站登录用户可用"], ["selected", "指定用户可用"],
  ].map(([key, label]) => h("option", { value: key, selected: item.visibility === key }, label)));
  const usernames = h("input", { type: "text", class: "grow", value: (item.sharedUsernames || []).join(", "),
    placeholder: "用户名，用逗号分隔", "aria-label": "共享用户名" });
  const target = h("div", { class: "col" }, h("label", {}, "指定用户"), usernames);
  const refresh = () => { target.hidden = visibility.value !== "selected"; };
  visibility.addEventListener("change", refresh);
  refresh();
  return h("div", { class: "card" }, h("h3", {}, "共享设置"),
    h("p", { class: "muted" }, "权限适用于这道题的全部版本。撤销只阻止新引用，已有问卷继续使用自己的快照。"),
    h("div", { class: "col" }, h("label", {}, "可见范围"), visibility), target,
    h("button", { onclick: async () => {
      try { const names = visibility.value === "selected"
        ? usernames.value.split(/[，,]/).map((s) => s.trim()).filter(Boolean) : [];
        await creatorCall("PUT", `${itemBase}/sharing`, { visibility: visibility.value, usernames: names });
        await loadItem(); flash(itemMsg, h("div", { class: "banner ok" }, "共享设置已保存")); }
      catch (err) { itemError(err); }
    } }, "保存共享设置"));
}

function renderUsage() {
  return h("div", { class: "card" }, h("h3", {}, "引用情况"),
    h("p", { class: "muted" }, `其他用户的问卷：${usage.otherSurveyCount} 份（只显示数量）`),
    usage.ownSurveys.length ? usage.ownSurveys.map((s) => h("p", {},
      h("a", { href: `/surveys/${s.surveyId}` }, s.title),
      ` · ${STATUS_TEXT[s.status] || s.status} · 版本 ${s.versionIds.map((id) =>
        `v${versions.find((v) => v.id === id)?.versionNo || "?"}`).join("、")}`))
      : h("p", { class: "muted" }, "你自己的问卷尚未引用这道题。"));
}

function renderStats(data) {
  const base = [h("p", {}, `v${data.versionNo} · ${data.title} · 仅统计我自己的 ${data.ownerSurveyCount} 份未删除问卷`),
    h("p", {}, `${data.answeredCount} 条可归版答案；${data.unattributedCount} 条旧答案无法归版，未计入下方分布。`)];
  if (data.type === "single" || data.type === "multiple") {
    const unit = data.type === "multiple" ? "次" : "人";
    base.push(data.options.length ? h("table", { class: "stat-table" }, h("tbody", {}, data.options.map((o) =>
      h("tr", {}, h("td", {}, o.text, o.hidden ? "（已隐藏）" : ""),
        h("td", {}, h("div", { class: "bar-wrap" }, h("div", { class: "bar", style: `width:${o.ratio * 100}%` }))),
        h("td", { class: "num" }, `${o.count} ${unit}`), h("td", { class: "num" }, `${(o.ratio * 100).toFixed(1)}%`))))) : null);
  } else {
    if (data.type === "number") base.push(h("p", {}, data.average === null ? "暂无数值答案" :
      `平均 ${data.average} · 最小 ${data.min} · 最大 ${data.max}`));
    base.push(data.values.length ? h("details", {}, h("summary", {}, `查看 ${data.values.length} 条答案`),
      h("ol", {}, data.values.map((v) => h("li", {}, String(v))))) : h("p", { class: "muted" }, "暂无可归版答案"));
  }
  return base;
}

function statsCard() {
  const select = h("select", { "aria-label": "统计版本" }, versions.map((v) =>
    h("option", { value: v.id, selected: v.id === versions.at(-1).id }, `v${v.versionNo} · ${v.content.title}`)));
  const slot = h("div", {});
  async function loadStats() {
    try { const data = await creatorCall("GET", `${itemBase}/versions/${select.value}/stats`);
      mount(slot, renderStats(data)); } catch (err) { mount(slot, errorBanner(err)); }
  }
  select.addEventListener("change", loadStats);
  loadStats();
  return h("div", { class: "card" }, h("h3", {}, "同版跨卷统计"),
    h("div", { class: "row" }, h("label", {}, "选择具体版本"), select), slot);
}

async function loadItem() {
  try {
    [item, versions, usage] = await Promise.all([
      creatorCall("GET", itemBase), creatorCall("GET", `${itemBase}/versions`),
      creatorCall("GET", `${itemBase}/usage`),
    ]);
    const owner = item.ownerId === Auth.user()?.id;
    mount(itemApp,
      h("div", { class: "card" }, h("div", { class: "title-row" },
        h("h2", {}, item.latestVersion?.content.title || "题目详情"),
        h("span", { class: "tag" }, item.visibility === "private" ? "私有" : item.visibility === "public" ? "公开" : "定向共享"),
        h("span", { class: "spacer" }), h("a", { href: "/question-banks" }, "返回题库")),
        h("p", { class: "muted" }, `创建于 ${fmtTime(item.createdAt)}；当前最新为 v${item.latestVersion?.versionNo || 1}。`),
        !owner && item.canSelectNew ? h("button", { onclick: async () => {
          try { const copy = await creatorCall("POST", "/api/question-items",
            { sourceVersionId: item.latestVersion.id }); location.href = `/questions/${copy.id}`; }
          catch (err) { itemError(err); }
        } }, "复制为我的独立题目") : null,
        !owner && !item.canSelectNew ? h("p", { class: "muted" }, "共享已撤销：可查看本人的旧问卷引用与统计，不能再选用或复制此题。") : null),
      renderHistory(owner), owner ? renderFork() : null, owner ? renderSharing() : null,
      renderUsage(), statsCard(),
    );
  } catch (err) { mount(itemApp, errorBanner(err)); }
}
loadItem();
