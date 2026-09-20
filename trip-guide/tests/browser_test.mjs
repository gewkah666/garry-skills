#!/usr/bin/env node
/**
 * browser_test.mjs - 用无头 Chrome 走一遍同行者的真实操作路径
 *
 * 只用 node 内置能力（fetch + WebSocket）直连 CDP，不装任何依赖。
 * 前置：notion-relay 的 notion_relay.py + devserve.py 已经起来（见 SKILL.md「同行协作」）。
 *
 *   node tests/browser_test.mjs "http://127.0.0.1:8099/s/chuanxi/?t=<token>"
 *
 * 覆盖：认领下拉出现 → 认领身份 → 清单从 Notion 来 → 勾选落库 → 加条目 → 删条目
 *       → 填偏好 → 同行一览更新 → 换人 → 游客模式 → 无 token 时退回本机勾选
 */
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const URL_ = process.argv[2];
if (!URL_) { console.error('用法: browser_test.mjs <url>'); process.exit(2); }

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const PORT = 9333;
const profile = mkdtempSync(join(tmpdir(), 'trip-cdp-'));

const chrome = spawn(CHROME, [
  '--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
  '--no-first-run', '--no-default-browser-check', '--disable-gpu', 'about:blank',
], { stdio: 'ignore' });

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function target() {
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const pg = list.find(t => t.type === 'page');
      if (pg) return pg.webSocketDebuggerUrl;
    } catch {}
    await sleep(250);
  }
  throw new Error('Chrome 没起来');
}

let ws, id = 0;
const waiting = new Map();
function send(method, params = {}) {
  const i = ++id;
  ws.send(JSON.stringify({ id: i, method, params }));
  return new Promise((res, rej) => waiting.set(i, { res, rej }));
}
async function evalJs(expr) {
  const r = await send('Runtime.evaluate', {
    expression: `(async () => { ${expr} })()`, awaitPromise: true, returnByValue: true,
  });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || 'JS 抛错');
  return r.result?.value;
}
// 等某个条件为真，超时就报错 —— 不用死等固定时间
async function until(expr, what, ms = 40000) {
  const t0 = Date.now();
  let last = '(没取到)';
  while (Date.now() - t0 < ms) {
    // 导航途中执行上下文会被销毁，evaluate 直接抛 —— 那只说明还在切页，继续等
    try { if (await evalJs(`return !!(${expr});`)) return true; } catch {}
    await sleep(250);
  }
  try {
    last = await evalJs(`return JSON.stringify({url:location.href.slice(0,80), ready:document.readyState, prep:!!document.getElementById('prep'), items:document.querySelectorAll('#prep-me input[data-item]').length, html:document.body.innerHTML.length});`);
  } catch (e) { last = '(取状态也失败: ' + e.message + ')'; }
  throw new Error(`等不到: ${what}\n     当时页面状态: ${last}`);
}

let pass = 0, fail = 0;
const ok = (c, m) => { c ? (pass++, console.log(`  ✓ ${m}`)) : (fail++, console.log(`  ✗ ${m}`)); };

