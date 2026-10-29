// 【第二阶段新增】题库列表、共享浏览及命名题库详情。
requireLogin();
renderNav();
const bankMsg = document.getElementById("msg");
const bankApp = document.getElementById("app");
const bankId = location.pathname.split("/").filter(Boolean)[1];
function bankError(err) { flash(bankMsg, errorBanner(err), 0); }

async function indexPage() {
  try {
    const [banks, mine, shared] = await Promise.all([
      creatorCall("GET", "/api/question-banks"),
      creatorCall("GET", "/api/question-items?scope=mine&limit=100"),
      creatorCall("GET", "/api/question-items?scope=shared&limit=100"),
    ]);
    const name = h("input", { type: "text", maxlength: 100, placeholder: "题库名称", "aria-label": "题库名称" });
    const form = questionContentForm();
    mount(bankApp,
      h("div", { class: "card" }, h("div", { class: "title-row" }, h("h2", {}, "我的题库"),
        h("span", { class: "spacer" }), h("a", { href: "/" }, "返回我的问卷")),
        h("p", { class: "muted" }, "可以建立多个命名题库；同一道题可放入多个题库。"),
        h("div", { class: "row" }, name, h("button", { class: "primary", onclick: async () => {
          try { const b = await creatorCall("POST", "/api/question-banks", { name: name.value.trim() });
            location.href = `/question-banks/${b.id}`; } catch (err) { bankError(err); }
        } }, "新建题库"))),
      h("div", { class: "card" }, h("h3", {}, "命名题库"), banks.length
        ? h("div", { class: "library-grid" }, banks.map((b) => h("a", { class: "library-tile", href: `/question-banks/${b.id}` },
          h("strong", {}, b.name), h("span", { class: "muted" }, `${b.itemCount} 道题`))))
        : h("p", { class: "muted" }, "还没有题库。上方输入名称即可创建。")),
      h("div", { class: "card" }, h("h3", {}, "我创建的题目"),
        mine.length ? mine.map((q) => h("p", {}, h("a", { href: `/questions/${q.id}` },
          `${q.latestVersion?.content.title || "未命名题目"} · v${q.latestVersion?.versionNo || 1}`)))
          : h("p", { class: "muted" }, "还没有独立题目。可以在下方创建，也可以从问卷编辑页保存。")),
      h("div", { class: "card" }, h("h3", {}, "创建独立题目"), form.node,
        h("button", { class: "primary", onclick: async () => {
          try { const q = await creatorCall("POST", "/api/question-items", { content: form.read() });
            location.href = `/questions/${q.id}`; } catch (err) { bankError(err); }
        } }, "保存题目")),
      h("div", { class: "card" }, h("h3", {}, "共享给我的题目"),
        shared.length ? shared.map((q) => h("p", {}, h("a", { href: `/questions/${q.id}` },
          `${q.latestVersion?.content.title || "未命名题目"} · v${q.latestVersion?.versionNo || 1}`),
          h("span", { class: "tag" }, q.visibility === "public" ? "公开" : "定向共享")))
          : h("p", { class: "muted" }, "目前没有可用的共享题目。")),
    );
  } catch (err) { mount(bankApp, errorBanner(err)); }
}

async function detailPage() {
  try {
    const [bank, mine, shared] = await Promise.all([
      creatorCall("GET", `/api/question-banks/${bankId}`),
      creatorCall("GET", "/api/question-items?scope=mine&limit=100"),
      creatorCall("GET", "/api/question-items?scope=shared&limit=100"),
    ]);
    const name = h("input", { type: "text", value: bank.name, maxlength: 100, "aria-label": "题库名称" });
    const available = [...mine, ...shared].filter((i) => !bank.items.some((member) => member.itemId === i.id));
    const pick = h("select", { "aria-label": "选择要收录的题目" },
      available.length ? available.map((q) => h("option", { value: q.id }, q.latestVersion?.content.title || q.id))
        : h("option", { value: "" }, "暂无可加入的题目"));
    mount(bankApp,
      h("div", { class: "card" }, h("div", { class: "title-row" }, h("h2", {}, bank.name),
        h("span", { class: "spacer" }), h("a", { href: "/question-banks" }, "返回题库")),
        h("div", { class: "row" }, name,
          h("button", { onclick: async () => { try { await creatorCall("PUT", `/api/question-banks/${bankId}`, { name: name.value.trim() });
            await detailPage(); } catch (err) { bankError(err); } } }, "保存名称"),
          h("button", { class: "danger", onclick: async () => {
            if (!confirm("删除题库？题目、版本和问卷不会被删除。")) return;
            try { await creatorCall("DELETE", `/api/question-banks/${bankId}`); location.href = "/question-banks"; }
            catch (err) { bankError(err); }
          } }, "删除题库"))),
      h("div", { class: "card" }, h("h3", {}, `题目清单（${bank.itemCount}）`),
        bank.items.length ? bank.items.map((member) => h("div", { class: "library-row" },
          member.available ? h("a", { href: `/questions/${member.itemId}` },
            `${member.item.latestVersion?.content.title || "未命名"} · v${member.item.latestVersion?.versionNo || 1}`)
            : h("span", { class: "muted" }, "共享权限已撤销，当前不可选用"),
          h("button", { class: "small danger", onclick: async () => {
            try { await creatorCall("DELETE", `/api/question-banks/${bankId}/items/${member.itemId}`); await detailPage(); }
            catch (err) { bankError(err); }
          } }, "移出"))) : h("p", { class: "muted" }, "题库还是空的。"),
        h("div", { class: "row", style: "margin-top:18px" }, pick,
          h("button", { class: "primary", disabled: !available.length, onclick: async () => {
            try { await creatorCall("PUT", `/api/question-banks/${bankId}/items/${pick.value}`); await detailPage(); }
            catch (err) { bankError(err); }
          } }, "加入题库"))),
    );
  } catch (err) { mount(bankApp, errorBanner(err)); }
}

(bankId ? detailPage : indexPage)();
