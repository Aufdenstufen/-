#!/usr/bin/env node
"use strict";

/**
 * 拾级而上 · 本地后台服务
 * ---------------------------------------------------------------
 * 零依赖，只用 Node 内置模块。启动：
 *     node server.js
 * 然后访问 http://127.0.0.1:8787/      站点
 *           http://127.0.0.1:8787/admin 后台
 *
 * 数据保存在同目录的 content.json；每次保存都会留一份 content.backup.json。
 * 首次启动会生成随机密码，写入 admin.config.json（只存 scrypt 哈希）。
 * 忘记密码：删掉 admin.config.json 重启，或设置环境变量 ADMIN_PASSWORD。
 */

const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawn } = require("node:child_process");

const ROOT = __dirname;
const PORT = Number(process.env.PORT || 8787);
const HOST = process.env.HOST || "127.0.0.1";

const P = {
  content: path.join(ROOT, "content.json"),
  backup: path.join(ROOT, "content.backup.json"),
  config: path.join(ROOT, "admin.config.json"),
  index: path.join(ROOT, "index.html"),
  admin: path.join(ROOT, "admin.html"),
};

// 后台文件绝不对外提供
const PRIVATE = new Set(["admin.config.json", "content.json", "content.backup.json", "server.js"]);

const SESSION_TTL = 12 * 60 * 60 * 1000; // 12 小时
const LOGIN_WINDOW = 10 * 60 * 1000;
const LOGIN_MAX = 8;
const MAX_BODY = 512 * 1024;

const sessions = new Map(); // token -> expiresAt
const attempts = new Map(); // ip -> { count, resetAt }

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".txt": "text/plain; charset=utf-8",
  ".md": "text/markdown; charset=utf-8",
  ".woff2": "font/woff2",
};

/* ---------------- 小工具 ---------------- */

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
    this.expose = true; // 可以安全地把 message 返回给前端
  }
}

const fail = (status, message) => new HttpError(status, message);

function send(res, status, body, headers = {}) {
  res.writeHead(status, {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    ...headers,
  });
  res.end(body);
}

function json(res, status, payload, headers = {}) {
  const body = JSON.stringify(payload);
  send(res, status, body, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    ...headers,
  });
}