async function main() {
  const wsUrl = await target();
  ws = new WebSocket(wsUrl);
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && waiting.has(m.id)) {
      const { res, rej } = waiting.get(m.id); waiting.delete(m.id);
      m.error ? rej(new Error(m.error.message)) : res(m.result);
    }
  };
  await new Promise(r => ws.onopen = r);
  await send('Page.enable'); await send('Runtime.enable');

  // 导航前打个标记，等它消失才算换到新文档。不这么做，下面的 until() 会命中
  // 旧页面残留的 DOM 直接返回真 —— 本机导航快看不出来，打到公网就必现。
  const goto = async u => {
    try { await evalJs(`window.__nav = 1; return 1;`); } catch {}
    await send('Page.navigate', { url: u });
    const t0 = Date.now();
    while (Date.now() - t0 < 20000) {
      try { if (!(await evalJs(`return typeof window.__nav !== 'undefined';`))) break; } catch {}
      await sleep(150);
    }
    await until(`document.readyState === 'complete' && document.getElementById('prep')`, '页面渲染');
  };

  console.log('\n【1】认领：分享链接打开，应出现「你是哪位？」');
  await goto(URL_);
  await evalJs(`Object.keys(localStorage).filter(k=>k.endsWith(':me')).forEach(k=>localStorage.removeItem(k)); return 1;`);
  await goto(URL_);
  await until(`document.querySelector('#prep-me .who')`, '认领卡');
  ok(await evalJs(`return /你是哪位/.test(document.querySelector('#prep-me .who').textContent);`), '出现认领提示');
  const names = await evalJs(`return [...document.querySelectorAll('#prep-me [data-claim]')].map(b=>b.textContent);`);
  ok(names.includes('御主'), `下拉里有名单成员：${names.join(' / ')}`);
  ok(names.some(n => /游客/.test(n)), '有「我是游客（只看）」');

  console.log('\n【2】认领身份 → 清单应从 Notion 来');
  await evalJs(`document.querySelector('#prep-me [data-claim]:not(.guest)').click(); return 1;`);
  await until(`document.querySelector('#prep-me .me-bar')`, '身份条');
  ok(await evalJs(`return /御主/.test(document.querySelector('.me-bar').textContent);`), '身份条显示当前身份');
  const n0 = await evalJs(`return document.querySelectorAll('#prep-me input[data-item]').length;`);
  ok(n0 >= 15, `清单来自 Notion，共 ${n0} 条`);
  ok(await evalJs(`return !!document.querySelector('#prep-me .list small');`), '「为什么带」的小字保留了');

  console.log('\n【3】勾选 → 落到 Notion');
  const firstId = await evalJs(`return document.querySelector('#prep-me input[data-item]').dataset.item;`);
  await evalJs(`const b=document.querySelector('#prep-me input[data-item]'); b.checked=true; b.dispatchEvent(new Event('change',{bubbles:true})); return 1;`);
  await until(`!document.getElementById('sync')?.textContent`, '同步完成');
  ok(await evalJs(`return document.querySelector('#prep-me .list label').classList.contains('done');`), '界面立刻划掉（乐观更新）');
  await goto(URL_);
  await until(`document.querySelector('#prep-me input[data-item]')`, '重载后的清单');
  ok(await evalJs(`return document.querySelector('input[data-item="${firstId}"]').checked;`), '刷新后仍是勾上的 → 真落库了');

  console.log('\n【4】加一条自己的 → 删掉');
  await evalJs(`const i=document.getElementById('newitem'); i.value='浏览器测试临时条目'; document.querySelector('[data-add]').click(); return 1;`);
  await until(`[...document.querySelectorAll('#prep-me .list span')].some(s=>/浏览器测试临时条目/.test(s.textContent))`, '新条目出现');
  ok(true, '加条目成功');
  const nAdd = await evalJs(`return document.querySelectorAll('#prep-me input[data-item]').length;`);
  ok(nAdd === n0 + 1, `条数 ${n0} → ${nAdd}`);
  await evalJs(`const lab=[...document.querySelectorAll('#prep-me .list label')].find(l=>/浏览器测试临时条目/.test(l.textContent)); lab.querySelector('[data-del]').click(); return 1;`);
  await until(`![...document.querySelectorAll('#prep-me .list span')].some(s=>/浏览器测试临时条目/.test(s.textContent))`, '条目消失');
  ok(true, '删条目成功');

  console.log('\n【5】偏好 → 同行一览');
  await evalJs(`const i=document.querySelector('[data-pref="饮食忌口"]'); i.value='浏览器测试·不吃香菜'; i.dispatchEvent(new Event('change',{bubbles:true})); return 1;`);
  await until(`/不吃香菜/.test(document.getElementById('prep-mates').textContent)`, '同行一览刷新');
  ok(true, '偏好写入并回显到同行一览');

  console.log('\n【6】换人 / 游客模式');
  await evalJs(`document.querySelector('.me-bar .swap').click(); return 1;`);
  await until(`document.querySelector('#prep-me .who')`, '回到认领卡');
  ok(true, '「换人」回到认领');
  await evalJs(`document.querySelector('#prep-me [data-claim="guest"]').click(); return 1;`);
  await until(`/游客模式/.test(document.getElementById('prep-me').textContent)`, '游客模式');
  ok(await evalJs(`return document.querySelectorAll('#prep-me input[data-k]').length > 0;`), '游客看到的是本机静态清单');

  console.log('\n【7】没有 token');
  const bare = URL_.split('?')[0];
  const st = await evalJs(`const r = await fetch(${JSON.stringify(bare)}, { redirect: 'manual' }); return r.status;`);
  if (st === 403) {
    // 线上：nginx 校验 token↔slug，不带 token 页面根本打不开。这本身就是一条安全断言。
    ok(true, '线上无 token → nginx 403，页面打不开');
    ok(await evalJs(`const r = await fetch(${JSON.stringify(bare)}.replace('/s/','/s/api/trip/')+'/roster'); return r.status === 403;`),
       '无 token 时 API 同样 403');
  } else {
    // devserve（不校验 token）：验证协作 UI 完全不出现，退回本机勾选 —— 这正是
    // dashboards 那份（URL 上没有 ?t=）的行为。
    await goto(bare);
    ok(await evalJs(`return document.querySelectorAll('#prep input[data-k]').length > 0 && !document.querySelector('#prep-me .who') && !document.querySelector('.me-bar');`),
       '无 token 时不出现任何协作 UI，静态清单照常');
    ok(await evalJs(`return /保存在本机/.test(document.querySelector('#prep .ch-t').textContent);`), '标题小字也跟着退回');
  }

  console.log(`\n${fail ? '✗' : '✓'} ${pass} 通过 / ${fail} 失败`);
  return fail;
}

let code = 1;
try { code = await main(); }
catch (e) { console.error('\n✗ ' + e.message); code = 1; }
finally { chrome.kill(); try { rmSync(profile, { recursive: true, force: true }); } catch {} }
process.exit(code ? 1 : 0);
