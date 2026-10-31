/**
 * 用 headless Edge 给看板截图。
 *
 * 为什么用它而不是自己用 PIL 画图：主人要的是「跟 webui 一模一样」的效果，
 * 直接截真实前端就不用维护两套绘图代码，也不会出现两边样式慢慢跑偏喵。
 */

const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const os = require("node:os");

/** Edge 可执行文件路径，按常见安装位置逐个试喵。 */
const EDGE_CANDIDATES = [
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
];

/** 找一个可用的浏览器可执行文件喵。 */
function findBrowser() {
  for (const candidate of EDGE_CANDIDATES) {
    if (fs.existsSync(candidate)) return candidate;
  }
  throw new Error("找不到 Edge 或 Chrome");
}

/** 最小 CDP 客户端：只用 WebSocket 收发 JSON 喵。 */
class Cdp {
  constructor(url) {
    this.url = url;
    this.nextId = 1;
    this.pending = new Map();
  }

  /** 建立连接并挂上消息分发喵。 */
  connect() {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.url);
      this.ws = ws;
      ws.addEventListener("open", () => resolve());
      ws.addEventListener("error", (event) => reject(new Error(`WebSocket 出错：${event.message || "unknown"}`)));
      ws.addEventListener("message", (event) => {
        const message = JSON.parse(event.data);
        const waiter = this.pending.get(message.id);
        if (!waiter) return;
        this.pending.delete(message.id);
        if (message.error) waiter.reject(new Error(message.error.message));
        else waiter.resolve(message.result);
      });
    });
  }

  /** 发一条命令并等结果喵。 */
  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  /** 关掉连接喵。 */
  close() {
    if (this.ws) this.ws.close();
  }
}

/** 等一个 HTTP 端口能连上，最多等 timeoutMs 喵。 */
function waitForPort(port, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const attempt = () => {
      const request = http.get({ host: "127.0.0.1", port, path: "/json/version" }, (response) => {
        response.resume();
        resolve();
      });
      request.on("error", () => {
        if (Date.now() > deadline) reject(new Error("调试端口一直没起来"));
        else setTimeout(attempt, 100);
      });
    };
    attempt();
  });
}

/** 拉一次调试端点，拿到可用的 target 列表喵。 */
function fetchJson(port, path) {
  return new Promise((resolve, reject) => {
    http
      .get({ host: "127.0.0.1", port, path }, (response) => {
        let body = "";
        response.on("data", (chunk) => (body += chunk));
        response.on("end", () => {
          try {
            resolve(JSON.parse(body));
          } catch (error) {
            reject(error);
          }
        });
      })
      .on("error", reject);
  });
}

/** 睡一会儿喵。 */
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** 等页面 document readyState 变成 complete，最多等 timeoutMs 喵。 */
async function waitForReady(cdp, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const probe = await cdp.send("Runtime.evaluate", {
      expression: "document.readyState",
      returnByValue: true,
    });
    if (probe.result && probe.result.value === "complete") return;
    await sleep(100);
  }
  throw new Error("页面一直没加载完");
}

/**
 * 截图主流程。
 *
 * 参数通过环境变量传，避免命令行转义问题喵。
 */