function readBody(req, limit = MAX_BODY) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > limit) {
        reject(fail(413, "请求体过大"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function parseCookies(header = "") {
  const out = {};
  header.split(";").forEach((part) => {
    const i = part.indexOf("=");
    if (i < 0) return;
    out[part.slice(0, i).trim()] = decodeURIComponent(part.slice(i + 1).trim());
  });
  return out;
}

/* ---------------- 密码与会话 ---------------- */

function hash(password, salt) {
  return crypto.scryptSync(String(password), salt, 64).toString("hex");
}

function loadConfig() {
  let cfg;
  try {
    cfg = JSON.parse(fs.readFileSync(P.config, "utf8"));
  } catch {
    cfg = null;
  }

  if (cfg && cfg.salt && cfg.hash) {
    console.log("· 密码沿用 admin.config.json（忘记密码：删除该文件后重启，或设置 ADMIN_PASSWORD）");
    return cfg;
  }

  const password = process.env.ADMIN_PASSWORD || crypto.randomBytes(9).toString("base64url");
  const salt = crypto.randomBytes(16).toString("hex");
  cfg = { salt, hash: hash(password, salt), createdAt: new Date().toISOString() };
  fs.writeFileSync(P.config, JSON.stringify(cfg, null, 2), { mode: 0o600 });

  if (process.env.ADMIN_PASSWORD) {
    console.log("· 已用环境变量 ADMIN_PASSWORD 设置后台密码");
  } else {
    console.log("");
    console.log("  ┌─────────────────────────────────────────────┐");
    console.log("  │  后台密码（只显示这一次，请自行保存）        │");
    console.log(`  │  ${password.padEnd(41)}│`);
    console.log("  └─────────────────────────────────────────────┘");
    console.log("");
  }
  return cfg;
}

const config = loadConfig();

function verifyPassword(input) {
  if (typeof input !== "string" || !input) return false;
  if (process.env.ADMIN_PASSWORD) {
    const a = Buffer.from(input);
    const b = Buffer.from(process.env.ADMIN_PASSWORD);
    if (a.length === b.length && crypto.timingSafeEqual(a, b)) return true;
  }
  const expected = Buffer.from(config.hash, "hex");
  const actual = Buffer.from(hash(input, config.salt), "hex");
  return expected.length === actual.length && crypto.timingSafeEqual(expected, actual);
}

function newSession(res) {
  const token = crypto.randomBytes(32).toString("hex");
  sessions.set(token, Date.now() + SESSION_TTL);
  res.setHeader(
    "Set-Cookie",
    `sid=${token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${Math.floor(SESSION_TTL / 1000)}`
  );
  return token;
}

function currentSession(req) {
  const token = parseCookies(req.headers.cookie).sid;
  if (!token) return null;
  const expires = sessions.get(token);
  if (!expires) return null;
  if (expires < Date.now()) {
    sessions.delete(token);
    return null;
  }
  return token;
}

function requireAuth(req) {
  if (!currentSession(req)) throw fail(401, "未登录或登录已过期");
}

function throttle(ip) {
  const now = Date.now();
  const entry = attempts.get(ip);
  if (!entry || entry.resetAt < now) {
    attempts.set(ip, { count: 0, resetAt: now + LOGIN_WINDOW });
    return;
  }
  if (entry.count >= LOGIN_MAX) throw fail(429, "尝试次数过多，请 10 分钟后再试");
}

function recordFailure(ip) {
  const entry = attempts.get(ip) || { count: 0, resetAt: Date.now() + LOGIN_WINDOW };
  entry.count += 1;
  attempts.set(ip, entry);
}

/* ---------------- 发布到 GitHub ---------------- */

function saveConfig() {
  fs.writeFileSync(P.config, JSON.stringify(config, null, 2), { mode: 0o600 });
}

// 返回给前端的设置：token 只给「有没有」和末尾四位
function githubView() {
  const g = config.github || {};
  return {
    ownerRepo: g.ownerRepo || "",
    branch: g.branch || "main",
    indexPath: g.indexPath || "index.html",
    contentPath: g.contentPath || "content.json",
    hasToken: Boolean(g.token),
    tokenHint: g.token ? "…" + String(g.token).slice(-4) : "",
    lastPublish: g.lastPublish || null,
  };
}

function parseOwnerRepo(value) {
  const text = String(value || "")
    .trim()
    .replace(/^https?:\/\/(www\.)?github\.com\//i, "")
    .replace(/\.git$/i, "")
    .replace(/\/+$/, "");

  const match = text.match(/^([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)$/);
  if (!match) throw fail(400, "仓库要写成 owner/repo，例如 Aufde/aufdenstufen");
  return { owner: match[1], repo: match[2] };
}

function cleanPath(value, fallback) {
  const text = String(value == null ? "" : value)
    .trim()
    .replace(/^\/+/, "")
    .replace(/\\/g, "/");

  if (!text) return fallback;
  if (text.length > 200) throw fail(400, "文件路径过长");
  if (/(^|\/)\.\.(\/|$)/.test(text)) throw fail(400, "文件路径不能包含 ..");
  return text;
}

async function github(method, apiPath, body, token) {
  const res = await fetch(`https://api.github.com${apiPath}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "shijie-ershang-admin",
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(20000),
  });

  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch (err) {
    data = null;
  }
  return { ok: res.ok, status: res.status, data };
}

function githubError(result, label) {
  const status = result.status;
  const detail = (result.data && result.data.message) || `HTTP ${status}`;

  if (status === 401) return fail(502, "GitHub 拒绝：token 无效或已过期，请重新生成");
  if (status === 403) {
    return fail(
      502,
      `GitHub 拒绝写入 ${label}：权限不足。token 需要勾选该仓库的「Contents: Read and write」，或触发了 API 频率限制`
    );
  }
  if (status === 404) {
    return fail(502, `找不到仓库里的 ${label}（或 token 没有该仓库的访问权限）`);
  }
  if (status === 409) return fail(502, "GitHub 报告版本冲突，请稍后重试");
  return fail(502, `GitHub 返回 ${status}：${detail}`);
}

async function putFile({ owner, repo, branch, filePath, content, message, token }) {
  const apiPath =
    `/repos/${owner}/${repo}/contents/` +
    filePath.split("/").map(encodeURIComponent).join("/");

  const existing = await github("GET", `${apiPath}?ref=${encodeURIComponent(branch)}`, null, token);

  let sha;
  if (existing.ok) sha = existing.data && existing.data.sha;
  else if (existing.status !== 404) throw githubError(existing, filePath);

  const result = await github(
    "PUT",
    apiPath,
    {
      message,
      content: Buffer.from(content, "utf8").toString("base64"),
      branch,
      ...(sha ? { sha } : {}),
    },
    token
  );

  if (!result.ok) throw githubError(result, filePath);

  return {
    path: filePath,
    action: sha ? "更新" : "新建",
    commit: result.data.commit && result.data.commit.html_url,
  };
}

/* ---------------- 内容读写与校验 ---------------- */

const CONTENT_DEFAULT = { site: {}, hero: {}, feature: {}, articles: { items: [] }, about: {}, footer: {} };

async function readContent() {
  try {
    const raw = await fs.promises.readFile(P.content, "utf8");
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : CONTENT_DEFAULT;
  } catch {
    return CONTENT_DEFAULT;
  }
}

const LIMITED_KEYS = new Set(["body", "desc", "lede", "paragraphs", "meta"]);

function cleanString(value, key) {
  const text = value.replace(/\u0000/g, "").replace(/\r\n/g, "\n").trim();
  const limit = LIMITED_KEYS.has(key) ? 4000 : key === "title" ? 200 : 600;
  if (text.length > limit) throw fail(400, `「${key}」过长（上限 ${limit} 字）`);
  if (key === "href" && text && !/^(https?:\/\/|#|mailto:)/i.test(text)) {
    throw fail(400, "链接只能以 http://、https://、# 或 mailto: 开头");
  }
  return text;
}

function sanitize(value, key, depth) {
  if (depth > 6) throw fail(400, "数据嵌套过深");

  if (typeof value === "string") return cleanString(value, key);

  if (Array.isArray(value)) {
    if (value.length > 300) throw fail(400, "数组过长");
    return value.map((item) => sanitize(item, key, depth + 1));
  }

  if (value && typeof value === "object") {
    const out = {};
    for (const key2 of Object.keys(value)) {
      if (key2 === "__proto__" || key2 === "constructor" || key2 === "prototype") continue;
      if (!/^[A-Za-z][\w-]{0,40}$/.test(key2)) continue;
      out[key2] = sanitize(value[key2], key2, depth + 1);
    }
    return out;
  }

  if (typeof value === "number" || typeof value === "boolean" || value === null) return value;
  throw fail(400, "不支持的数据类型");
}

function validate(input) {
  const data = sanitize(input, "root", 0);

  if (!Array.isArray(data?.articles?.items)) {
    throw fail(400, "缺少 articles.items 数组");
  }

  data.articles.items = data.articles.items.filter((item) => item && typeof item === "object");
  data.articles.items.forEach((item, i) => {
    if (!item.title) throw fail(400, `第 ${i + 1} 篇文章缺少标题`);
    if (item.href && !/^(https?:\/\/|#)/i.test(item.href)) {
      throw fail(400, `第 ${i + 1} 篇文章的链接不合法`);
    }
  });

  return data;
}

async function writeContent(data) {
  const payload = JSON.stringify(data, null, 2) + "\n";
  const tmp = P.content + ".tmp";

  if (fs.existsSync(P.content)) {
    await fs.promises.copyFile(P.content, P.backup);
  }
  await fs.promises.writeFile(tmp, payload, "utf8");
  await fs.promises.rename(tmp, P.content);
}

/* ---------------- 页面渲染 ---------------- */

const CONTENT_TAG = /<script id="site-content" type="application\/json">[\s\S]*?<\/script>/;

function bake(template, data) {
  const payload = JSON.stringify(data)
    .replace(/</g, "\\u003c")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");

  if (!CONTENT_TAG.test(template)) return template; // 模板没留占位符就原样返回
  return template.replace(
    CONTENT_TAG,
    `<script id="site-content" type="application/json">${payload}</script>`
  );
}

async function renderIndex() {
  const [template, data] = await Promise.all([
    fs.promises.readFile(P.index, "utf8"),
    readContent(),
  ]);
  return bake(template, data);
}

/* ---------------- 路由 ---------------- */

async function serveStatic(req, res, pathname) {
  const rel = pathname.replace(/^\/+/, "");
  const target = path.resolve(ROOT, rel);

  if (!target.startsWith(ROOT + path.sep)) throw fail(403, "禁止访问");
  if (PRIVATE.has(path.basename(target))) throw fail(403, "禁止访问");

  let stat;
  try {
    stat = await fs.promises.stat(target);
  } catch {
    throw fail(404, "找不到文件");
  }
  if (!stat.isFile()) throw fail(404, "找不到文件");

  const type = MIME[path.extname(target).toLowerCase()] || "application/octet-stream";
  const body = await fs.promises.readFile(target);
  send(res, 200, body, {
    "Content-Type": type,
    "Cache-Control": type.startsWith("text/html") ? "no-cache" : "public, max-age=300",
  });
}

async function route(req, res) {
  const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
  const pathname = decodeURIComponent(url.pathname);
  const method = req.method || "GET";

  /* --- API --- */
  if (pathname === "/api/me" && method === "GET") {
    return json(res, 200, { authed: Boolean(currentSession(req)) });
  }

  if (pathname === "/api/login" && method === "POST") {
    const ip = req.socket.remoteAddress || "unknown";
    throttle(ip);

    let body = {};
    try {
      body = JSON.parse(await readBody(req, 4096) || "{}");
    } catch {
      throw fail(400, "请求格式错误");
    }

    if (!verifyPassword(body.password)) {
      recordFailure(ip);
      throw fail(401, "密码不正确");
    }

    attempts.delete(ip);
    newSession(res);
    return json(res, 200, { ok: true });
  }

  if (pathname === "/api/logout" && method === "POST") {
    const token = currentSession(req);
    if (token) sessions.delete(token);
    res.setHeader("Set-Cookie", "sid=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0");
    return json(res, 200, { ok: true });
  }

  if (pathname === "/api/content" && method === "GET") {
    return json(res, 200, await readContent());
  }

  if (pathname === "/api/content" && method === "PUT") {
    requireAuth(req);
    if (req.headers["x-requested-with"] !== "fetch") throw fail(400, "缺少请求头");

    let raw;
    try {
      raw = JSON.parse(await readBody(req));
    } catch (err) {
      if (err.status) throw err;
      throw fail(400, "JSON 解析失败");
    }

    const data = validate(raw);
    await writeContent(data);
    console.log(`· 已保存 content.json（${data.articles.items.length} 篇文章）`);
    return json(res, 200, { ok: true, content: data });
  }

  /* --- 发布到 GitHub --- */
  if (pathname === "/api/publish/settings" && method === "GET") {
    requireAuth(req);
    return json(res, 200, githubView());
  }

  if (pathname === "/api/publish/settings" && method === "POST") {
    requireAuth(req);
    if (req.headers["x-requested-with"] !== "fetch") throw fail(400, "缺少请求头");

    let body;
    try {
      body = JSON.parse((await readBody(req, 8192)) || "{}");
    } catch {
      throw fail(400, "请求格式错误");
    }

    const { owner, repo } = parseOwnerRepo(body.ownerRepo);

    const branch = String(body.branch || "").trim() || "main";
    if (!/^[A-Za-z0-9._/-]{1,80}$/.test(branch)) throw fail(400, "分支名不合法");

    const previous = config.github || {};
    const token = typeof body.token === "string" ? body.token.trim() : "";

    config.github = {
      ownerRepo: `${owner}/${repo}`,
      branch,
      indexPath: cleanPath(body.indexPath, "index.html"),
      contentPath: cleanPath(body.contentPath, "content.json"),
      token: token || previous.token || "",
      lastPublish: previous.lastPublish || null,
    };

    saveConfig();
    console.log(`· 已保存发布设置：${config.github.ownerRepo}@${branch}`);
    return json(res, 200, githubView());
  }

  if (pathname === "/api/publish" && method === "POST") {
    requireAuth(req);
    if (req.headers["x-requested-with"] !== "fetch") throw fail(400, "缺少请求头");

    const g = config.github || {};
    if (!g.token) throw fail(400, "还没有设置 GitHub token，先填好并保存设置");

    const { owner, repo } = parseOwnerRepo(g.ownerRepo);
    const branch = g.branch || "main";
    const token = g.token;

    const [html, data] = await Promise.all([renderIndex(), readContent()]);
    const when = new Date().toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false });
    const message = `更新站点内容 · ${when}`;

    let files;
    try {
      files = [
        await putFile({
          owner, repo, branch, token, message,
          filePath: g.indexPath || "index.html",
          content: html,
        }),
        await putFile({
          owner, repo, branch, token, message,
          filePath: g.contentPath || "content.json",
          content: JSON.stringify(data, null, 2) + "\n",
        }),
      ];
    } catch (err) {
      if (err.status) throw err;
      throw fail(502, "连接 GitHub 失败：" + err.message);
    }

    g.lastPublish = { at: new Date().toISOString(), commit: files[0].commit };
    saveConfig();

    console.log(`· 已发布到 GitHub：${owner}/${repo}@${branch}`);
    return json(res, 200, { ok: true, files, settings: githubView() });
  }

  if (pathname === "/api/export" && method === "GET") {
    requireAuth(req);
    const html = await renderIndex();
    return send(res, 200, html, {
      "Content-Type": "text/html; charset=utf-8",
      "Content-Disposition": 'attachment; filename="index.html"',
      "Cache-Control": "no-store",
    });
  }

  /* --- 页面 --- */
  if (pathname === "/" || pathname === "/index.html") {
    const html = await renderIndex();
    return send(res, 200, html, {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-cache",
    });
  }

  if (pathname === "/admin" || pathname === "/admin/") {
    const html = await fs.promises.readFile(P.admin, "utf8");
    return send(res, 200, html, {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
    });
  }

  if (method !== "GET" && method !== "HEAD") throw fail(405, "方法不允许");

  return serveStatic(req, res, pathname);
}

const server = http.createServer((req, res) => {
  route(req, res).catch((err) => {
    const exposed = Boolean(err.expose);
    const status = exposed ? err.status || 500 : 500;
    if (!exposed) console.error(err);
    if (res.headersSent) return res.end();
    json(res, status, { ok: false, error: exposed ? err.message : "服务器错误" });
  });
});

server.on("error", (err) => {
  if (err.code === "EADDRINUSE") {
    console.error("");
    console.error(`  端口 ${PORT} 已被占用。`);
    console.error("  · 可能后台已经在运行了：直接打开下面的地址试试");
    console.error(`    http://127.0.0.1:${PORT}/admin`);
    console.error("  · 或者换个端口：先执行  set PORT=9000  再启动");
    console.error("");
    process.exit(1);
  }
  throw err;
});

server.listen(PORT, HOST, () => {
  const local = `http://${HOST === "0.0.0.0" ? "127.0.0.1" : HOST}:${PORT}`;

  console.log("");
  console.log("  拾级而上 · 本地站点");
  console.log(`  站点  ${local}/`);
  console.log(`  后台  ${local}/admin`);
  console.log("  Ctrl+C / 关闭窗口 停止");
  console.log("");

  openBrowser(`${local}/admin`);
});

// 启动后自动打开后台（不想自动打开：设置环境变量 OPEN_ADMIN=0）
function openBrowser(url) {
  if (process.env.OPEN_ADMIN === "0") return;

  const command =
    process.platform === "win32" ? "cmd" : process.platform === "darwin" ? "open" : "xdg-open";
  const args = process.platform === "win32" ? ["/c", "start", "", url] : [url];

  try {
    const child = spawn(command, args, { detached: true, stdio: "ignore" });
    child.on("error", () => {});
    child.unref();
  } catch (err) {
    // 打不开浏览器不影响服务本身
  }
}

process.on("SIGINT", () => {
  console.log("\n· 已停止");
  server.close(() => process.exit(0));
});
