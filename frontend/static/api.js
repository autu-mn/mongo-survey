// 所有页面共用：请求封装、登录状态、DOM 构造、显示文字。
// 前端只调用后端 API，不实现任何跳转或校验逻辑（都在后端）。

class ApiError extends Error {
  constructor(status, body) {
    super(body?.message || `请求失败（${status}）`);
    this.status = status;
    this.code = body?.code;
    this.details = body?.details;
  }
}

const Auth = {
  token: () => localStorage.getItem("token"),
  user: () => JSON.parse(localStorage.getItem("user") || "null"),
  save(token, user) {
    localStorage.setItem("token", token);
    localStorage.setItem("user", JSON.stringify(user));
  },
  clear() {
    localStorage.removeItem("token");
    localStorage.removeItem("user");
  },
};

function loginUrl() {
  return "/login?redirect=" + encodeURIComponent(location.pathname + location.search);
}

async function api(method, path, body, extraHeaders = {}) {
  const headers = { ...extraHeaders };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (Auth.token()) headers["Authorization"] = "Bearer " + Auth.token();
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && ["token_expired", "invalid_token"].includes(data?.code)) Auth.clear();
    throw new ApiError(res.status, data);
  }
  return data;
}

// 创作者页面：未登录或凭证失效时跳到登录页，登录后回到当前页
function requireLogin() {
  if (!Auth.token()) {
    location.href = loginUrl();
    throw new Error("redirecting");
  }
}

async function creatorCall(method, path, body, headers) {
  try {
    return await api(method, path, body, headers);
  } catch (e) {
    if (e.status === 401) location.href = loginUrl();
    throw e;
  }
}

// ---------- DOM ----------

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (k === "class") node.className = v;
    else if (k === "value") node.value = v;
    else if (k === "checked") node.checked = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function mount(root, ...children) {
  root.replaceChildren(...children.flat().filter(Boolean));
}

function renderNav() {
  const user = Auth.user();
  const nav = h("header", { class: "nav" },
    h("a", { class: "brand", href: "/" }, brandMark(), "问卷系统"),
    h("a", { href: "/" }, "我创建的"),
    h("a", { href: "/#joined" }, "我参与的"),
    h("span", { class: "spacer" }),
    user ? h("span", { class: "who" }, user.username) : null,
    user ? h("a", { href: "#", onclick: (e) => { e.preventDefault(); Auth.clear(); location.href = "/login"; } }, "退出") : h("a", { href: loginUrl() }, "登录"),
  );
  document.body.prepend(nav);
}

function brandMark() {
  return h("span", { class: "brand-mark", "aria-hidden": "true" }, h("i"), h("i"), h("i"));
}

function errorBanner(err) {
  const details = Array.isArray(err?.details) ? err.details : [];
  return h("div", { class: "banner error" },
    err?.message || String(err),
    details.length ? h("ul", {}, details.map((d) => h("li", {}, d.message))) : null,
  );
}

function flash(container, node, ms = 4000) {
  container.replaceChildren(node);
  if (ms) setTimeout(() => { if (container.firstChild === node) container.replaceChildren(); }, ms);
}

// ---------- 显示文字 ----------

const STATUS_TEXT = { draft: "草稿", open: "进行中", expired: "已截止", full: "已满额", closed: "已关闭" };
const TYPE_TEXT = { single: "单选", multiple: "多选", text: "文本填空", number: "数字填空" };
const ENDED_TEXT = { closed: "问卷已关闭", expired: "问卷已过截止时间", full: "问卷已收满" };

function statusBadge(displayStatus) {
  return h("span", { class: "badge " + displayStatus }, STATUS_TEXT[displayStatus] || displayStatus);
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

function surveyLink(slug) {
  return `${location.origin}/survey/${slug}`;
}

function pathParam(index) {
  return decodeURIComponent(location.pathname.split("/").filter(Boolean)[index]);
}