async function main() {
  const baseUrl = process.env.SHOT_URL;
  const outPath = process.env.SHOT_OUT;
  const token = process.env.SHOT_TOKEN || "";
  const width = Number(process.env.SHOT_WIDTH || 1100);
  const height = Number(process.env.SHOT_HEIGHT || 900);
  const waitMs = Number(process.env.SHOT_WAIT || 2500);
  const selector = process.env.SHOT_SELECTOR || "";
  // 默认只截内容区，不带顶部的功能栏喵
  const defaultClip = process.env.SHOT_CLIP || "main.page";
  // 页签：没显式指定时沿用 URL 里已有的 hash，别再拿 overview 把它盖掉喵
  const hash = process.env.SHOT_HASH || "";
  // 可选：截图前把鼠标移到这个选择器上，用来验证悬浮提示喵
  const hoverSelector = process.env.SHOT_HOVER || "";

  if (!baseUrl || !outPath) throw new Error("SHOT_URL 与 SHOT_OUT 必须都给");

  const browserPath = findBrowser();
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), "dsh-shot-"));
  const port = 9200 + Math.floor(Math.random() * 400);

  const child = spawn(
    browserPath,
    [
      "--headless=new",
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${userDataDir}`,
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-gpu",
      "--hide-scrollbars",
      "--force-device-scale-factor=2",
      `--window-size=${width},${height}`,
      "about:blank",
    ],
    { stdio: "ignore" },
  );

  let cdp;
  try {
    await waitForPort(port, 20000);
    const version = await fetchJson(port, "/json/version");
    // 新版本 Edge 用 /json/list 拿页面 target 喵
    const targets = await fetchJson(port, "/json/list");
    const page = targets.find((item) => item.type === "page");
    if (!page) throw new Error("没有可用的页面 target");
    cdp = new Cdp(page.webSocketDebuggerUrl);
    await cdp.connect();

    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width,
      height,
      deviceScaleFactor: 2,
      mobile: false,
    });

    // 先访问同源的空页，才能写 localStorage 喵
    const target = new URL(baseUrl);
    if (hash) target.hash = hash.replace(/^#?/, "#");
    // 喵~注意：查询串必须保留，截图参数（窗口、范围、日期）全靠它传给前端喵
    await cdp.send("Page.navigate", { url: target.toString() });
    // 喵~注意：必须等页面真正加载完，否则 evaluate 还跑在上一个上下文（about:blank）里，
    // 写进去的 token 落在不透明源上，看板读不到就会一直弹口令框喵
    await waitForReady(cdp, 15000);
    if (token) {
      const writeResult = await cdp.send("Runtime.evaluate", {
        expression: `localStorage.setItem("devicehub.token", ${JSON.stringify(token)}); localStorage.getItem("devicehub.token");`,
        returnByValue: true,
      });
      const written = writeResult.result && writeResult.result.value;
      if (written !== token) throw new Error(`token 写入失败，读回的是 ${JSON.stringify(written)}`);
      // 喵~注意：这里必须用 reload 而不是再 navigate 一次——目标地址（含 hash）已经就位，
      // 再导航同一个 URL 会被当成同文档跳转而不重新加载，前端仍用内存里的空口令喵
      await cdp.send("Page.reload", { ignoreCache: true });
      await waitForReady(cdp, 15000);
    }
    await sleep(waitMs);

    // 喵~注意：固定等一会儿有时不够（刚重启时首个请求要建连接池），
    // 这里再等口令遮罩消失，最多多等 6 秒，等不到就交给下面的自检报错喵
    {
      const guardDeadline = Date.now() + 6000;
      while (Date.now() < guardDeadline) {
        const probe = await cdp.send("Runtime.evaluate", {
          expression: `(() => {
            const text = document.body ? document.body.innerText : "";
            return !(text.includes("填入口令") || text.includes("口令无效"));
          })()`,
          returnByValue: true,
        });
        if (probe.result && probe.result.value) break;
        await sleep(250);
      }
    }

    // 等指定元素出现，超时不算失败喵
    if (selector) {
      const deadline = Date.now() + 8000;
      while (Date.now() < deadline) {
        const probe = await cdp.send("Runtime.evaluate", {
          expression: `!!document.querySelector(${JSON.stringify(selector)})`,
          returnByValue: true,
        });
        if (probe.result && probe.result.value) break;
        await sleep(200);
      }
    }

    // 喵~注意：要验证悬浮提示时得先真的把鼠标移上去，浮层只认 pointermove 喵
    if (hoverSelector) {
      const point = await cdp.send("Runtime.evaluate", {
        expression: `(() => {
          const node = document.querySelector(${JSON.stringify(hoverSelector)});
          if (!node) return null;
          const rect = node.getBoundingClientRect();
          if (rect.width <= 0 || rect.height <= 0) return null;
          // 取色块中心，保证指针真的落在元素上喵
          return { x: rect.x + rect.width / 2, y: rect.y + rect.height / 2 };
        })()`,
        returnByValue: true,
      });
      const spot = point.result && point.result.value;
      if (spot) {
        // 先移进去再微调一格，触发 pointermove 喵
        await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: spot.x, y: spot.y, buttons: 0 });
        await sleep(120);
        await cdp.send("Input.dispatchMouseEvent", { type: "mouseMoved", x: spot.x + 1, y: spot.y, buttons: 0 });
        await sleep(400);
      }
    }

    // 喵~防御：口令没生效时页面会弹「填入口令 / 口令无效」的遮罩，
    // 这时候拍下来的是一张灰底弹窗图，看着像成功其实全是错的，必须直接判失败喵
    const guard = await cdp.send("Runtime.evaluate", {
      expression: `(() => {
        const text = document.body ? document.body.innerText : "";
        if (text.includes("填入口令")) return "填入口令";
        if (text.includes("口令无效")) return "口令无效";
        return "";
      })()`,
      returnByValue: true,
    });
    const blocked = guard.result && guard.result.value;
    if (blocked) throw new Error(`口令没有生效，页面停在「${blocked}」遮罩上`);

    // 要截某个元素时用它的完整文档包围盒裁剪喵
    let clip;
    const clipSelector = selector || defaultClip;
    if (clipSelector) {
      const box = await cdp.send("Runtime.evaluate", {
        expression: `(() => {
          const node = document.querySelector(${JSON.stringify(clipSelector)});
          if (!node) return null;
          const rect = node.getBoundingClientRect();
          // 喵~注意：加上滚动偏移才是文档坐标，否则页面滚过之后会裁错位置喵
          return { x: rect.x + window.scrollX, y: rect.y + window.scrollY, width: rect.width, height: rect.height };
        })()`,
        returnByValue: true,
      });
      const value = box.result && box.result.value;
      if (value && value.width > 0 && value.height > 0) {
        // 喵~注意：视口比内容矮时，视口外的部分不会被绘制，截出来会是一片空白；
        // 先把视口撑到内容高度，重新布局后再截，长列表才完整喵
        if (value.height + value.y > height) {
          await cdp.send("Emulation.setDeviceMetricsOverride", {
            width,
            height: Math.ceil(value.height + value.y + 40),
            deviceScaleFactor: 2,
            mobile: false,
          });
          await sleep(600);
          // 撑开视口后位置可能微调，重新量一次包围盒喵
          const again = await cdp.send("Runtime.evaluate", {
            expression: `(() => {
              const node = document.querySelector(${JSON.stringify(clipSelector)});
              if (!node) return null;
              const rect = node.getBoundingClientRect();
              return { x: rect.x + window.scrollX, y: rect.y + window.scrollY, width: rect.width, height: rect.height };
            })()`,
            returnByValue: true,
          });
          const remeasured = again.result && again.result.value;
          if (remeasured && remeasured.width > 0 && remeasured.height > 0) {
            clip = { x: remeasured.x, y: remeasured.y, width: remeasured.width, height: remeasured.height, scale: 2 };
          }
        }
        if (!clip) {
          clip = { x: value.x, y: value.y, width: value.width, height: value.height, scale: 2 };
        }
      }
    }

    const shot = await cdp.send("Page.captureScreenshot", {
      format: "png",
      ...(clip ? { clip } : { captureBeyondViewport: true }),
    });
    fs.writeFileSync(outPath, Buffer.from(shot.data, "base64"));
    process.stdout.write(`OK ${outPath}`);
  } finally {
    if (cdp) cdp.close();
    child.kill();
    // 清理临时用户目录喵
    try {
      fs.rmSync(userDataDir, { recursive: true, force: true });
    } catch {
      // 清不掉就算了，系统临时目录会自己回收喵
    }
  }
}

main().catch((error) => {
  process.stderr.write(`FAILED ${error.message}`);
  process.exit(1);
});
