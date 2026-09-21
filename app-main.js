
(function(){
'use strict';

// ── 主题切换 ──
var THEMES = ['dark','blue','green','purple'];
var THEME_LABELS = {'dark':'🌙 暗色','blue':'💧 清新蓝','green':'🌿 自然绿','purple':'💜 薄雾紫'};
function applyTheme(name) {
  document.documentElement.setAttribute('data-theme', name);
  localStorage.setItem('cs2_theme', name);
}
function cycleTheme() {
  var cur = document.documentElement.getAttribute('data-theme') || 'dark';
  var idx = THEMES.indexOf(cur);
  var next = THEMES[(idx + 1) % THEMES.length];
  applyTheme(next);
  showThemeToast(next);
}
function showThemeToast(name) {
  var t = document.getElementById('themeToast');
  if (!t) { t = document.createElement('div'); t.id='themeToast'; t.style.cssText='position:fixed;bottom:20px;left:50%;transform:translateX(-50%);background:var(--surface);color:var(--text);padding:8px 20px;border-radius:20px;font-size:12px;z-index:9999;border:1px solid var(--border);box-shadow:var(--shadow),inset 0 1px 0 rgba(255,255,255,.045);pointer-events:none;transition:opacity .3s'; document.body.appendChild(t); }
  t.textContent = THEME_LABELS[name] || name;
  t.style.opacity = '1';
  clearTimeout(t._tid);
  t._tid = setTimeout(function(){ t.style.opacity = '0'; }, 1500);
}
window.cycleTheme = cycleTheme;
window.applyTheme = applyTheme;
// 点击空白关闭主题菜单
document.addEventListener('click', function(e) {
  var p = document.getElementById('themePicker');
  if (p && !p.contains(e.target)) p.classList.remove('open');
});
// 初始化主题
(function(){
  var saved = localStorage.getItem('cs2_theme');
  applyTheme(saved && THEMES.indexOf(saved) >= 0 ? saved : 'dark');
})();

// ═══════════════ 骨架屏 ═══════════════
function showSkeleton() {
  var skel = document.createElement('div');
  skel.id = 'skeletonWrap';
  skel.style.cssText = 'position:fixed;inset:0;z-index:100;background:var(--bg);display:flex;flex-direction:column;align-items:center;overflow-y:auto';
  // 顶部进度条
  skel.innerHTML = '<div id="skProgress" style="position:fixed;top:0;left:0;height:3px;background:linear-gradient(90deg,var(--blue),#c084fc,var(--rise));width:0%;transition:width .6s ease;z-index:101;border-radius:0 2px 2px 0"></div>' +
    '<div style="width:100%;max-width:1280px;padding:56px 24px 40px;margin:0 auto">' +
      // 标题区
      '<div class="sk-box" style="width:50%;height:22px;margin-bottom:8px"></div>' +
      '<div class="sk-box" style="width:30%;height:13px;margin-bottom:36px;opacity:.6"></div>' +
      // 五列 KPI
      '<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:32px">' +
        Array(5).fill('<div class="sk-box" style="height:70px;border-radius:12px"></div>').join('') +
      '</div>' +
      // 两列布局
      '<div style="display:grid;grid-template-columns:1.2fr 1fr;gap:16px;margin-bottom:20px">' +
        '<div class="sk-box" style="height:200px;border-radius:14px"></div>' +
        '<div class="sk-box" style="height:200px;border-radius:14px"></div>' +
      '</div>' +
      // 卡片行
      '<div class="sk-box" style="width:35%;height:14px;margin-bottom:14px"></div>' +
      '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;margin-bottom:28px">' +
        Array(6).fill('<div class="sk-box" style="height:110px;border-radius:12px"></div>').join('') +
      '</div>' +
      // 列表区
      '<div class="sk-box" style="width:30%;height:14px;margin-bottom:14px"></div>' +
      '<div class="sk-box" style="height:260px;border-radius:14px;margin-bottom:20px"></div>' +
      '<div class="sk-box" style="width:25%;height:14px;margin-bottom:14px"></div>' +
      '<div class="sk-box" style="height:260px;border-radius:14px"></div>' +
    '</div>';
  var st = document.createElement('style');
  st.textContent = '.sk-box{background:linear-gradient(110deg,var(--surface) 30%,rgba(255,255,255,.03) 50%,var(--surface) 70%);background-size:200% 100%;animation:skShimmer 1.8s infinite ease-in-out;border-radius:8px}.sk-box:nth-child(odd){animation-delay:.2s}.sk-box:nth-child(3n){animation-delay:.4s}@keyframes skShimmer{0%{background-position:200% 0}100%{background-position:-200% 0}}';
  document.head.appendChild(st);
  document.body.appendChild(skel);
  // 渐进进度条
  window._skProgress = 0;
  setTimeout(function() { updateProgress(15); }, 100);
  setTimeout(function() { updateProgress(40); }, 400);
  setTimeout(function() { updateProgress(70); }, 900);
}
function updateProgress(pct) {
  var bar = document.getElementById('skProgress');
  if (bar && pct > (window._skProgress || 0)) {
    window._skProgress = pct;
    bar.style.width = pct + '%';
  }
}
showSkeleton();

function hideSkeleton() {
  updateProgress(100);
  var el = document.getElementById('skeletonWrap');
  var bar = document.getElementById('skProgress');
  if (el) {
    el.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
    el.style.opacity = '0';
    el.style.transform = 'translateY(-8px)';
    setTimeout(function() {
      if (el && el.parentNode) el.remove();
      if (bar && bar.parentNode) bar.remove();
    }, 400);
  }
  document.body.classList.remove('body-fadein');
}

// ═══════════════ CONSTANTS — 唯一真相源 ═══════════════
// 磨损等级：中文 → 英文缩写 → 中文显示名
// 与 holdings.json 的 wear 字段对齐（后端已修正：略有磨损=MW, 久经沙场=FT）
const WEAR_MAP = {
  'FN': '崭新出厂',
  'MW': '略有磨损',
  'FT': '久经沙场',
  'WW': '战地风云',
  'BS': '战痕累累'
};

// 从 holdings.json category 中文 → 前端分类 key
const CAT_MAP = {
  '步枪':   'weapon',
  '手枪':   'weapon',
  '冲锋枪': 'weapon',
  '手套':   'gloves',
  '匕首':   'knives',
  '印花':   'sticker',
  '音乐盒': 'music',
  '其他':   'other'
};

// 前端分类 key → 中文显示名
const CAT_LABELS = {
  'weapon':  '武器',
  'gloves':  '手套',
  'knives':  '匕首',
  'sticker': '印花',
  'music':   '音乐',
  'other':   '其他'
};

// ═══════════════ DOM CACHE ═══════════════
const $ = id => document.getElementById(id);
const esc = s => { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; };
const DOM = {
  countBadge:$('countBadge'), tbody:$('tbody'), pager:$('pager'),
  tabBar:$('tabBar'), recGrid:$('recGrid'), recUpdateTime:$('recUpdateTime'),
  syncStatus:$('syncStatus'), updateTime:$('updateTime'),
  newsSection:$('newsSection'), newsGrid:$('newsGrid'), newsUpdateTime:$('newsUpdateTime'),
  tokenModal:$('tokenModal'), tokenInput:$('tokenInput'), tokenStatus:$('tokenStatus'),
  searchInput:$('searchInput'), sortOrder:$('sortOrder'),
  pageJump:$('pageJump'), pageNumInput:$('pageNumInput'), pageGoBtn:$('pageGoBtn')
};

// ═══════════════ STATE ═══════════════
let H = [];                // holdings items (flattened)
let costOverrides = {};    // { "饰品名|FN": cost_float }
let marketData = null;     // raw market.json
let recData = {};          // marketData.recommendations
let curCat = 'all';
let curPage = 1;
let recPage = 1;
let _recAllItems = [];
let sortCol = 'pnlPct';
let sortDir = 'desc';
var fmtDate = v => v;


let filteredCache = null;
let filterCacheKey = '';
let searchQuery = '';

const PAGE_SIZE = 30;
const REC_PAGE_SIZE = 6;
const LS_KEY = 'cs2_cost_overrides';
const LS_TOKEN_KEY = 'cs2_gh_token';
const LS_STARRED = 'cs2_steam_starrings';
const GH_REPO = 'hintime/cs2-dashboard';
const GH_API = 'https://api.github.com/repos/' + GH_REPO + '/contents/cost-overrides.json';

let ghToken = localStorage.getItem(LS_TOKEN_KEY) || '';
let syncTimer = null;
let starred = JSON.parse(localStorage.getItem(LS_STARRED) || '{}');

// ═══════════════ UPDATE DATA (trigger GitHub Actions workflow) ═══════════════
let updateTimer = null;
const WORKFLOW_ID = 'update-cs2-data.yml';
const WORKFLOW_API = 'https://api.github.com/repos/' + GH_REPO + '/actions/workflows/' + WORKFLOW_ID + '/dispatches';
const RUNS_API = 'https://api.github.com/repos/' + GH_REPO + '/actions/runs?workflow_id=' + WORKFLOW_ID + '&per_page=1';

async function pollWorkflowComplete() {
  const MAX_WAIT = 180000; // 3 min
  const INTERVAL = 15000;   // 15s
  const start = Date.now();
  while (Date.now() - start < MAX_WAIT) {
    await sleep(INTERVAL);
    try {
      const r = await fetch(RUNS_API, {
        headers: { 'Authorization': 'token ' + ghToken, 'Accept': 'application/vnd.github.v3+json' }
      });
      if (r.ok) {
        const data = await r.json();
        const latestRun = data.workflow_runs && data.workflow_runs[0];
        if (latestRun && (latestRun.status === 'completed')) {
          return; // Done
        }
        // If still in progress, keep polling
      }
    } catch(e) {}
  }
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// Toast notification
let toastEl = null;
function showToast(msg, duration) {
  if (!toastEl) {
    toastEl = document.createElement('div');
    toastEl.style.cssText = 'position:fixed;bottom:28px;left:50%;transform:translateX(-50%) translateY(8px);background:rgba(22,27,34,.97);border:1px solid rgba(96,165,250,.4);border-radius:10px;padding:10px 20px;font-size:13px;color:#d1d5db;z-index:9999;backdrop-filter:blur(12px);transition:opacity .3s,transform .3s;pointer-events:none;white-space:nowrap;box-shadow:0 8px 32px rgba(0,0,0,.3)';
    document.body.appendChild(toastEl);
  }
  toastEl.textContent = msg;
  toastEl.style.opacity = '1'; toastEl.style.transform = 'translateX(-50%) translateY(0)';
  clearTimeout(toastEl._timer);
  toastEl._timer = setTimeout(() => { toastEl.style.opacity = '0'; toastEl.style.transform = 'translateX(-50%) translateY(8px)'; }, duration);
}

// ═══════════════ HELPERS ═══════════════
function wearCN(code) { return WEAR_MAP[code] || code || '--'; }

// 翻译饰品名：中文名映射 + 磨损中文
function cnName(name) {
  if (!name) return name;
  var nm = window._cnNameMap || {};
  var cn = nm[name] || name;
  // 替换磨损
  cn = cn.replace(/\(Factory New\)/g,'(崭新出厂)')
    .replace(/\(Minimal Wear\)/g,'(略有磨损)')
    .replace(/\(Field-Tested\)/g,'(久经沙场)')
    .replace(/\(Well-Worn\)/g,'(战地风云)')
    .replace(/\(Battle-Scarred\)/g,'(战痕累累)');
  return cn;
}

function overrideKey(name, wear) {
  // Stable key: name|WEAR_CODE (e.g. "AK-47 红线|FT")
  // Empty/other wear uses empty string
  return name + '|' + (wear || '');
}

function isBS(item) {
  // Unified BS filter: check both wear code and name
  return item.w === 'BS' || item.n.includes('战痕累累');
}

// ═══════════════ OVERRIDES PERSISTENCE ═══════════════
function saveOverrides() {
  localStorage.setItem(LS_KEY, JSON.stringify(costOverrides));
  if (ghToken) scheduleSync();
}

function scheduleSync() {
  clearTimeout(syncTimer);
  syncTimer = setTimeout(syncToGitHub, 2000);
}

async function syncToGitHub() {
  if (!ghToken) return;
  const payload = JSON.stringify(costOverrides, null, 2);
  // 防抖：仅在内容实际变化时同步
  if (syncToGitHub._lastPayload === payload) return;
  syncToGitHub._lastPayload = payload;
  const el = DOM.syncStatus;
  el.textContent = '⏳ 同步中...';
  el.className = 'sync-status show';
  try {
    const getR = await fetch(GH_API, {
      headers: {'Authorization':'token '+ghToken, 'Accept':'application/vnd.github.v3+json'}
    });
    let sha = null;
    if (getR.ok) { sha = (await getR.json()).sha; }
    const body = {
      message: 'auto: update cost overrides',
      content: btoa(unescape(encodeURIComponent(JSON.stringify(costOverrides,null,2)))),
      branch: 'main'
    };
    if (sha) body.sha = sha;
    const putR = await fetch(GH_API, {
      method: 'PUT',
      headers: {'Authorization':'token '+ghToken, 'Accept':'application/vnd.github.v3+json', 'Content-Type':'application/json'},
      body: JSON.stringify(body)
    });
    if (putR.ok) {
      el.textContent = '✅ 已同步'; el.className = 'sync-status show ok';
      setTimeout(() => { el.className = 'sync-status'; }, 3000);
    } else {
      const err = await putR.json();
      el.textContent = '❌ ' + (err.message||putR.status); el.className = 'sync-status show err';
    }
  } catch(e) {
    el.textContent = '❌ 网络错误'; el.className = 'sync-status show err';
  }
}

async function loadOverrides() {
  try {
    const r = await fetch('cost-overrides.json');
    if (r.ok) { const remote = await r.json(); if (remote && typeof remote === 'object') Object.assign(costOverrides, remote); }
  } catch(e) {}
  try {
    const local = JSON.parse(localStorage.getItem(LS_KEY) || '{}');
    if (local && typeof local === 'object') Object.assign(costOverrides, local);
  } catch(e) {}
}

// ═══════════════ HOLDINGS SYNC (跨设备同步持仓) ═══════════════
function getHoldingsGHPath() {
  var key = getMyKey();
  return 'https://api.github.com/repos/' + GH_REPO + '/contents/holdings_' + key + '.json';
}

window.syncHoldingsToGitHub = async function() {
  var btn = document.getElementById('syncBtn');
  var origText = btn ? btn.innerHTML : '';
  if (btn) { btn.classList.add('syncing'); btn.innerHTML = '⏳同步中'; btn.style.opacity='.6'; btn.style.pointerEvents='none'; }
  var el = document.getElementById('syncStatus');
  if (!el) { showToast('同步失败：界面未加载',3000); resetBtn(); return; }
  var key = getMyKey();
  if (!key) { el.textContent='❌ 请先登录'; el.className='sync-status show err'; showToast('❌ 请先登录',3000); resetBtn(); return; }
  if (!ghToken) { el.textContent='❌ 请先配置 GitHub Token（⚙齿轮）'; el.className='sync-status show err'; showToast('❌ 没有 GitHub Token',3000); resetBtn(); return; }
  var items = loadMyHoldings();
  if (!items.length) { el.textContent='❌ 持仓为空'; el.className='sync-status show err'; showToast('❌ 持仓为空',3000); resetBtn(); return; }
  el.textContent='⏳ 同步持仓中...'; el.className='sync-status show';
  var repo = GH_REPO;
  var auth = {'Authorization':'token '+ghToken, 'Accept':'application/vnd.github.v3+json'};
  try {
    var jsonStr = JSON.stringify({update_time:new Date().toISOString(),items:items},null,2);
    var b64 = btoa(unescape(encodeURIComponent(jsonStr)));
    var path = 'holdings_' + key + '.json';
    var blobR = await fetch('https://api.github.com/repos/'+repo+'/git/blobs', {
      method:'POST', headers:auth, body:JSON.stringify({content:b64,encoding:'base64'})
    });
    if (!blobR.ok) { el.textContent='❌ blob失败 '+blobR.status; el.className='sync-status show err'; showToast('❌ blob失败',3000); resetBtn(); return; }
    var blobSha = (await blobR.json()).sha;
    var refR = await fetch('https://api.github.com/repos/'+repo+'/git/refs/heads/main', {headers:auth});
    if (!refR.ok) { el.textContent='❌ 获取commit失败 '+refR.status; el.className='sync-status show err'; showToast('❌ commit失败',3000); resetBtn(); return; }
    var refData = await refR.json();
    var latestCommitSha = refData.object.sha;
    var commitR = await fetch('https://api.github.com/repos/'+repo+'/git/commits/'+latestCommitSha, {headers:auth});
    if (!commitR.ok) { el.textContent='❌ 获取tree失败'; el.className='sync-status show err'; showToast('❌ tree失败',3000); resetBtn(); return; }
    var baseTreeSha = (await commitR.json()).tree.sha;
    var treeR = await fetch('https://api.github.com/repos/'+repo+'/git/trees', {
      method:'POST', headers:auth, body:JSON.stringify({base_tree:baseTreeSha, tree:[{path:path,mode:'100644',type:'blob',sha:blobSha}]})
    });
    if (!treeR.ok) { el.textContent='❌ tree失败 '+treeR.status; el.className='sync-status show err'; showToast('❌ tree失败',3000); resetBtn(); return; }
    var treeSha = (await treeR.json()).sha;
    var commitBody = {message:'sync: holdings for '+key, tree:treeSha, parents:[latestCommitSha]};
    var newCommitR = await fetch('https://api.github.com/repos/'+repo+'/git/commits', {
      method:'POST', headers:auth, body:JSON.stringify(commitBody)
    });
    if (!newCommitR.ok) { el.textContent='❌ commit失败 '+newCommitR.status; el.className='sync-status show err'; showToast('❌ commit失败',3000); resetBtn(); return; }
    var newCommitSha = (await newCommitR.json()).sha;
    var updateR = await fetch('https://api.github.com/repos/'+repo+'/git/refs/heads/main', {
      method:'PATCH', headers:auth, body:JSON.stringify({sha:newCommitSha,force:true})
    });
    if (updateR.ok) {
      el.textContent='✅ 持仓已同步'; el.className='sync-status show ok';
      showToast('✅ 持仓同步成功',3000);
      setTimeout(function(){el.className='sync-status'},5000);
    } else {
      el.textContent='❌ 更新ref失败 '+updateR.status; el.className='sync-status show err';
      showToast('❌ 同步失败（'+updateR.status+'）',3000);
    }
    resetBtn();
  } catch(e) {
    el.textContent='❌ 网络错误'; el.className='sync-status show err';
    showToast('❌ 同步失败：网络错误',3000);
    resetBtn();
  }
  function resetBtn(){ if(btn){ btn.classList.remove('syncing'); btn.innerHTML='↑ 同步'; btn.style.opacity=''; btn.style.pointerEvents=''; } }
}

window.loadHoldingsFromGitHub = async function() {
  var key = getMyKey();
  if (!ghToken || !key) { alert('请先登录并配置 GitHub Token'); return; }
  try {
    var r = await fetch('https://api.github.com/repos/'+GH_REPO+'/contents/holdings_'+key+'.json?ref=main', {headers:{'Authorization':'token '+ghToken,'Accept':'application/vnd.github.v3+json'}});
    if (!r.ok) { alert('远程没有持仓数据（状态码：'+r.status+'）'); return; }
    var d = await r.json();
    var content = JSON.parse(decodeURIComponent(escape(atob(d.content))));
    if (content && content.items && content.items.length) {
      saveMyHoldings(content.items);
      alert('✅ 已恢复 '+content.items.length+' 件持仓，即将刷新');
      location.reload();
    } else {
      alert('远程持仓数据为空');
    }
  } catch(e) {
    alert('加载失败：'+e.message);
  }
}

// ═══════════════ STAR SYSTEM ═══════════════
function saveStars() { localStorage.setItem(LS_STARRED, JSON.stringify(starred)); updateWatchCount(); }
function updateWatchCount() { }
function toggleStar(goodId) {
  starred[goodId] = !starred[goodId];
  saveStars();
  document.querySelectorAll('.row-star[data-gid="'+goodId+'"]').forEach(b => { b.textContent = starred[goodId] ? '★' : '☆'; });
}

// ═══════════════ LOAD DATA ═══════════════
const CACHE_TTL = 5 * 60 * 1000;
const CACHE_KEY = 'cs2_market_cache';

function getCachedMarket() {
  try {
    const cached = localStorage.getItem(CACHE_KEY);
    if (cached) {
      const data = JSON.parse(cached);
      if (Date.now() - data.ts < CACHE_TTL) return data.market;
    }
  } catch(e) {}
  return null;
}

function setCachedMarket(market) {
  try { localStorage.setItem(CACHE_KEY, JSON.stringify({ts: Date.now(), market})); } catch(e) {}
}

async function loadAll() {
  // 用「数据版本号」代替「当前时间戳」作为缓存键：
  // 数据未更新时 URL 不变，浏览器可直接命中缓存，不再每次都下载 8MB+ 数据。
  // （旧写法 Date.now() + cache:'no-store' 等于完全禁用缓存）
  let t0 = String(Math.floor(Date.now() / 300000));
  try {
    var _st = await fetch('data_status.json?ts=' + Date.now(), { cache: 'no-store' })
      .then(function(r) { return r.ok ? r.json() : null; })
      .catch(function() { return null; });
    if (_st && _st.updated) t0 = String(_st.updated).replace(/[^0-9A-Za-z:_-]/g, '');
  } catch (e) {}
  const fetchOpts = {};
  updateProgress(20);
  
  await loadOverrides();

  // 并行加载 market + holdings
  const cachedMarket = getCachedMarket();
  const marketP = cachedMarket
    ? Promise.resolve(cachedMarket)
    : fetch('market.json?v=' + t0, fetchOpts).then(r => r.json()).then(function(m) {
        if (m) setCachedMarket(m); return m;
      }).catch(() => null);
  
  const holdingsP = fetch('holdings.json?v=' + t0, fetchOpts).then(r => r.json()).catch(() => null);
  
  // 尽快渲染主内容
  const [marketR, _hr] = await Promise.all([marketP, holdingsP]);
  let holdingsR = _hr;
  updateProgress(60);

  // AI 分析异步预热
  var aiP = fetch('ai_analysis.json?v=' + t0, fetchOpts).then(r => r.json()).then(function(ai) {
    window._aiAnalysis = ai || {};
    var openRows = document.querySelectorAll('.row-analysis.open');
    for (var ri = 0; ri < openRows.length; ri++) {
      var td = openRows[ri].firstChild;
      var tr = openRows[ri].previousElementSibling;
      if (tr && tr._item && td) td.innerHTML = buildItemAnalysisHTML(tr._item);
    }
    document.dispatchEvent(new CustomEvent('ai-loaded'));
    return ai;
  }).catch(function() { window._aiAnalysis = {}; return {}; });
  // AI 徽章内联渲染
  window.aiBadgeHTML = function(name) {
    var ai = window._aiAnalysis || {};
    var txt = ai[name] || null;
    if (!txt) return '';
    var v, confidence, reason, risk, entryLow, entryHigh;
    if (typeof txt === 'object') {
      v = txt.verdict || '';
      confidence = txt.confidence || 0;
      reason = txt.reason || '';
      risk = txt.risk || '';
      entryLow = txt.entryLow || 0;
      entryHigh = txt.entryHigh || 0;
    } else {
      var m = txt.match(/操作建议[:：]\s*(\S+)/);
      v = (m||[])[1]||'';
      confidence = 0;
      reason = txt.replace(/.*核心逻辑[:：]\s*/s,'').replace(/\s*⚠.*/s,'').trim();
      risk = (txt.match(/风险[:：]\s*(.+)/)||[])[1]||'';
    }
    if (!v) return '';
    var cls = v.includes('减仓')||v.includes('卖出') ? 'sell' : v.includes('持有')||v.includes('加仓') ? 'hold' : 'wait';
    var tip = 'AI分析: ' + v;
    if (confidence) tip += ' (置信度' + confidence + ')';
    if (reason) tip += '\n理由: ' + reason;
    if (risk) tip += '\n风险: ' + risk;
    return '<span class="ai-table-badge '+cls+'" title="' + esc(tip) + '">🤖 ' + v + (confidence ? ' ' + confidence + '%' : '') + '</span>';
  };
  // 未登录不显示任何持仓数据
  if (!getMyKey()) { holdingsR = null; }
  // 如果已登录，合并个人持仓
  var myHoldings = loadMyHoldings();
  if (myHoldings.length > 0 && holdingsR && Array.isArray(holdingsR.items)) {
    // 合并：个人持仓覆盖同名物品，同时保留 holdings.json 的价格数据
    var priceMap = {};
    holdingsR.items.forEach(function(it){ priceMap[it.market_hash] = it; });
    myHoldings.forEach(function(mh){
      var server = priceMap[mh.market_hash];
      if(server) {
        // 继承服务器端的价格、涨跌率等数据
        mh.price = server.price;
        mh.rate_1 = server.rate_1;
        mh.rate_7 = server.rate_7;
        mh.rate_30 = server.rate_30;
        mh.buff_sell = server.buff_sell || 0;
        mh.buff_buy = server.buff_buy || 0;
        mh.yyyp_sell = server.yyyp_sell || 0;
      }
    });
    holdingsR = { items: myHoldings };
  } else if (myHoldings.length > 0) {
    holdingsR = { items: myHoldings };
  } else if (!holdingsR || !holdingsR.items) {
    holdingsR = null;
  }

  // ── Process holdings ──
  if (holdingsR && Array.isArray(holdingsR.items)) {
    H = [];
    window.H = H;  // 更新全局引用，确保 openItemDetail 能找到数据
    holdingsR.items.forEach(item => {
      const catKey = CAT_MAP[item.category] || 'other';
      const wearCode = item.wear || '';  // FN/MW/FT/WW/BS/other/'' 
      const q = item.qty || 1;
      // cost: single number per item (total for qty)
      const costTotal = item.cost;
      const pricePerUnit = item.price;   // ECO returns per-unit price
      const costPerUnit = costTotal / q;

      for (let i = 0; i < q; i++) {
        const key = overrideKey(item.name, wearCode === 'other' ? '' : wearCode);
        const cU = costOverrides[key] || costPerUnit;
        H.push({
          n: item.name,
          w: wearCode === 'other' ? '' : wearCode,
          t: catKey,
          q: 1,
          c: cU,
          p: pricePerUnit,
          pnl: pricePerUnit - cU,
          pnlPct: cU > 0 ? (pricePerUnit - cU) / cU * 100 : 0,
          gid: item.id || 0,
          mh: item.market_hash,
          // 传递涨跌率字段（update.py写入）
          rate_1: item.rate_1,
          rate_7: item.rate_7,
          rate_30: item.rate_30,
          price_history: item.price_history,
          buff_sell: item.buff_sell || 0,
          buff_buy: item.buff_buy || 0,
          buff_sell_num: item.buff_sell_num || 0,
          buff_buy_num: item.buff_buy_num || 0,
          yyyp_sell: item.yyyp_sell || 0,
          yyyp_sell_num: item.yyyp_sell_num || 0
        });
      }
    });
  }

  // ── Load Chinese name map from name_map.json (all 37k items) ──
  window._cnNameMap = window._cnNameMap || {};
  fetch('name_map.json?v='+t0).then(function(r){return r.ok?r.json():null;}).then(function(nm){
    if(nm && typeof nm === 'object'){
      window._cnNameMap = nm;
      render();
    }
  }).catch(function(){});

  // ── Process market ──
  if (marketR) {
    marketData = marketR;
    // Store tracked names for autocomplete
    if (marketR.eco_tracked_names && marketR.eco_tracked_names.length) {
      window._trackedNames = marketR.eco_tracked_names;
      // Populate datalist — 优先持仓物品（中英文都加）
      var dl = document.getElementById('nameDatalist');
      if (dl) {
        dl.innerHTML = '';
        var seen = {};
        (H || []).forEach(function(h) {
          var cn = h.n || '';           // 中文名 "M4A1消音版 | 苔藓石英 (崭新出厂)"
          var en = h.mh || '';          // 英文名 "M4A1-S | Moss Quartz (Factory New)"
          if (cn && !seen[cn]) { seen[cn] = true; addOpt(cn); }
          if (en && !seen[en]) { seen[en] = true; addOpt(en); }
        });
        marketR.eco_tracked_names.slice(0, 3000).forEach(function(n) {
          if (!seen[n]) { seen[n] = true; addOpt(n); }
        });
      }
      function addOpt(v) { var o = document.createElement('option'); o.value = v; dl.appendChild(o); }
    }
    const ut = marketR.updated || marketR.alerts_updated || marketR.market_updated || marketR.update_time || marketR.items_updated;
    if (DOM.updateTime) {
      DOM.updateTime.textContent = (ut ? '数据 ' + new Date(ut).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) : '刷新 ' + new Date(t0).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}));
    }
    recData = marketR.recommendations || {};
    // 自动记录推荐数据到浏览器本地存储
    try {
      var allRecs = (recData.all || []).slice(0, 30);
      var today = new Date().toISOString().slice(0,10);
      var prev = JSON.parse(localStorage.getItem('cs2_rec_tracks') || '[]');
      var existing = {}; prev.forEach(function(t){existing[t.name+'_'+t.date] = true;});
      var added = false;
      allRecs.forEach(function(r){
        var key = (r.name||'') + '_' + today;
        if (!existing[key]) {
          existing[key] = true;
          prev.push({name: r.name||'', date: today, recPrice: r.price||r.eco_price||0, channel: r.channel||'eco'});
          added = true;
        }
      });
      if (added) {
        if (prev.length > 500) prev = prev.slice(-500);
        localStorage.setItem('cs2_rec_tracks', JSON.stringify(prev));
      }
    } catch(_) {}
    // 推荐板块显示当前加载时间（随刷新按钮更新）
    if (DOM.recUpdateTime) DOM.recUpdateTime.textContent = ut ? new Date(ut).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) : '';
  } else {
    // no market.json at all — show refresh time
    if (DOM.updateTime) DOM.updateTime.textContent = '刷新 ' + new Date(t0).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
  }

  initDashboard();
  // 初始视图：读 URL hash，无则默认「推荐」（真标签页，只显示一个面板）
  if (typeof initView === 'function') initView();
  // 加载 ECO 基础价格用于持仓（兜底）
  fetch('eco_tracked.json?v=' + t0).then(function(r){ return r.ok ? r.json() : []; }).then(function(ecoItems){
    // 建立双索引：HashName→Price 和 GoodsName→Price
    var ecoMap = {};
    ecoItems.forEach(function(e){
      if(e.HashName && e.Price>0) ecoMap[e.HashName] = e.Price;
      if(e.GoodsName && e.Price>0 && !ecoMap[e.GoodsName]) ecoMap[e.GoodsName] = e.Price;
    });
    window._ecoPrices = ecoMap;
    if (H && H.length) {
      H.forEach(function(h){
        var hn = h.mh || h.n;
        var ecoP = ecoMap[hn];
        if (!ecoP && h.n) ecoP = ecoMap[h.n]; // 也试中文名
        if (ecoP > 0) { h.eco_price = ecoP; if (!h.p) { h.p = ecoP; h.pnl = ecoP - h.c; h.pnlPct = h.c>0?(ecoP-h.c)/h.c*100:0; } }
      });
    }
  }).catch(function(){});
  // 加载 BUFF 历史数据（用于持仓折线图）
  fetch('buff_recent.json?v=' + t0).then(function(r){ return r.ok ? r.json() : {}; }).then(function(bh){
    window._buffHistory = bh || {};
    // 用 buff_history 补充持仓物品的 BUFF/悠悠价格
    if (H && H.length) {
      var latest = Object.keys(bh).sort().pop();
      if (latest && bh[latest]) {
        H.forEach(function(h){
          var hn = h.mh || h.n;
          if (!hn || !bh[latest][hn]) return;
          var dp = bh[latest][hn];
          if (dp.buff_sell > 0 && !h.buff_sell) { h.buff_sell = dp.buff_sell; h.buff_sell_num = dp.buff_sell_num || 0; }
          if (dp.yyyp_sell > 0 && !h.yyyp_sell) { h.yyyp_sell = dp.yyyp_sell; h.yyyp_sell_num = dp.yyyp_sell_num || 0; }
        });
      }
    }
  }).catch(function(){});
  renderNews();
  loadFirePulseOverview();
  setTimeout(hideSkeleton, 80);
}

// ═══════════════ DASHBOARD INIT ═══════════════
function initDashboard() {
  buildTabs();
  recPage = 1;

  // 收集所有需要实时查价的物品（推荐 + 持仓）
  var allItems = (recData.all || []).slice()
  var holdingNames = (H || []).map(function(h){ return h.mh || ''; }).filter(Boolean)

  fetchLivePrices(allItems, holdingNames).then(function(){
    // 注：此处原有一端「前端二次评分」逻辑，用 (buff_sell - eco_price)/eco_price
    // 计算溢价并覆盖 r.score。因 eco_price 是低端档位价、与 buff_sell 口径不同，
    // 算出的溢价动辄数千%，会把后端 FirePulse 评分覆盖成假高分。
    // 已于 2026-09-14 移除，评分统一以后端 score_with_firepulse() 为准。

    renderAllRecs()
    render()
    updateKPI()
    renderNews()
  }).catch(function(){
    renderAllRecs()
    render()
    updateKPI()
    renderNews()
  })

  // Setup all button handlers
  setupExportBtn()
  setupChangelogClose()
  setupRefreshBtn()
  setupTokenModal()
  var lb2 = document.getElementById('loadBar');
  if(lb2) { lb2.classList.remove('active'); lb2.classList.add('done'); }
}


// ═══════════════ CS2 NEWS CENTER ═══════════════
let cs2NewsData = null;
let newsTab = 'news';

// ── 新闻关键词分类 ──
function classifyNews(title, body) {
  var txt = ((title||'') + ' ' + (body||'')).toLowerCase();
  var bull = [
    '新武器箱','新皮肤','大行动','新地图','掉落','新收藏品','新印花','武器箱更新',
    '新增武器','新饰品','活动','折扣','免费','掉落重置','新纪念品',
    'major','iem','esl','锦标赛','冠军','邀请赛','胶囊','通行证','签名','淘汰赛',
    '新音乐','新标签','新系列','回归','来袭','上新','上架','登场',
    '音乐套件','音乐盒','新曲','音乐包',
    '更新','改进','优化','增强','新增','调整武器',
    'workshop','工坊','联动','合作','联名','限定'
  ];
  var bear = [
    '削弱','涨价','手续费','封禁','ban','vac','减少','下架','移除',
    'bug','崩溃','宕机','延迟','维护','停服','回档','漏洞','暂停',
    '调整武器','限制','关闭','终止','过期','失效'
  ];
  for (var i=0;i<bull.length;i++) if(txt.indexOf(bull[i])>=0) return 'bull';
  for (var i=0;i<bear.length;i++) if(txt.indexOf(bear[i])>=0) return 'bear';
  return 'neutral';
}

async function fetchCS2News() {
  try {
    const r = await fetch('news.json');
    const j = await r.json();
    return (j.news || []).map(function(n) { return {
      title: n.title,
      body: n.body,
      url: n.url || 'https://steamcommunity.com/app/730/',
      date: new Date(n.date * 1000),
      source: n.source || 'Steam',
      type: 'news' }; });
  } catch(e) {}
  return [];
}

async function fetchCS2Updates() {
  try {
    const r = await fetch('news.json');
    const j = await r.json();
    return (j.updates || []).map(function(n) { return {
      title: n.title,
      body: n.body,
      url: n.url || 'https://store.steampowered.com/news/app/730',
      date: new Date(n.date * 1000),
      source: n.source || 'CS2',
      type: 'update' }; });
  } catch(e) {}
  return [];
}

function calcSentiment() {
  var signals = [];
  var score = 50;
  // 全量市场数据（从 market_scan.json）
  var scan = window._marketScan || {};
  if (scan.movers) {
    var gainers = scan.movers.gainers || [], losers = scan.movers.losers || [];
    var totalMovers = gainers.length + losers.length || 1;
    var gainRatio = gainers.length / totalMovers;
    // 涨跌比影响分数
    if (gainRatio >= 0.7)       { score += 20; signals.push({emoji:'🚀', text:'涨跌比 '+gainers.length+':'+losers.length+'，市场强势'}); }
    else if (gainRatio <= 0.3)  { score -= 20; signals.push({emoji:'📉', text:'涨跌比 '+gainers.length+':'+losers.length+'，市场普跌'}); }
    else if (gainRatio >= 0.5)  { score += 8;  signals.push({emoji:'📈', text:'涨跌比 '+gainers.length+':'+losers.length+'，市场偏多'}); }
    else                        { score -= 8;  signals.push({emoji:'📊', text:'涨跌比 '+gainers.length+':'+losers.length+'，市场承压'}); }
    // 平均涨跌幅度
    var avgGain = gainers.length ? gainers.reduce(function(s,g){return s+g.r7;},0)/gainers.length : 0;
    var avgLoss = losers.length ? losers.reduce(function(s,l){return s+l.r7;},0)/losers.length : 0;
    if (avgGain > 20)      { score += 10; signals.push({emoji:'🔥', text:'平均涨幅 +'+avgGain.toFixed(0)+'%，资金活跃'}); }
    else if (avgGain > 5)  { score += 5;  signals.push({emoji:'📈', text:'平均涨幅 +'+avgGain.toFixed(0)+'%'}); }
    if (avgLoss < -30)     { score -= 10; signals.push({emoji:'❄', text:'平均跌幅 '+avgLoss.toFixed(0)+'%，抛压明显'}); }
    else if (avgLoss < -10){ score -= 5;  signals.push({emoji:'📉', text:'平均跌幅 '+avgLoss.toFixed(0)+'%'}); }
  }
  // 价格分布
  if (scan.tiers) {
    var t = scan.tiers, tierTotal = Object.values(t).reduce(function(a,b){return a+b;},0)||1;
    var highEnd = (t['200-1000']||0) + (t['>1000']||0);
    var highRatio = highEnd / tierTotal;
    if (highRatio > 0.3) { score += 5; signals.push({emoji:'💎', text:'高端饰品占比'+(highRatio*100).toFixed(0)+'%，市场活跃'}); }
  }
  // 持仓对比
  if (H && H.length) {
    var upCount = 0, downCount = 0;
    H.forEach(function(h){ if(h.pnl>=0) upCount++; else downCount++; });
    var winRate = upCount/H.length;
    if (winRate > 0.7)      { score += 10; signals.push({emoji:'🏆', text:'持仓胜率'+(winRate*100).toFixed(0)+'%，优于市场'}); }
    else if (winRate < 0.3) { score -= 10; signals.push({emoji:'⚠', text:'持仓胜率'+(winRate*100).toFixed(0)+'%，需关注'}); }
  }
  score = Math.max(0, Math.min(100, score));
  var vibe = score >= 65 ? '🐂 看多' : score <= 35 ? '🐻 看空' : '⚖ 中性';
  var color = score >= 65 ? 'var(--rise)' : score <= 35 ? 'var(--fall)' : 'var(--text2)';
  return { score: score, vibe: vibe, color: color, signals: signals };
}

// ── FirePulse 大盘条 ──
async function loadFirePulseOverview() {
  try {
    var t = Math.floor(Date.now()/900000);
    var r = await fetch('market_overview.json?v=' + t);
    if (!r.ok) return;
    var d = await r.json();
    if (!d || !d.index) return;
    var el = document.getElementById('fpOverview');
    if (!el) return;
    el.style.display = 'grid';
    var ix = d.index || {}, tr = d.trade || {}, ud = d.updown || {}, gd = d.greedy || {};
    var pct = ix.change_pct;
    document.getElementById('fpIndex').textContent = (ix.current != null) ? Number(ix.current).toFixed(2) : '--';
    var chg = document.getElementById('fpIndexChg');
    if (pct != null) {
      var cls = pct >= 0 ? 'clr-rise' : 'clr-fall';
      var days = ix.change_days ? (' · 连' + (ix.change_days > 0 ? '涨' : '跌') + Math.abs(ix.change_days) + '天') : '';
      chg.className = cls;
      chg.textContent = (pct >= 0 ? '+' : '') + Number(pct).toFixed(2) + '%' + days;
    }
    if (tr.today_amount != null) {
      document.getElementById('fpAmount').textContent = '¥' + (tr.today_amount/10000).toFixed(0) + '万';
      var mom = tr.amount_mom;
      var mEl = document.getElementById('fpAmountMom');
      if (mom != null) {
        mEl.textContent = '环比昨日 ' + (mom >= 0 ? '+' : '') + Number(mom).toFixed(1) + '%';
        mEl.className = 'k-sub ' + (mom >= 0 ? 'clr-rise' : 'clr-fall');
      }
    }
    if (ud.up != null) document.getElementById('fpUp').textContent = ud.up;
    if (ud.down != null) document.getElementById('fpDown').textContent = ud.down;
    if (gd.value != null) {
      document.getElementById('fpGreedy').textContent = Number(gd.value).toFixed(1);
      var gl = document.getElementById('fpGreedyLabel');
      gl.textContent = (gd.label || '') + (gd.change != null ? (' · ' + (gd.change >= 0 ? '+' : '') + gd.change) : '');
      gl.style.color = (gd.value >= 60) ? 'var(--rise)' : (gd.value <= 30 ? 'var(--fall)' : 'var(--text3)');
    }
  } catch (e) {}

  // 走势图：优先用 API 自带的 24h 指数走势（即时可用），历史采样点作补充
  try {
    var pts = (d.trend_24h || []).slice(-24);
    if (pts.length < 2) {
      var hr = await fetch('market_overview_history.json?v=' + t);
      if (hr.ok) {
        var hd = await hr.json();
        Object.keys(hd || {}).sort().forEach(function (day) {
          (hd[day] || []).forEach(function (p) { if (p.index != null) pts.push(p.index); });
        });
        pts = pts.slice(-24);
      }
    }
    var sp = document.getElementById('fpSpark');
    if (sp && typeof window.sparkline === 'function' && pts.length >= 2) {
      sp.innerHTML = window.sparkline(pts, (pts[pts.length-1] >= pts[0]) ? 'var(--rise)' : 'var(--fall)', 110, 22);
      sp.title = '饰品指数近24小时走势';
    }
  } catch (e) {}

  // 板块数据（24 个板块横向滚动）
  try {
    var sr = await fetch('market_sectors.json?v=' + t);
    if (sr.ok) {
      var sd = await sr.json();
      var box = document.getElementById('fpSectors');
      if (box && sd && sd.sectors && sd.sectors.length) {
        box.style.display = 'flex';
        box.innerHTML = sd.sectors.map(function (s) {
          var spct = s.change_pct;
          var scls = (spct != null && spct >= 0) ? 'clr-rise' : 'clr-fall';
          var val = (s.index != null) ? Number(s.index).toFixed(0) : '--';
          var txt = (spct != null) ? ((spct >= 0 ? '+' : '') + Number(spct).toFixed(2) + '%') : '--';
          return '<div style="flex:0 0 auto;background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:5px 10px;white-space:nowrap;line-height:1.5">'
            + '<span style="color:var(--text2)">' + (s.name || '') + '</span> '
            + '<b style="margin-left:4px">' + val + '</b> '
            + '<span class="' + scls + '" style="margin-left:3px">' + txt + '</span>'
            + '</div>';
        }).join('');
      }
    }
  } catch (e) {}
}


async function renderNews() {
  if (!DOM.newsSection) return;
  // 注意：资讯面板的显隐由 switchView() 统一管理，此处不再强制 display=''，
  // 否则会让资讯区在「推荐/持仓」视图下也被撑开显示。
  // 加载 AI 空投监控
  fetch('ai_news_impact.json?v=' + Math.floor(Date.now()/900000)).then(function(r) { return r.ok ? r.json() : null; }).then(function(d) {
    var bar = document.getElementById('aiNewsImpact');
    var txt = document.getElementById('aiNewsImpactText');
    if (!bar || !txt) return;
    if (d && d.impact && d.impact.length > 5) { txt.textContent = d.impact; bar.style.display = ''; }
    else if (d && d.headlines && d.headlines.length) { txt.textContent = '最新公告：' + d.headlines[0].replace('- ','') + '... | AI分析生成中，请稍后刷新'; bar.style.display = ''; }
  }).catch(function() {});
  if (!cs2NewsData) {
    var grid = $('newsGrid');
    if (grid) grid.innerHTML = '<div class="news-loading"><span class="spinner"></span>加载资讯中...</div>';
    var results = await Promise.all([fetchCS2News(), fetchCS2Updates()]);
    var all = results[0].concat(results[1]);
    all.sort(function(a,b){ return b.date - a.date; });
    cs2NewsData = { all: all };
    if (DOM.newsUpdateTime) {
      DOM.newsUpdateTime.textContent = new Date().toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
    }
  }
  renderNewsTab(newsTab);
  setupNewsTabs();
}

function renderNewsTab(tab) {
  newsTab = tab;
  var grid = $('newsGrid');
  if (!grid) return;
  var html = '';
  if (tab === 'news') {
    var items = cs2NewsData ? cs2NewsData.all : [];
    var itemsToShow = items.slice(0, 15);
    itemsToShow.forEach(function(n) {
      var isUpdate = n.type === 'update';
      var srcLabel = isUpdate ? '🔧 更新' : '📰 新闻';
      var srcColor = isUpdate ? '#f59e0b' : '#3b82f6';
      // 关键词分类利好利空
      var sentiment = classifyNews(n.title,n.body);
      if(sentiment==='bull') sentiment='<span style="color:#4ade80;font-size:10px;padding:2px 6px;background:rgba(74,222,128,.12);border-radius:4px">▲ 利好</span>';
      else if(sentiment==='bear') sentiment='<span style="color:#f87171;font-size:10px;padding:2px 6px;background:rgba(248,113,113,.12);border-radius:4px">▼ 利空</span>';
      else sentiment='';
      var tm = n.date.toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
      html += '<div class="news-card" onclick="window.open(\''+esc(n.url||'')+'\',\'_blank\')">'+
        '<span class="nc-source" style="color:'+srcColor+'">'+esc(srcLabel)+' '+sentiment+'</span>'+
        '<span class="nc-title">'+esc(n.title)+'</span>'+
        '<span class="nc-body">'+esc(n.body||n.title)+'</span>'+
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px">'+
          '<span class="nc-time">'+tm+'</span>'+
          '<span class="nc-link">阅读全文 ↗</span>'+
        '</div></div>';
    });
    if (!items.length) html = '<div class="news-loading">暂无数据</div>';
    grid.innerHTML = html;
    grid.style.cssText = 'display:grid;grid-template-columns:repeat(3,1fr);gap:12px';
  } else if (tab === 'sentiment') {
    var s = calcSentiment();
    var upCount = H.filter(function(h){return (h.rate_7||0)>0;}).length;
    var dnCount = H.filter(function(h){return (h.rate_7||0)<0;}).length;
    var noData = H.length - upCount - dnCount;
    var totalV = H.reduce(function(sum,h){var v=h.p*(h.q||1);return sum+(isNaN(v)?0:v);},0);
    var totalC = H.reduce(function(sum,h){var c=h.c*(h.q||1);return sum+(isNaN(c)?0:c);},0);
    var pnl = totalV - totalC;
    var pnlPct = totalC>0?(pnl/totalC*100):0;
    var winCount = H.filter(function(h){return h.pnl>=0;}).length;
    var winRate = H.length?(winCount/H.length*100).toFixed(1):'0';
    
    html += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">'+
      // 左：情绪仪表盘
      '<div class="sentiment-card">'+
        '<h4>🎭 市场情绪</h4>'+
        '<div style="text-align:center;padding:16px 0">'+
          '<div style="font-size:48px;margin-bottom:4px">'+(s.score>=65?'🐂':s.score<=35?'🐻':'⚖')+'</div>'+
          '<div style="font-size:20px;font-weight:700;color:'+s.color+'">'+s.score+'/100 · '+s.vibe+'</div>'+
        '</div>'+
        '<div class="sentiment-track" style="height:6px;margin-top:8px"><div class="sentiment-fill" style="width:'+s.score+'%;background:linear-gradient(90deg,#f87171,#fbbf24,#4ade80);border-radius:3px"></div></div>'+
        '<div style="display:flex;justify-content:space-between;font-size:9px;color:var(--text3);margin-top:2px"><span>🐻 看空0</span><span>⚖ 中性50</span><span>🐂 看多100</span></div>'+
      '</div>'+
      // 右：持仓健康
      '<div class="sentiment-card">'+
        '<h4>💼 持仓健康</h4>'+
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px">'+
          '<div style="text-align:center"><div style="font-size:24px;font-weight:700;color:'+(pnlPct>=0?'var(--rise)':'var(--fall)')+'">'+(pnlPct>=0?'+':'')+pnlPct.toFixed(1)+'%</div><div style="font-size:10px;color:var(--text3);margin-top:2px">持仓盈亏率</div></div>'+
          '<div style="text-align:center"><div style="font-size:24px;font-weight:700;color:var(--rise)">'+winRate+'%</div><div style="font-size:10px;color:var(--text3);margin-top:2px">胜率</div></div>'+
          '<div style="text-align:center"><div style="font-size:24px;font-weight:700;color:var(--text)">'+H.length+'</div><div style="font-size:10px;color:var(--text3);margin-top:2px">持仓品种</div></div>'+
          '<div style="text-align:center"><div style="font-size:24px;font-weight:700;color:'+(pnl>=0?'var(--rise)':'var(--fall)')+'">¥'+(pnl>=0?'+':'')+pnl.toFixed(0)+'</div><div style="font-size:10px;color:var(--text3);margin-top:2px">总盈亏</div></div>'+
        '</div>'+
      '</div>'+
    '</div>'+
    // 涨跌分布 + 信号
    '<div class="sentiment-card" style="margin-top:12px">'+
      '<h4>📊 持仓涨跌分布 · '+H.length+'件</h4>'+
      '<div style="margin-top:10px">'+
        '<div style="display:flex;height:20px;background:var(--border);border-radius:10px;overflow:hidden">'+
          '<div style="height:100%;width:'+(H.length?upCount/H.length*100:0)+'%;background:#4ade80;border-radius:10px 0 0 10px;transition:width .6s;"></div>'+
          (noData>0?'<div style="height:100%;width:'+(H.length?noData/H.length*100:0)+'%;background:rgba(148,163,184,.4);position:relative;transition:width .6s"><span style="position:absolute;top:-18px;left:50%;transform:translateX(-50%);font-size:9px;color:var(--text3);white-space:nowrap">'+noData+'件无数据</span></div>':'')+
          '<div style="height:100%;width:'+(H.length?dnCount/H.length*100:0)+'%;background:#ef4444;border-radius:0 10px 10px 0;transition:width .6s"></div>'+
        '</div>'+
        '<div style="display:flex;justify-content:space-between;font-size:11px;margin-top:4px;color:var(--text2)">'+
          '<span style="color:#4ade80">📈 '+upCount+'只涨</span>'+
          (noData>0?'<span style="color:var(--text3)">'+noData+'件无数据</span>':'')+
          '<span style="color:#ef4444">📉 '+dnCount+'只跌</span>'+
        '</div>'+
      '</div>'+
      '<div style="margin-top:12px;font-size:11px;color:var(--text2)">'+
        s.signals.map(function(sig){return '<span style="margin-right:16px">'+sig.emoji+' '+sig.text+'</span>';}).join('')+
      '</div>'+
    // ── AI 洞察 ──
    renderAIPanel(H) +
    '</div>';
    grid.innerHTML = html;
    grid.style.cssText = '';
  }
}

// ── AI 洞察面板 ──
function renderAIPanel(H) {
  var ai = window._aiAnalysis || {};
  if (!Object.keys(ai).length) return '';  // 没有 AI 数据不显示
  // 统计
  var counts = { sell: 0, hold: 0, wait: 0, total: 0 };
  var decisions = [];
  H.forEach(function(h) {
    var mk = h.n || h.mh || '';  // AI key 用中文名
    var txt = ai[mk];
    if (!txt) return;
    var v = (typeof txt === 'object' ? txt.verdict : (txt.match(/操作建议[:：]\s*(\S+)/)||[])[1]) || '';
    var c = (typeof txt === 'object' ? txt.confidence : parseInt((txt.match(/置信度[:：]\s*(\d+)/)||[])[1]||'0'));
    var reason = (typeof txt === 'object' ? txt.reason : (txt.match(/核心逻辑[:：]\s*(.+)/)||[])[1]) || '';
    if (v.includes('减仓')||v.includes('卖出')) { counts.sell++; }
    else if (v.includes('持有')||v.includes('加仓')) { counts.hold++; }
    else { counts.wait++; }
    counts.total++;
    decisions.push({ name: h.n||mk, wear: h.w, verdict: v, confidence: c, reason: reason });
  });
  if (!counts.total) return '';  // 持仓都不在 AI 分析中
  // 排序：按置信度
  decisions.sort(function(a,b){ return (b.confidence||0) - (a.confidence||0); });
  var top3 = decisions.slice(0, 3);
  var total = counts.total;
  return '<div class="ai-card" style="margin-top:14px">'+
    '<h4>🤖 AI 持仓洞察 <span class="ai-badge-glow">Zhipu GLM</span></h4>'+
    '<div class="ai-summary-row">'+
      '<div class="ai-stat"><div class="ai-stat-val sell">'+counts.sell+'</div><div class="ai-stat-lbl">🔥 建议减仓</div></div>'+
      '<div class="ai-stat"><div class="ai-stat-val hold">'+counts.hold+'</div><div class="ai-stat-lbl">📈 继续持有</div></div>'+
      '<div class="ai-stat"><div class="ai-stat-val wait">'+counts.wait+'</div><div class="ai-stat-lbl">👀 观望不动</div></div>'+
    '</div>'+
    '<div style="font-size:10px;color:var(--text3);margin-top:8px">AI 已分析 <b style="color:var(--text)">'+total+'</b> 件持仓物品</div>'+
    (top3.length ? '<div style="margin-top:10px"><div style="font-size:11px;font-weight:600;color:var(--text2);margin-bottom:6px">📋 高置信度建议</div>'+top3.map(function(d){
      var vc = d.verdict.includes('减仓')||d.verdict.includes('卖出')?'var(--rise)':d.verdict.includes('持有')||d.verdict.includes('加仓')?'var(--rise)':'var(--amber)';
      return '<div class="ai-signal">'+
        '<span style="color:'+vc+';font-weight:600;min-width:48px">'+d.verdict+'</span>'+
        '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+(d.name||'').substring(0,28)+'</span>'+
        '<span style="font-size:10px;color:var(--text3);min-width:40px;text-align:right">置信 '+d.confidence+'</span>'+
      '</div>';
    }).join('')+'</div>' : '') +
  '</div>';
}
// ── AI 市场研判生成 ──
function generateAIInsight() {
  var bar = document.getElementById('aiInsightBar');
  var text = document.getElementById('aiInsightText');
  if (!bar || !text) return;
  // 优先用后端 AI 生成的全量市场洞察（一次 API 调 8793 件摘要）
  fetch('ai_market_insight.json?v=' + Math.floor(Date.now()/900000)).then(function(r) {
    return r.ok ? r.json() : null;
  }).then(function(data) {
    if (data && data.insight) {
      text.innerHTML = data.insight;
      bar.style.display = '';
      var t = document.getElementById('aiInsightTime');
      if (t && data.date) t.textContent = '更新于' + data.date.slice(5);
      return;
    }
    // 回退：用持仓 AI 数据生成简易研判
    var ai = window._aiAnalysis || {};
    var counts = {sell:0, hold:0, wait:0};
    Object.keys(ai).forEach(function(k) {
      if (k.startsWith('_')) return;
      var v = typeof ai[k] === 'object' ? (ai[k].verdict||'') : ((ai[k].match(/操作建议[:：]\s*(\S+)/)||[])[1]||'');
      if (v.includes('减仓')||v.includes('卖出')) counts.sell++;
      else if (v.includes('持有')||v.includes('加仓')) counts.hold++;
      else counts.wait++;
    });
    if (counts.sell + counts.hold + counts.wait === 0) return;
    text.innerHTML = 'AI信号分布：<b style="color:var(--rise)">'+counts.sell+'减仓</b> · <b style="color:var(--fall)">'+counts.hold+'持有</b> · <b style="color:var(--amber)">'+counts.wait+'观望</b>';
    bar.style.display = '';
  }).catch(function(){});
}
// ── AI 推荐分析渲染 ──
function renderAIRecommendations() {
  var banner = document.getElementById('aiRecBanner');
  var picksEl = document.getElementById('aiRecPicks');
  var strategyEl = document.getElementById('aiRecStrategy');
  var dateEl = document.getElementById('aiRecDate');
  var sumEl = document.getElementById('aiRecSummary');
  var detailEl = document.getElementById('aiRecDetail');
  var moreEl = document.getElementById('aiRecMore');
  if (!banner || !picksEl) return;
  var now = Date.now();
  // ── 5 分钟内存缓存：翻页/排序/重绘不再重复请求 ──
  if (window._aiRecData && window._aiRecDataAt && (now - window._aiRecDataAt) < 300000) {
    renderAIRecBody(window._aiRecData);
    if (window._aiRecLessonsAt && (now - window._aiRecLessonsAt) < 300000) renderAILessons(window._aiRecLessons, window._aiRecData);
    else loadAILessons(window._aiRecData);
    return;
  }
  // Kronos 预测（实验性）：与 AI 精选并行加载，失败则静默不显示
  try { if (!FC.loaded) { loadForecast().then(function () { if (window._aiRecData) renderAIRecBody(window._aiRecData); }); } } catch (e) {}
  fetch('ai_recommendations.json?' + now).then(function(r) {
    return r.ok ? r.json() : null;
  }).then(function(data) {
    if (!data || !data.picks || !data.picks.length) {
      banner.style.display = 'none';
      return;
    }
    window._aiRecData = data;
    window._aiRecDataAt = Date.now();
    renderAIRecBody(data);
    if (window._aiRecLessonsAt && (Date.now() - window._aiRecLessonsAt) < 300000) renderAILessons(window._aiRecLessons, data);
    else loadAILessons(data);
  }).catch(function() {
    banner.style.display = 'none';
  });
}

// 追踪教训（评分权重反哺）——独立请求 + 缓存
// ── Kronos 14 日预测（实验性）──
// 只覆盖「推荐池前10 + AI 精选」的标的；由 update.py 在推荐板块更新时一并生成。
// 定位：辅助方向参考，不作买卖依据（Kronos 是金融 K 线基础模型迁移，域外外推）。
var FC = { map: {}, loaded: false };
function loadForecast() {
  var _now = Math.floor(Date.now() / 900000);
  return fetch('ai_forecast.json?v=' + _now)
    .then(function (r) { return r.ok ? r.json() : null; })
    .catch(function () { return null; })
    .then(function (d) {
      var m = {};
      if (d && d.items) {
        for (var i = 0; i < d.items.length; i++) {
          var it = d.items[i];
          if (it && it.hash_name) m[it.hash_name] = it;
          if (it && it.name) m['n:' + it.name] = it;
        }
      }
      FC.map = m; FC.meta = d; FC.loaded = true;
      return m;
    });
}
function fcOf(item) {
  if (!item) return null;
  var m = FC.map || {};
  return (item.hash_name && m[item.hash_name]) || m['n:' + item.name] || null;
}
// 预测徽章（AI 精选卡片用）
function fcChip(item) {
  var f = fcOf(item);
  if (!f || typeof f.change_pct !== 'number') return '';
  var up = f.change_pct >= 0;
  var cls = up ? 'fc-up' : 'fc-dn';
  var arrow = up ? '▲' : '▼';
  // 看跌时明确标注，避免被误读成「推荐评级把它判亏了」——Kronos 不进评分、不做否决
  var tag = up ? '' : ' · 看跌·仅参考';
  return '<span class="fc-chip ' + cls + '" title="Kronos 时序模型 ' + (FC.meta && FC.meta.days ? FC.meta.days : 14) +
    ' 日预测：' + f.current + ' → ' + f.forecast + '（' + (up ? '+' : '') + f.change_pct + '%）· 实验性，仅方向参考，不参与推荐评分">' +
    arrow + ' ' + (up ? '+' : '') + f.change_pct + '%／' + (FC.meta && FC.meta.days ? FC.meta.days : 14) + '日' + tag + '</span>';
}
// 展开行用的一行说明
function fcLine(item) {
  var f = fcOf(item);
  if (!f || typeof f.change_pct !== 'number') return '';
  var up = f.change_pct >= 0;
  return '<div class="bk-sub" style="margin-top:2px">Kronos ' + (FC.meta && FC.meta.days ? FC.meta.days : 14) +
    '日预测：<b style="color:var(--' + (up ? 'rise' : 'fall') + ')">' + (up ? '+' : '') + f.change_pct + '%</b>' +
    '（' + f.current + ' → ' + f.forecast + '）· <span style="opacity:.7">实验性，仅方向参考</span></div>';
}

function loadAILessons(data) {
  fetch('tracking_lessons.json?v=' + Date.now())
    .then(function(r) { return r.ok ? r.json() : null; })
    .catch(function() { return null; })
    .then(function(ls) {
      window._aiRecLessons = ls;
      window._aiRecLessonsAt = Date.now();
      renderAILessons(ls, data);
    });
}

// ── AI 精选主体渲染（纯渲染，不请求）──
function renderAIRecBody(data) {
  var banner = document.getElementById('aiRecBanner');
  var picksEl = document.getElementById('aiRecPicks');
  var strategyEl = document.getElementById('aiRecStrategy');
  var dateEl = document.getElementById('aiRecDate');
  var sumEl = document.getElementById('aiRecSummary');
  var detailEl = document.getElementById('aiRecDetail');
  var moreEl = document.getElementById('aiRecMore');
  if (!banner || !picksEl) return;
  var picks = data.picks.slice(0, 5);
  window._aiPicks = picks;
  if (dateEl) dateEl.textContent = data.date || '';
  if (sumEl) {
    if (data.summary) sumEl.innerHTML = '<b>📋 策略：</b>' + esc(data.summary);
    else if (data.strategy) sumEl.innerHTML = '<b>💡 策略：</b>' + esc(data.strategy);
    else sumEl.innerHTML = '';
    sumEl.title = [data.summary, data.strategy].filter(Boolean).join(' ｜ ');
  }
  banner.style.display = '';

  var rankIcons = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣'];
  picksEl.innerHTML = picks.map(function(p, i) {
    var se = p.sentiment || '';
    var cls = AI_SENT_CLS[se] || 's-neutral';
    return '<div class="aip' + (i === 0 ? ' sel' : '') + '" data-i="' + i + '" role="button" tabindex="0" title="' + esc(p.name || '') + '">' +
      '<div class="aip-head"><span class="aip-rk">' + (rankIcons[i] || ('#' + (i + 1))) + '</span>' +
        '<span class="aip-nm">' + esc(p.name || '--') + '</span></div>' +
      '<div class="aip-prow"><span class="aip-price">' + (p.price !== undefined && p.price !== '' ? '¥' + esc(String(p.price)) : '—') + '</span>' +
        (se ? '<span class="aip-sent ' + cls + '">' + esc(se) + '</span>' : '') +
        (typeof fcChip === 'function' ? fcChip(p) : '') + '</div>' +
      '<div class="aip-sigs">' + aiPickSignals(p) + '</div>' +
    '</div>';
  }).join('');
  picksEl.querySelectorAll('.aip').forEach(function(el) {
    var idx = parseInt(el.getAttribute('data-i'), 10);
    el.addEventListener('click', function() { window.aiSelectPick(idx); });
    el.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); window.aiSelectPick(idx); }
    });
  });
  window.aiSelectPick(0);

  if (moreEl && !moreEl._bound) {
    moreEl._bound = 1;
    moreEl.addEventListener('click', function() {
      if (!detailEl) return;
      var show = detailEl.style.display !== 'none';
      detailEl.style.display = show ? 'none' : '';
      moreEl.textContent = show ? '展开详情 ▾' : '收起详情 ▴';
    });
  }

  // 底部元信息：策略 / 推理过程 / 自检 / 教训（占位）
  var foot = [];
  if (data.strategy) foot.push('<span>💡 ' + esc(data.strategy) + '</span>');
  if (data.reasoning) {
    foot.push('<details><summary>🧠 推理过程</summary><div style="margin-top:4px;padding:6px 8px;background:rgba(96,165,250,.04);border-radius:6px;line-height:1.6;color:var(--text2)">' + esc(data.reasoning) + '</div></details>');
  }
  if (data.self_critique) foot.push('<span>⚠️ 自检：<b>' + esc(data.self_critique) + '</b></span>');
  foot.push('<div id="aiRecLessons" style="width:100%"></div>');
  strategyEl.innerHTML = foot.join('');
  if (data.scoring_weights) renderAILessons(null, data);
}

// ── 评分权重 / 教训反哺（原逻辑保留）──
function renderAILessons(lessons, data) {
  var box = document.getElementById('aiRecLessons');
  if (!box) return;
  var latest = (lessons && lessons.analysis_history && lessons.analysis_history.length)
    ? lessons.analysis_history[lessons.analysis_history.length - 1] : null;
  var sf = latest ? latest.scoring_feedback || {} : {};
  var lessonsList = lessons ? lessons.lessons || [] : [];
  var sw = data ? data.scoring_weights : null;
  var adjHtml = '';
  if (sw || sf.eco_weight_advice || sf.buff_weight_advice) {
    adjHtml += '<div style="display:flex;gap:10px;align-items:center;font-size:10px;margin-bottom:6px;flex-wrap:wrap">';
    adjHtml += '<span style="color:var(--text3)">📊 评分权重(AI调整):</span>';
    var ecoV = sw ? sw.eco : (sf.eco_weight_advice || '不变');
    var buffV = sw ? sw.buff : (sf.buff_weight_advice || '不变');
    adjHtml += '<span style="color:' + (String(ecoV).indexOf('-') >= 0 ? 'var(--fall)' : 'var(--rise)') + '">ECO ' + (ecoV > 0 ? '+' : '') + ecoV + '%</span>';
    adjHtml += '<span style="color:' + (String(buffV).indexOf('+') >= 0 ? 'var(--fall)' : 'var(--rise)') + '">BUFF ' + (buffV > 0 ? '+' : '') + buffV + '%</span>';
    adjHtml += '<span style="color:var(--text3)">| 溢价: ' + esc(sf.premium_threshold_advice || '?') + '</span>';
    adjHtml += '</div>';
  }
  if (lessonsList.length) {
    adjHtml += '<div style="font-size:9px;color:var(--text3);line-height:1.5">';
    adjHtml += '🧠 ' + lessonsList.slice(0, 2).map(function(l) { return esc(l.lesson).slice(0, 35) + (l.confirmed >= 3 ? ' ✓' : ''); }).join(' · ');
    adjHtml += '</div>';
  }
  if (latest && latest.reason_analysis) {
    var ra = latest.reason_analysis;
    if (ra.right_reasons || ra.wrong_reasons) {
      adjHtml += '<div style="font-size:9px;color:var(--text2);line-height:1.5;margin-top:4px">';
      adjHtml += '💬 理由优化: ';
      if (ra.right_reasons) adjHtml += '<span style="color:var(--fall)">✅' + esc(ra.right_reasons).slice(0, 40) + '</span> ';
      if (ra.wrong_reasons) adjHtml += '<span style="color:var(--rise)">❌' + esc(ra.wrong_reasons).slice(0, 40) + '</span>';
      adjHtml += '</div>';
    }
  }
  box.innerHTML = adjHtml
    ? '<div style="margin-top:8px;padding:8px 10px;background:rgba(251,191,36,.06);border-radius:8px;border-left:2px solid rgba(251,191,36,.3)">' + adjHtml + '</div>'
    : '';
}

// ── AI 研判色阶 + 信号标签（沿用原口径）──
var AI_SENT_CLS = { '强烈看多': 's-strong', '看多': 's-bull', '中性偏多': 's-neutral', '中性': 's-neutral', '中性偏空': 's-bear', '看空': 's-bear', '强烈看空': 's-sbear' };
function aiPickSignals(p) {
  var r = p.reason || '';
  var signals = [];
  if (Array.isArray(p.trend_signals) && p.trend_signals.length) {
    signals = p.trend_signals.slice(0);
  } else {
    if (/供不应求|供<求|卖方市场/.test(r)) signals.push('+卖方市场');
    if (/供大于求|供>求|买方市场/.test(r)) signals.push('-买方市场');
    var pm = r.match(/溢价(\d+[\d.]*%)/);
    if (pm) { var pv = parseFloat(pm[1]); signals.push((pv < 6 ? '+' : '=') + '溢价' + pm[1]); }
    if (/流动性优良/.test(r)) signals.push('=流动性优良');
    if (/稀缺|仅\d+件/.test(r)) signals.push('+稀缺品');
  }
  if (!signals.length) signals.push('=AI精选');
  return signals.slice(0, 4).map(function(s) {
    var pre = s.charAt(0);
    var cls = pre === '+' ? 'p' : (pre === '-' ? 'n' : 'e');
    var icon = pre === '+' ? '↑' : (pre === '-' ? '↓' : '—');
    var label = (pre === '+' || pre === '-' || pre === '=') ? s.slice(1) : s;
    return '<span class="sg ' + cls + '">' + icon + ' ' + esc(label) + '</span>';
  }).join('');
}
// 选中 AI 精选条目 → 下方展开该条全字段
window.aiSelectPick = function(i) {
  var picks = window._aiPicks || [];
  var p = picks[i];
  var detailEl = document.getElementById('aiRecDetail');
  if (!detailEl) return;
  document.querySelectorAll('#aiRecPicks .aip').forEach(function(el) {
    el.classList.toggle('sel', parseInt(el.getAttribute('data-i'), 10) === i);
  });
  if (!p) { detailEl.innerHTML = ''; return; }
  var left = [];
  if (p.price_zone) left.push('<div class="ai-row" style="margin-bottom:8px"><i>🎯 推荐入手价格区间</i><span class="txt">' + esc(p.price_zone) + '</span></div>');
  if (p.platform_advice) left.push('<div class="ai-row"><i>🏪 平台建议</i><span class="txt">' + esc(p.platform_advice) + '</span></div>');
  if (!left.length) left.push('<div class="ai-row"><span class="txt">暂无补充信息</span></div>');
  var mid = '<div class="ai-row"><i>📊 买入理由</i><span class="txt">' + esc(p.reason || '暂无') + '</span></div>';
  var right = [];
  if (p.risk) right.push('<div class="ai-row warn" style="margin-bottom:8px"><i style="color:#f87171">⚠️ 风险评估</i>' + esc(p.risk) + '</div>');
  if (p.operation) right.push('<div class="ai-row plan"><i style="color:#86efac">🎯 操作计划</i>' + esc(p.operation) + '</div>');
  if (!right.length) right.push('<div class="ai-row"><span class="txt">无风险/操作提示</span></div>');
  var icons = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣'];
  detailEl.innerHTML = '<div class="dh"><span>▸ 展开详情</span><b>' + (icons[i] || '') + ' ' + esc(p.name || '') + '</b>' +
    (p.sentiment ? '<span class="rt-dim">' + esc(p.sentiment) + '</span>' : '') +
    (p.price !== undefined && p.price !== '' ? '<span class="rt-dim">¥' + esc(String(p.price)) + '</span>' : '') +
    (typeof fcChip === 'function' ? fcChip(p) : '') + '</div>' +
    (typeof fcLine === 'function' ? fcLine(p) : '') +
    '<div class="ai-grid"><div>' + left.join('') + '</div><div>' + mid + '</div><div>' + right.join('') + '</div></div>';
};

// ── 填充表格 AI 徽章 ──
function populateAIBadges() {
  var badges = document.querySelectorAll('.ai-badge-inline');
  if (!badges.length) return;
  var H = window.H || [];
  badges.forEach(function(el) {
    var idx = parseInt(el.id.replace('aib-',''));
    if (isNaN(idx) || !H[idx]) return;
    var name = H[idx].n || H[idx].mh || '';  // AI key 用中文名
    if (name) el.innerHTML = window.aiBadgeHTML(name);
  });
}
// AI 数据加载完成后刷新徽章和面板
document.addEventListener('ai-loaded', function() {
  populateAIBadges();
  // AI 徽章更新
  var aiBadge = document.getElementById('aiBadge');
  if (aiBadge) {
    var ai = window._aiAnalysis || {};
    var count = Object.keys(ai).filter(function(k){return !k.startsWith('_');}).length;
    // 2026-09-14 顶部「智谱AI · N件」徽章已撤下（信息噪音；页面底部已有 AI 品牌说明）
    aiBadge.innerHTML = '<span class="ai-dot"></span>智谱AI · ' + count + '件';
    aiBadge.style.display = 'none';
    aiBadge.title = '智谱 GLM-4-Flash · 已分析 ' + count + ' 件持仓物品';
  }
  // 显示页脚
  var af = document.getElementById('aiFooter');
  if (af) af.style.display = '';
  // AI市场研判
  generateAIInsight();
  // 触发面板重绘
  if (window.H && window.H.length) {
    var grid = document.getElementById('scanGrid');
    if (grid) { renderScan(); }
  }
});
function setupNewsTabs() {
  var newsTabs = $('newsTabs');
  if (!newsTabs || newsTabs._bound) return;
  newsTabs._bound = 1;
  newsTabs.onclick = function(e) {
    var btn = e.target.closest('[data-ntab]');
    if (!btn) return;
    this.querySelectorAll('.tab').forEach(function(b) { b.classList.remove('on'); });
    btn.classList.add('on');
    renderNewsTab(btn.dataset.ntab);
  };
}

function setupExportBtn() {
  var exportBtn = document.getElementById('exportBtn');
  if (exportBtn) {
    exportBtn.onclick = function() {
      const blob = new Blob([JSON.stringify(costOverrides, null, 2)], {type:'application/json'});
      const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'cost-overrides.json'; a.click();
    };
  }
}

function updateKPI() {
  if (!H.length) return;
  const tc = H.reduce((s,h) => s + (isNaN(h.c)?0:h.c), 0);
  const tp = H.reduce((s,h) => s + (isNaN(h.p)?0:h.p), 0);
  const tpct = tc > 0 ? (tp - tc) / tc * 100 : 0;
  const isUp = tp >= tc;
  
  // 更新持仓汇总区域的三个指标
  const valueEl = document.getElementById('totalValueHeader');
  const countEl = document.getElementById('totalCountHeader');
  const pnlEl = document.getElementById('totalPnlHeader');
  const pnlPctEl = document.getElementById('totalPnlPctHeader');
  const costEl = document.getElementById('totalCostHeader');
  
  if (valueEl) {
    valueEl.textContent = '¥' + tp.toLocaleString();
    // 总价值用等宽大字，不按涨跌染色（涨跌由「总盈亏」卡承担）
    valueEl.className = 'k-value';
    valueEl.style.color = '';
  }
  if (countEl) countEl.textContent = H.length + ' 件';
  
  if (pnlEl) {
    pnlEl.textContent = (isUp ? '+' : '') + '¥' + ((tp||0) - (tc||0)).toLocaleString();
    pnlEl.className = 'k-value ' + (isUp ? 'rise' : 'fall');
    pnlEl.style.color = isUp ? 'var(--rise)' : 'var(--fall)';
  }
  if (pnlPctEl) {
    var winners = H.filter(function(h){return h.p > h.c;}).length;
    pnlPctEl.textContent = (isUp ? '+' : '') + tpct.toFixed(2) + '% · ' + Math.round(winners / H.length * 100) + '% 胜率';
  }
  var sorted = H.slice().sort(function(a,b){return b.pnlPct - a.pnlPct;});
  var best = sorted[0], worst = sorted[H.length-1];
  var bestEl = document.getElementById('bestPerformer');
  var worstEl = document.getElementById('worstPerformer');
  if (bestEl && best) {
    bestEl.textContent = best.n + ' ' + (best.pnlPct>=0?'+':'') + best.pnlPct.toFixed(1) + '%';
    bestEl.style.color = best.pnlPct >= 0 ? 'var(--fall)' : 'var(--rise)';
  }
  if (worstEl && worst) {
    worstEl.textContent = worst.n + ' ' + (worst.pnlPct>=0?'+':'') + worst.pnlPct.toFixed(1) + '%';
    worstEl.style.color = worst.pnlPct >= 0 ? 'var(--fall)' : 'var(--rise)';
  }
  
  if (costEl) costEl.textContent = '¥' + tc.toLocaleString();
  // 综合信号灯
  var pnlPct2 = tc>0?(tp-tc)/tc*100:0;
  var winRate2 = H.filter(function(h){return h.p>h.c;}).length/Math.max(1,H.length)*100;
  var avgPnl = H.length?tp/Math.max(1,H.length):0;
  var iconEl = document.getElementById('signalIcon');
  var textEl = document.getElementById('signalText');
  var subEl = document.getElementById('signalSub');
  if (iconEl && textEl) {
    if (pnlPct2 > 10 && winRate2 > 60) {
      iconEl.textContent = '▲'; textEl.textContent = '强势'; textEl.style.color = '#4ade80';
      if(subEl) subEl.textContent = '盈利率' + winRate2.toFixed(0) + '%';
    } else if (pnlPct2 > 0 && winRate2 > 40) {
      iconEl.textContent = '🟡'; textEl.textContent = '观望'; textEl.style.color = '#fbbf24';
      if(subEl) subEl.textContent = (pnlPct2>0?'+':'') + pnlPct2.toFixed(1) + '%';
    } else if (pnlPct2 < -5) {
      iconEl.textContent = '▼'; textEl.textContent = '注意'; textEl.style.color = '#f87171';
      if(subEl) subEl.textContent = (pnlPct2>0?'+':'') + pnlPct2.toFixed(1) + '%';
    } else {
      iconEl.textContent = '⚪'; textEl.textContent = '平稳'; textEl.style.color = '#94a3b8';
      if(subEl) subEl.textContent = H.length + '持仓 · 均¥'+avgPnl.toFixed(0);
    }
  }
}

function buildTabs() {
  // Build category tabs dynamically from actual data
  const catCounts = {};
  H.forEach(h => { catCounts[h.t] = (catCounts[h.t] || 0) + 1; });

  const cats = [{key:'all', label:'全部', count:H.length}];
  // Show categories that exist in data, in display order
  ['weapon','gloves','knives','sticker','music','other'].forEach(key => {
    if (catCounts[key]) cats.push({key, label:CAT_LABELS[key], count:catCounts[key]});
  });

  let html = '';
  cats.forEach(c => {
    html += '<button class="tab ' + (c.key === 'all' ? 'on' : '') + '" data-cat="' + c.key + '">' + c.label + ' ' + c.count + '</button>';
  });
  if (DOM.tabBar) DOM.tabBar.innerHTML = html;
}

// ═══════════════ TABLE RENDER ═══════════════
function getFiltered() {
  const key = curCat + '|' + sortCol + '|' + sortDir + '|' + PAGE_SIZE + '|' + searchQuery;
  if (filteredCache && filterCacheKey === key) return filteredCache;
  let raw = curCat === 'all' ? H : H.filter(h => h.t === curCat);
  raw = raw.filter(h => !isBS(h));
  if (searchQuery) {
    const q = searchQuery.trim().toLowerCase();
    raw = raw.filter(h => h.n.toLowerCase().includes(q) || (WEAR_MAP[h.w]||'').toLowerCase().includes(q));
  }
  filteredCache = raw.sort((a,b) => {
    // Map column names to data fields
    const fieldMap = {ecoP:'p', multiP:'buff_sell'};
    const sortField = fieldMap[sortCol] || sortCol;
    const av = a[sortField] || 0, bv = b[sortField] || 0;
    if (typeof av === 'string') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
    return sortDir === 'asc' ? av - bv : bv - av;
  });
  filterCacheKey = key;
  return filteredCache;
}

function invalidateCache() { filteredCache = null; filterCacheKey = ''; }

// ══════════ 主导航：真标签页视图切换 ══════════
// 与旧的「滚动锚点」不同：点击导航只显示对应的一个面板，其余隐藏，彻底消除长页面堆叠。
var _VIEW_IDS = ['recPanel', 'holdingsPanel', 'scanPanel', 'newsSection', 'changelogPanel'];

window.switchView = function(id) {
  if (_VIEW_IDS.indexOf(id) < 0) id = 'recPanel';
  _VIEW_IDS.forEach(function(vid) {
    var el = document.getElementById(vid);
    if (!el) return;
    el.style.display = (vid === id) ? '' : 'none';
  });
  // 同步导航高亮
  var btns = document.querySelectorAll('.nav-btn[data-view]');
  for (var i = 0; i < btns.length; i++) {
    btns[i].classList.toggle('on', btns[i].getAttribute('data-view') === id);
  }
  // 记录到 URL，便于刷新后停在原视图
  try { history.replaceState(null, '', '#' + id); } catch (e) {}
  window.scrollTo({ top: 0, behavior: 'smooth' });
  // 切到推荐/持仓时触发一次重绘（尺寸变化后图表需重算）
  if (id === 'recPanel' && typeof renderAllRecs === 'function') { try { renderAllRecs(); } catch (e) {} }
  if (id === 'holdingsPanel' && typeof render === 'function') { try { render(); } catch (e) {} }
};

// 兼容旧调用（子页链接等仍可能用 scrollToPanel）
window.scrollToPanel = function(id) { window.switchView(id); };

// 读 URL hash 决定初始视图；无 hash 时默认「推荐」
window.initView = function() {
  var h = (location.hash || '').replace('#', '');
  window.switchView(_VIEW_IDS.indexOf(h) >= 0 ? h : 'recPanel');
};

function render() {
  filterHidden();
  const items = H || [];
  // 空状态显示占位
  var hp = document.getElementById('holdingsPanel');
  if (hp) {
    var emptyEl = document.getElementById('holdingsEmpty');
    if (items.length === 0) {
      if (!emptyEl) {
        var div = document.createElement('div');
        div.id = 'holdingsEmpty';
        div.style.cssText = 'padding:60px 20px;text-align:center;color:var(--text3);font-size:13px';
        div.innerHTML = (getMyKey() ? '还没有持仓数据，点击"导入库存"开始' : '请先 <b style="color:var(--blue);cursor:pointer" onclick="document.getElementById(\'authModal\').style.display=\'flex\'">登录</b> 查看持仓');
        hp.appendChild(div);
      }
    } else if (emptyEl) {
      emptyEl.remove();
    }
  }
  if (DOM.countBadge) DOM.countBadge.textContent = items.length;
  const totalPages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  if (curPage > totalPages) curPage = totalPages;
  const start = (curPage - 1) * PAGE_SIZE;
  const pageItems = items.slice(start, start + PAGE_SIZE);

  const frag = document.createDocumentFragment();
  pageItems.forEach((h, idx) => {
    const realIdx = start + idx;
    // 防止 NaN 污染显示
    if(isNaN(h.p)) h.p = 0;
    if(isNaN(h.c)) h.c = 0;
    if(isNaN(h.pnl)) h.pnl = 0;
    if(isNaN(h.pnlPct)) h.pnlPct = 0;
    const isProfit = h.pnl >= 0;
    const pnlCls = isProfit ? 'clr-rise' : 'clr-fall';
    const rowCls = isProfit ? 'pnl-profit' : 'pnl-loss';
    const key = overrideKey(h.n, h.w);
    const edited = costOverrides[key] !== undefined;
    // P&L 进度条：按比例显示盈亏幅度（上限 30%，下限 -20%）
    const pnlPctClamped = Math.max(-20, Math.min(30, h.pnlPct));
    const barPct = Math.abs(pnlPctClamped) / 30 * 100;
    const barCls = isProfit ? 'profit' : 'loss';
    const barIcon = isProfit ? '🔼' : '🔽';
    const tr = document.createElement('tr');
    tr.className = rowCls + ' hold-row';
    tr.dataset.idx = realIdx;
    tr.onclick = function(e) {
      if (e.target.closest('button') || e.target.closest('.cost-val')) return;
      var ar = this._analysisRow || this.nextElementSibling;
      if (ar && ar.classList.contains('row-analysis')) {
        if (!ar._loaded) {
          ar._loaded = true;
          ar.firstChild.innerHTML = buildItemAnalysisHTML(this._item);
        }
        ar.classList.toggle('open');
      }
    };
    tr.innerHTML =
      '<td><div class="item-name"><button class="row-star" data-gid="'+h.gid+'">'+(h.gid&&starred[h.gid]?'★':'☆')+'</button>'+esc(cnName(h.n))+'<span class="ai-badge-inline" id="aib-'+realIdx+'"></span> <span class="chart-btn" onclick="event.stopPropagation();showPriceChart(\''+esc(h.n).replace(/'/g,"\\'")+'\', '+(h.buff_sell || h.eco_price || h.yyyp_sell || 0)+')" title="查看价格走势">📈</span></div></td>'+
      '<td>'+(h.w ? '<span class="wear-tag">'+wearCN(h.w)+'</span>' : '--')+'</td>'+
      '<td class="text-r mono"><span class="cost-val" data-idx="'+realIdx+'" title="点击编辑">¥'+h.c.toFixed(2)+'</span><span class="edit-cost" data-idx="'+realIdx+'"></span>'+(edited?'<span class="cost-edited">已改</span>':'')+'</td>'+
      '<td class="text-r mono">'+(h.eco_price > 0 ? '¥'+h.eco_price.toFixed(2) : '<span class="text-muted">--</span>')+'</td>'+
      '<td class="text-r mono">'+(h.buff_sell > 0 ? '¥'+h.buff_sell.toFixed(2)+'<sup style="font-size:8px;color:var(--rise);margin-left:1px">实时</sup>' : '<span class="text-muted">--</span>')+'<br><span style="font-size:10px;color:var(--amber)">'+(h.yyyp_sell > 0 ? '悠悠¥'+h.yyyp_sell.toFixed(2)+'<sup style="font-size:8px;color:var(--rise);margin-left:1px">实时</sup>' : '')+'</span></td>'+
      '<td class="text-r mono" style="font-size:11px">'+(h.rate_1 !== undefined && !isNaN(h.rate_1) ? '<span class="'+(h.rate_1>=0?'clr-rise':'clr-fall')+'">'+(h.rate_1>=0?'+':'')+h.rate_1.toFixed(1)+'%</span>' : '--')+' · '+(h.rate_7 !== undefined && !isNaN(h.rate_7) ? '<span class="'+(h.rate_7>=0?'clr-rise':'clr-fall')+'">'+(h.rate_7>=0?'+':'')+h.rate_7.toFixed(1)+'%</span>' : '--')+'</td>'+
      '<td class="text-r"><span class="'+pnlCls+'" style="font-weight:700">'+(h.pnl>=0?'+':'')+'¥'+(isNaN(h.pnl)?'0.00':h.pnl.toFixed(2))+'</span></td>'+
      '<td class="text-r"><div class="pnl-bar-wrap"><span class="'+pnlCls+'" style="font-weight:600">'+(h.pnlPct>=0?'+':'')+h.pnlPct.toFixed(1)+'%</span><span class="pnl-bar-icon">'+barIcon+'</span><div class="pnl-bar-track"><div class="pnl-bar-fill '+barCls+'" style="width:'+barPct.toFixed(0)+'%"></div></div></div></td>'+
      '<td class="text-r"><button class="sell-btn" data-name="'+esc(h.n)+'" data-wear="'+(h.w||'')+'" title="卖出此饰品">卖出</button></td>'+
      '</tr>';
    frag.appendChild(tr);
    // 分析行懒加载（点击时才渲染）
    var analysisRow = document.createElement('tr');
    analysisRow.className = 'row-analysis';
    analysisRow.innerHTML = '<td colspan="9"></td>';
    frag.appendChild(analysisRow);
    tr._analysisRow = analysisRow;
    tr._item = h;
  });
  if (DOM.tbody) { DOM.tbody.innerHTML = ''; DOM.tbody.appendChild(frag); }
  // 填充 AI 徽章
  if (window._aiAnalysis && Object.keys(window._aiAnalysis).length) populateAIBadges();

  if (totalPages <= 1) { if (DOM.pager) DOM.pager.innerHTML = ''; if (DOM.pageJump) DOM.pageJump.style.display = 'none'; return; }
  if (DOM.pager) DOM.pager.innerHTML = '<button class="pgr-btn" id="pgPrev" '+(curPage<=1?'disabled':'')+'>上一页</button><span class="pgr-info">'+curPage+' / '+totalPages+' 页 · '+items.length+' 条</span><button class="pgr-btn" id="pgNext" '+(curPage>=totalPages?'disabled':'')+'>下一页</button>';
  if (DOM.pageJump) DOM.pageJump.style.display = 'flex';
  if (DOM.pageNumInput) { DOM.pageNumInput.max = totalPages; DOM.pageNumInput.value = ''; }
  if (DOM.pager) DOM.pager.onclick = e => {
    const btn = e.target.closest('.pgr-btn');
    if (!btn || btn.disabled) return;
    if (btn.id === 'pgPrev') { curPage = Math.max(1, curPage - 1); render(); }
    if (btn.id === 'pgNext') { curPage = Math.min(totalPages, curPage + 1); render(); }
  };

// ── Render 表格 ──
}
window.render = render;

// ═══════════════ EVENT HANDLERS ═══════════════
// tabBar click - null check with document-level fallback
if (DOM.tabBar) {
  DOM.tabBar.onclick = e => {
    const btn = e.target.closest('.tab');
    if (!btn) return;
    DOM.tabBar.querySelectorAll('.tab').forEach(b => b.classList.remove('on'));
    btn.classList.add('on');
    curCat = btn.dataset.cat;
    curPage = 1;
    invalidateCache();
    render();
  };
} else {
  document.addEventListener('click', e => {
    const btn = e.target.closest('#tabBar .tab');
    if (!btn) return;
    document.querySelectorAll('#tabBar .tab').forEach(b => b.classList.remove('on'));
    btn.classList.add('on');
    curCat = btn.dataset.cat;
    curPage = 1;
    invalidateCache();
    render();
  });
}

document.querySelectorAll('thead th').forEach(th => {
  th.onclick = () => {
    const col = th.dataset.col;
    if (!col) return;
    if (sortCol === col) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
    else { sortCol = col; sortDir = 'desc'; }
    document.querySelectorAll('thead th').forEach(h => h.className = '');
    th.className = sortDir === 'asc' ? 'sort-asc' : 'sort-desc';
    invalidateCache();
    render();
  };
});
// Set default sort indicator on 6th column (盈亏%)
const ths = document.querySelectorAll('thead th');
if (ths[5]) ths[5].className = 'sort-desc';

// 搜索框
let searchTimer = null;
if (DOM.searchInput) {
  DOM.searchInput.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      searchQuery = DOM.searchInput.value;
      curPage = 1;
      invalidateCache();
      render();
    }, 200);
  });
}

// 排序下拉框
if (DOM.sortOrder) {
  DOM.sortOrder.addEventListener('change', () => {
    const v = DOM.sortOrder.value;
    sortCol = v;
    sortDir = 'desc';
    curPage = 1;
    invalidateCache();
    render();
  });
}

// 页码跳转
if (DOM.pageSizeSel) {
  DOM.pageSizeSel.addEventListener('change', function() {
    PAGE_SIZE = parseInt(this.value) || 50;
    curPage = 1;
    invalidateCache();
    render();
  });
}


if (DOM.pageGoBtn) {
  DOM.pageGoBtn.onclick = function() {
    const n = parseInt(DOM.pageNumInput.value);
    const totalPages = Math.max(1, Math.ceil(getFiltered().length / PAGE_SIZE));
    if (!isNaN(n) && n >= 1 && n <= totalPages) {
      curPage = n;
      render();
    }
  };
}
if (DOM.pageNumInput) {
  DOM.pageNumInput.addEventListener('keydown', e => { if (e.key === 'Enter') DOM.pageGoBtn && DOM.pageGoBtn.click(); });
}
if (DOM.searchInput) {
  DOM.searchInput.addEventListener('keydown', e => { if (e.key === 'Enter') { curPage=1; invalidateCache(); render(); } });
}
if (DOM.tbody) {
  DOM.tbody.onclick = function(e) {
  const starBtn = e.target.closest('.row-star');
  if (starBtn) { const gid = +starBtn.dataset.gid; if (gid) toggleStar(gid); return; }

  const editBtn = e.target.closest('.cost-val, .edit-cost');
  if (!editBtn) return;
  const idx = +editBtn.dataset.idx;
  const item = H[idx];
  const td = editBtn.closest('td');
  if (!td) return;
  td.innerHTML = '<span class="cost-edit-group"><input class="cost-input" type="number" step="0.01" value="'+item.c.toFixed(2)+'"><button class="cost-save-btn" title="保存">✓</button></span><button class="cost-cancel-btn" title="取消">✕</button><span class="cost-edit-preview"></span>';
  const inp = td.querySelector('.cost-input');
  const saveBtn = td.querySelector('.cost-save-btn');
  const cancelBtn = td.querySelector('.cost-cancel-btn');
  const preview = td.querySelector('.cost-edit-preview');
  inp.focus(); inp.select();
  function updatePreview() {
    var v = parseFloat(inp.value);
    if (!isNaN(v) && v >= 0) {
      var newPnl = item.p - v;
      var newPct = v > 0 ? (item.p - v) / v * 100 : 0;
      preview.textContent = (newPnl >= 0 ? '+' : '') + newPnl.toFixed(0) + ' (' + (newPct >= 0 ? '+' : '') + newPct.toFixed(1) + '%)';
      preview.style.color = newPnl >= 0 ? 'var(--rise)' : 'var(--fall)';
    } else {
      preview.textContent = '';
    }
  }
  inp.addEventListener('input', updatePreview);
  updatePreview();
  function save() {
    const val = parseFloat(inp.value);
    if (!isNaN(val) && val >= 0) {
      item.c = val;
      item.pnl = item.p - val;
      item.pnlPct = val > 0 ? (item.p - val) / val * 100 : 0;
      costOverrides[overrideKey(item.n, item.w)] = val;
      saveOverridesDebounced();
    }
    invalidateCache(); updateKPI(); render();
  }
  saveBtn.onclick = save;
  cancelBtn.onclick = function() { invalidateCache(); render(); };
  inp.onblur = function() { setTimeout(save, 150); };
  inp.onkeydown = function(e) { if (e.key === 'Enter') save(); if (e.key === 'Escape') { invalidateCache(); render(); } };
};
}

function exportCSV() {
  var rows=[['名称','成本','当前价','盈亏%','类型','品名']];
  H.forEach(function(s){
    var cost=getCost(s.name,true);
    var pnlPct=cost>0?((s.price-cost)/cost*100):0;
    rows.push([s.name,cost.toFixed(2),s.price.toFixed(2),pnlPct.toFixed(1)+'%',s.listed?'在售':'持仓',s.type||'']);
  });
  var csv=rows.map(function(r){return r.map(function(v){var s=String(v);return s.includes(',')||s.includes('"')?'"'+s.replace(/"/g,'""')+'"':s;}).join(',');}).join('\n');
  var blob=new Blob(['\uFEFF'+csv],{type:'text/csv;charset=utf-8'});
  var a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download='cs2_portfolio_'+new Date().toISOString().slice(0,10)+'.csv';a.click();
  URL.revokeObjectURL(a.href);
}


// ═══════════════ REFRESH BUTTON ═══════════════
// 状态跟踪
let isUpdating = false;
let prevSnapshot = null; // 刷新前的数据快照

// cost-overrides 写盘防抖
let _saveOverridesTimer = null;
function saveOverridesDebounced() {
  clearTimeout(_saveOverridesTimer);
  _saveOverridesTimer = setTimeout(saveOverrides, 300);
}

// 数据快照（用于对比变更）
function takeSnapshot() {
  const snap = {
    holdings: H ? H.map(h => ({n: h.n, w: h.w, c: h.c, p: h.p})) : [],
    recs: {}
  };
  if (recData) {
    snap.recs.all = (recData.all || []).map(r => r.name);
  }
  return snap;
}

// 对比新旧数据，生成变更列表
function diffSnapshot(oldSnap, newSnap) {
  if (!oldSnap) return null;
  const changes = {prices: [], alerts: [], recs: []};

  // 1. 持仓价格变动
  const oldMap = {};
  oldSnap.holdings.forEach(h => { oldMap[h.n + '|' + h.w] = h.p; });
  newSnap.holdings.forEach(h => {
    const oldP = oldMap[h.n + '|' + h.w];
    if (oldP !== undefined && Math.abs(h.p - oldP) > 0.01) {
      changes.prices.push({name: h.n, wear: h.w, oldPrice: oldP, newPrice: h.p, pct: oldP > 0 ? (h.p - oldP) / oldP * 100 : 0});
    }
  });
  // 按变动绝对值排序
  changes.prices.sort((a, b) => Math.abs(b.pct) - Math.abs(a.pct));


  // 3. 推荐变动
  for (const k of ['all']) {
    const oldSet = new Set(oldSnap.recs[k] || []);
    const newSet = new Set(newSnap.recs[k] || []);
    const added = [...newSet].filter(n => !oldSet.has(n));
    const removed = [...oldSet].filter(n => !newSet.has(n));
    if (added.length) changes.recs.push({type: 'added', cat: k, items: added});
    if (removed.length) changes.recs.push({type: 'removed', cat: k, items: removed});
  }

  return changes;
}

// 渲染变更日志
function renderChangelog(changes) {
  const panel = $('changelogPanel');
  const content = $('changelogContent');
  const navBtn = $('changelogNavBtn');
  // 注意：面板显隐统一由 switchView() 管理，此处只控制「变动」导航按钮是否出现，
  // 否则会把 display 强制成 block，破坏标签页切换。
  if (!changes || (!changes.prices.length && !changes.recs.length)) {
    if (navBtn) navBtn.style.display = 'none';
    // 若当前正停在「变动」视图且已无内容，退回推荐
    if (panel && panel.style.display !== 'none' && typeof switchView === 'function') switchView('recPanel');
    return;
  }
  if (navBtn) navBtn.style.display = '';

  let html = '';

  // 价格变动
  if (changes.prices.length) {
    html += '<div class="cl-section"><div class="cl-section-title">💰 持仓价格变动 <span class="cl-count">' + changes.prices.length + '</span></div>';
    changes.prices.slice(0, 20).forEach(c => {
      const cls = c.pct > 0 ? 'up' : 'dn';
      const sign = c.pct > 0 ? '+' : '';
      html += '<div class="cl-item"><span class="cl-tag price">价格</span><span class="cl-name">' + esc(c.name) + (c.wear ? ' <span class="wear-tag">' + c.wear + '</span>' : '') + '</span><span class="cl-old">¥' + c.oldPrice.toFixed(2) + '</span><span class="cl-new ' + cls + '">¥' + c.newPrice.toFixed(2) + ' ' + sign + c.pct.toFixed(1) + '%</span></div>';
    });
    if (changes.prices.length > 20) html += '<div class="cl-empty">...还有 ' + (changes.prices.length - 20) + ' 项变动</div>';
    html += '</div>';
  }

  // 推荐变动
  if (changes.recs.length) {
    html += '<div class="cl-section"><div class="cl-section-title">🎯 推荐变化 <span class="cl-count">' + changes.recs.length + '</span></div>';
    changes.recs.forEach(r => {
      const label = REC_CAT_LABELS[r.cat] || r.cat;
      r.items.slice(0, 5).forEach(name => {
        const tag = r.type === 'added' ? 'new' : 'alert';
        const prefix = r.type === 'added' ? '➕' : '➖';
        html += '<div class="cl-item"><span class="cl-tag ' + tag + '">' + label + '</span><span class="cl-name">' + prefix + ' ' + esc(name) + '</span></div>';
      });
      if (r.items.length > 5) html += '<div class="cl-empty">...还有 ' + (r.items.length - 5) + ' 项</div>';
    });
    html += '</div>';
  }

  content.innerHTML = html;
  $('changelogTime').textContent = new Date().toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
  panel.style.display = 'block';
  panel.scrollIntoView({behavior: 'smooth', block: 'nearest'});
}

// 关闭按钮 - moved to initDashboard
function setupChangelogClose() {
  const el = $('changelogClose');
  if (!el) return;
  el.onclick = () => {
    if (typeof switchView === 'function') { switchView('recPanel'); return; }
    $('changelogPanel').style.display = 'none';
    const navBtn = $('changelogNavBtn');
    if (navBtn) navBtn.style.display = 'none';
  };
}

// 轮询检查更新是否完成
async function pollUpdateComplete(startTime) {
  const MAX_WAIT = 120000; // 2分钟超时
  const INTERVAL = 5000;   // 5秒轮询一次
  const start = Date.now();

  while (Date.now() - start < MAX_WAIT) {
    await sleep(INTERVAL);
    try {
      // 检查 market.json 的更新时间是否比 startTime 新
      const r = await fetch('data_status.json?ts=' + Date.now(), { cache: 'no-store' });
      if (r.ok) {
        const data = await r.json();
        // 检测多个时间戳字段（alerts / items / index）
        const updateTime = data.updated;
        if (updateTime) {
          // 支持毫秒时间戳和 ISO 字符串两种格式
          const updateTs = typeof updateTime === 'number' ? updateTime : new Date(updateTime).getTime();
          // 如果更新时间比开始时间晚，说明更新完成了
          if (updateTs > startTime) {
            return true;
          }
        }
      }
    } catch(e) {}
  }
  return false; // 超时
}

document.addEventListener('keydown', function(e) {
  var tag = e.target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  if (e.key === 'j' || e.key === 'ArrowDown') { curPage = Math.min(curPage + 1, Math.ceil(getFiltered().length / PAGE_SIZE)); render(); }
  if (e.key === 'k' || e.key === 'ArrowUp') { curPage = Math.max(curPage - 1, 1); render(); }
  if (e.key === 'g' && !e.shiftKey) { curPage = 1; render(); }
  if (e.key === 'G') { curPage = Math.max(1, Math.ceil(getFiltered().length / PAGE_SIZE)); render(); }
  if (e.key === '/' || e.key === 's') { e.preventDefault(); DOM.searchInput.focus(); }
  if (e.key === 'Escape') { DOM.searchInput.blur(); DOM.searchInput.value = ''; searchQuery = ''; curPage = 1; invalidateCache(); render(); }
  if (e.key === 'r') $('refreshBtn').click();
});

document.addEventListener('keydown', function(e) {
  var tag = e.target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  if (e.key === 'j' || e.key === 'ArrowDown') { curPage = Math.min(curPage + 1, Math.ceil(getFiltered().length / PAGE_SIZE)); render(); }
  if (e.key === 'k' || e.key === 'ArrowUp') { curPage = Math.max(curPage - 1, 1); render(); }
  if (e.key === 'g' && !e.shiftKey) { curPage = 1; render(); }
  if (e.key === 'G') { curPage = Math.max(1, Math.ceil(getFiltered().length / PAGE_SIZE)); render(); }
  if (e.key === '/' || e.key === 's') { e.preventDefault(); DOM.searchInput.focus(); }
  if (e.key === 'Escape') { DOM.searchInput.blur(); DOM.searchInput.value = ''; searchQuery = ''; curPage = 1; invalidateCache(); render(); }
  if (e.key === 'r') $('refreshBtn').click();
});

function setupRefreshBtn() {
const btn = $('refreshBtn');
if (!btn) return;
btn.onclick = async function() {
  if (isUpdating) return; // 防止重复点击
  
  const btn = $('refreshBtn');
  const startTime = Date.now();
  isUpdating = true;
  
  // 保存刷新前的快照
  prevSnapshot = takeSnapshot();
  
  // 阶段1：立即加载当前数据
  btn.textContent = '⏳ 加载中...';
  btn.disabled = true;
  
  try {
    await loadAll();
    renderAnalysis();
    const loadTs = new Date(startTime).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
    DOM.updateTime.textContent = '刷新 ' + loadTs;
    $('refreshStatus').textContent = '加载中';
    $('refreshStatus').style.color = '';
    showToast('📊 已加载本地数据，开始全量扫描...', 2000);
  } catch (e) {
    console.error('Load failed:', e);
    $('refreshStatus').textContent = '❌ 失败';
    $('refreshStatus').style.color = '#f87171';
  }
  
  // 阶段2：触发全量扫描（持仓价格 + 异动 + 推荐）
  btn.textContent = '🧠 扫描全量数据...';
  $('refreshStatus').textContent = '扫描中';
  
  try {
    // 触发本地全量更新
    fetch('http://localhost:8765/update?mode=full').catch(() => {});
    
    // 同时触发 CI 更新（如果有 Token）
    if (ghToken) {
      // 触发数据更新 workflow
      fetch(WORKFLOW_API, {
        method: 'POST',
        headers: { 'Authorization': 'token ' + ghToken, 'Accept': 'application/vnd.github.v3+json', 'Content-Type': 'application/vnd.github+json' },
        body: JSON.stringify({ ref: 'main' })
      }).catch(() => {});
    }
    
    // 阶段3：轮询等待更新完成
    btn.textContent = '⏳ 更新中...';
    const completed = await pollUpdateComplete(startTime);
    
    if (completed) {
      // 更新完成，重新加载数据
      await loadAll();
      const finalTs = new Date().toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
      DOM.updateTime.textContent = '更新 ' + finalTs;
      $('refreshStatus').textContent = '✅ 成功';
      $('refreshStatus').style.color = '#4ade80';
      
      const items = H?.length || 0;
      const recs = (recData?.all?.length||0);
      showToast('✅ 全量扫描完成 · ' + items + ' 持仓 · ' + recs + ' 推荐', 4000);
      
      // 对比并显示变更日志
      const newSnap = takeSnapshot();
      const changes = diffSnapshot(prevSnapshot, newSnap);
      renderChangelog(changes);
    } else {
      showToast('⏱️ 扫描超时，数据将在后台更新', 3000);
      $('refreshStatus').textContent = '⏱️ 超时';
      $('refreshStatus').style.color = '#fbbf24';
    }
    
  } catch (e) {
    console.error('Update failed:', e);
    showToast('❌ 更新失败: ' + e.message, 3000);
    $('refreshStatus').textContent = '❌ 失败';
    $('refreshStatus').style.color = '#f87171';
  } finally {
    btn.textContent = '↻ 刷新';
    btn.disabled = false;
    isUpdating = false;
    setTimeout(() => { const rs=$('refreshStatus'); if(rs) { rs.textContent=''; rs.style.color=''; } }, 5000);
  }
};
} // end setupRefreshBtn

function setupTokenModal() {
const gearBtn = $('gearBtn');
if (!gearBtn) return;
gearBtn.onclick = function() {
  DOM.tokenInput.value = ghToken;
  DOM.tokenStatus.textContent = ghToken ? '✅ 已配置 Token' : '⚠ 未配置，编辑不会自动同步';
  DOM.tokenModal.classList.add('show');
};
const tokenCancel = $('tokenCancel');
if (tokenCancel) tokenCancel.onclick = () => DOM.tokenModal.classList.remove('show');
const tokenClear = $('tokenClear');
if (tokenClear) tokenClear.onclick = function() {
  ghToken = ''; localStorage.removeItem(LS_TOKEN_KEY);
  DOM.tokenInput.value = ''; DOM.tokenStatus.textContent = '🗑️ Token 已清除';
};
const tokenSave = $('tokenSave');
if (tokenSave) tokenSave.onclick = async function() {
  const token = DOM.tokenInput.value.trim();
  if (!token) { DOM.tokenStatus.textContent = '⚠ 请输入 Token'; return; }
  DOM.tokenStatus.textContent = '⏳ 验证中...';
  try {
    const r = await fetch('https://api.github.com/repos/'+GH_REPO, {headers:{'Authorization':'token '+token,'Accept':'application/vnd.github.v3+json'}});
    if (r.ok) {
      ghToken = token; localStorage.setItem(LS_TOKEN_KEY, token);
      DOM.tokenStatus.textContent = '✅ Token 有效，已保存！';
      setTimeout(() => DOM.tokenModal.classList.remove('show'), 1500);
    } else { DOM.tokenStatus.textContent = '❌ Token 无效或无权限'; }
  } catch(e) { DOM.tokenStatus.textContent = '❌ 网络错误'; }
};
if (DOM.tokenModal) DOM.tokenModal.onclick = function(e) { if (e.target === this) this.classList.remove('show'); }
} // end setupTokenModal

// ── 实时查价（通过 Cloudflare Worker）──
const WORKER_BASE = 'https://cs2wyx.asia'

async function fetchLivePrices(items, holdNames) {
  var allNames = []
  var seen = {}
  ;(items || []).forEach(function(r){
    var hn = r.hash_name || r.name
    if (hn && !seen[hn]) { seen[hn] = true; allNames.push(hn) }
  })
  ;(holdNames || []).forEach(function(n){
    if (n && !seen[n]) { seen[n] = true; allNames.push(n) }
  })
  if (!allNames.length) return
  // CSQAQ 单次请求过多会导致 502，每次最多 20 个，跳过明显不追踪的类型
  var skipTypes = ['Sticker', 'Patch', 'Charm', 'Graffiti', 'Case', 'Container', 'Capsule', 'Pin', 'Key', 'Music Kit', 'Pass', 'Souvenir', 'Collectible'];
  var filtered = allNames.filter(function(n){
    for(var i=0;i<skipTypes.length;i++){ if(n.indexOf(skipTypes[i])===0) return false; }
    return true;
  });
  var batch = filtered.slice(0, 35)
  try {
    var resp = await fetch(WORKER_BASE+'/api/csqaq/batch?names='+encodeURIComponent(batch.join(',')))
    if (!resp.ok) return
    var csqaqData = await resp.json()
    // 识别数据来源
    var sourceDetected = false;
    var touched = false;
    ;(items || []).forEach(function(r){
      var hn = r.hash_name || r.name
      if (hn && csqaqData[hn]) {
        var dp = csqaqData[hn]
        if (!sourceDetected && dp._source) { sourceDetected = dp._source; }
        if (dp.buff_sell > 0) { r.buff_sell = dp.buff_sell; r.buff_source = 'BUFF'; touched = true; }
        if (dp.buff_sell_num > 0) r.buff_sell_num = dp.buff_sell_num
        if (dp.yyyp_sell > 0) r.yyyp_sell = dp.yyyp_sell
        if (dp.yyyp_sell_num > 0) r.yyyp_sell_num = dp.yyyp_sell_num
        // ★ Steam 独立市场价：刷新后立刻重算偏离度，否则卡片上的
        //   「Steam偏离」会一直停留在 market.json 生成时的旧值。
        if (dp.steam_sell > 0) {
          var _prevSteam = r.n_steam || r.steam_sell || 0;
          r.steam_sell = dp.steam_sell
          r.n_steam = dp.steam_sell
          if (dp.steam_sell_num > 0) r.steam_sell_num = dp.steam_sell_num
          var _expect = (r.buff_sell || 0) * 1.45
          if (_expect > 0) {
            r.n_dev_steam = Math.round((dp.steam_sell - _expect) / _expect * 1000) / 10
          }
          if (_prevSteam !== dp.steam_sell) touched = true
        }
      }
    })
    // 价格变了 → 立即重渲染推荐列表，让偏离度标签跟着更新
    if (touched && typeof renderAllRecs === 'function') renderAllRecs()
    // 更新数据来源标记（双源显示）
    var srcBadge = document.getElementById('dataSourceBadge');
    if (srcBadge) {
      var hasYyyp = (H || []).some(function(h) { return (h.yyyp_sell || 0) > 0; });
      var hasBuff = (H || []).some(function(h) { return (h.buff_sell || 0) > 0; });
      if (hasYyyp && hasBuff) srcBadge.textContent = '📡CSQAQ+SteamDT';
      else if (hasYyyp) srcBadge.textContent = '📡CSQAQ';
      else if (hasBuff) srcBadge.textContent = '📡SteamDT';
      srcBadge.style.display = '';
    }
    if ((holdNames || []).length) {
      ;(H || []).forEach(function(h){
        var hn = h.mh || ''
        if (!hn || !csqaqData[hn]) return
        var dp = csqaqData[hn]
        if (dp.buff_sell > 0) { h.p = dp.buff_sell; h.buff_sell = dp.buff_sell; h.buff_sell_num = dp.buff_sell_num || 0; }
        if (dp.yyyp_sell > 0) { h.yyyp_sell = dp.yyyp_sell; h.yyyp_sell_num = dp.yyyp_sell_num || 0; }
        if (h.p > 0) { h.pnl = h.p - h.c; h.pnlPct = h.c > 0 ? (h.p-h.c)/h.c*100 : 0; }
      })
    }
  } catch(e) {}
}

// ═══════════════ RECOMMENDATIONS ═══════════════
const CHANNEL_LABELS = {eco:'📊 ECO信号', buff:'💰 BUFF信号'};
// 暴露到全局供 recModalScript 使用
window.CHANNEL_LABELS = CHANNEL_LABELS;

// ── Sparkline 折线图工具（全局可用）──
window.sparkline = function sparkline(prices, color, w, h) {
  if (!prices || prices.length < 2) return '';
  w = w || 120; h = h || 28;
  var pad = 2;
  var min = Math.min.apply(null, prices), max = Math.max.apply(null, prices);
  if (max - min < 0.01) { min -= 1; max += 1; }
  function sx(i) { return pad + i / (prices.length - 1) * (w - pad * 2); }
  function sy(v) { return h - pad - (v - min) / (max - min) * (h - pad * 2); }
  var d = prices.map(function(v,i){ return (i===0?'M':'L') + sx(i).toFixed(1) + ',' + sy(v).toFixed(1); }).join('');
  return '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + ' ' + h + '" style="vertical-align:middle"><path d="' + d + '" stroke="' + color + '" stroke-width="1.5" fill="none" stroke-linejoin="round" stroke-linecap="round"/></svg>';
}

// ── 去孤立尖刺后再画（真实采样里的瞬时异常挂单价会把整条曲线压平）──
// 只替换「左右邻居彼此接近、而自己离二者中点很远」的单点；真实的价格跳变（连续多点）不动。
window.sparklineClean = function(prices, color, w, h) {
  if (!prices || prices.length < 3) return window.sparkline(prices, color, w, h);
  var sorted = prices.slice().sort(function(a, b) { return a - b; });
  var m = Math.floor(sorted.length / 2);
  var med = sorted.length % 2 ? sorted[m] : (sorted[m - 1] + sorted[m]) / 2;
  var thr = Math.max(med * 0.08, 0.5);
  var out = prices.slice();
  for (var i = 1; i < prices.length - 1; i++) {
    var mid = (prices[i - 1] + prices[i + 1]) / 2;
    if (Math.abs(prices[i - 1] - prices[i + 1]) <= thr && Math.abs(prices[i] - mid) > thr) out[i] = mid;
  }
  return window.sparkline(out, color, w, h);
};

// ── 折线图口径说明（替代名不副实的"30日"）──
// ⚠ 后端取的是 price_history.db 的「最近 60 个采样点」，实测约 3~4 次/天，
//   即 ≈15~20 天，不是 30 天。这里按真实数据给出采样次数 / 日期区间 / 变动次数。
window.sparklineInfo = function(prices, ts, compact, prefix) {
  if (!prices || prices.length < 2) return '';
  var uniq = {}, n = 0;
  for (var i = 0; i < prices.length; i++) { if (!uniq[prices[i]]) { uniq[prices[i]] = 1; n++; } }
  if (compact) return (prefix ? prefix : prices.length + '次') + '·变动' + n + '次';
  var span = '';
  if (ts && ts.length === prices.length && ts[0] && ts[prices.length - 1]) {
    span = ' · ' + String(ts[0]).slice(5, 10) + '~' + String(ts[prices.length - 1]).slice(5, 10);
  }
  return (prefix ? prefix : '近' + prices.length + '次采样') + span + ' · 变动' + n + '次' + (n <= 2 ? '（价格长期未变）' : '');
};

// ── 价格走势图弹窗 ──
window.showPriceChart = async function(itemName, curPrice) {
  var overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.style.cssText = 'opacity:1;pointer-events:auto;display:flex';
  overlay.onclick = function(e) { if (e.target === overlay) overlay.remove(); };
  var box = document.createElement('div');
  box.style.cssText = 'background:var(--surface2);border:1px solid var(--border);border-radius:16px;padding:20px;max-width:660px;width:92%;position:relative;box-shadow:0 16px 48px rgba(0,0,0,.5)';
  box.innerHTML = '<div style="font-size:15px;font-weight:700;margin-bottom:10px;color:var(--text);display:flex;align-items:center;gap:8px"><span>📈</span>' + esc(cnName(itemName)) + '</div><div id="chartLoading" style="text-align:center;color:var(--text3);padding:48px 0">⏳ 加载数据...</div><button onclick="this.closest(\'.modal-overlay\').remove()" style="position:absolute;top:10px;right:14px;background:none;border:none;font-size:20px;cursor:pointer;color:var(--text3);width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;transition:all .2s" onmouseover="this.style.background=\'var(--surface)\'" onmouseout="this.style.background=\'none\'">✕</button>';
  overlay.appendChild(box);
  document.body.appendChild(overlay);
  
  try {
    var r = await fetch('/api/pricechart?name=' + encodeURIComponent(itemName));
    if (!r.ok) {
      var cp0 = Number(curPrice) || 0;
      document.getElementById('chartLoading').textContent = cp0 > 0 ? ('当前价 ¥' + cp0.toFixed(2) + ' · 暂无历史走势') : '暂无走势数据';
      return;
    }
    var data = await r.json();
    var prices = (data.eco || []).map(function(e){ return e.p; }).filter(function(p){ return p > 0; });
    if (prices.length < 2) {
      var cp = Number(curPrice) || (prices.length === 1 ? prices[0] : 0);
      document.getElementById('chartLoading').textContent = cp > 0 ? ('当前价 ¥' + cp.toFixed(2) + ' · 暂无历史走势') : '暂无走势数据';
      return;
    }
    var canvas = document.createElement('canvas');
    canvas.width = 620; canvas.height = 320;
    canvas.style.cssText = 'width:100%;height:auto;display:block';
    document.getElementById('chartLoading').replaceWith(canvas);
    var ctx = canvas.getContext('2d');
    var W = canvas.width, H = canvas.height;
    var padT = 32, padB = 44, padL = 56, padR = 80;
    var pw = W - padL - padR, ph = H - padT - padB;
    var min = Math.min.apply(null, prices), max = Math.max.apply(null, prices);
    var range = max - min || 1;
    var padding = range * 0.08;
    if (range < 0.5) { range = 1; padding = 0.5; }
    min -= padding; max += padding; range = max - min;
    function px(i) { return padL + i / (prices.length - 1) * pw; }
    function py(v) { return padT + (max - v) / range * ph; }
    
    // 干净背景
    ctx.fillStyle = '#0d1117'; ctx.beginPath(); ctx.roundRect(0,0,W,H,10); ctx.fill();
    
    // 虚线网格
    ctx.strokeStyle = 'rgba(75,85,99,.2)'; ctx.lineWidth = 0.5;
    ctx.setLineDash([4,6]);
    for (var g = 0; g <= 3; g++) {
      var gy = padT + g/3*ph, val = max - g/3*range;
      ctx.beginPath(); ctx.moveTo(padL,gy); ctx.lineTo(W-padR,gy); ctx.stroke();
      ctx.fillStyle = '#9ca3af'; ctx.font = '11px system-ui,sans-serif'; ctx.textAlign = 'right';
      ctx.fillText('¥'+val.toFixed(0), padL-10, gy+4);
    }
    ctx.setLineDash([]);
    
    // X轴日期
    [0, Math.floor(prices.length*0.33), Math.floor(prices.length*0.66), prices.length-1].forEach(function(i){
      var ts = ((data.eco||[])[i]||{}).t||'';
      var label = ts.length>10 ? ts.substring(5,10) : '#'+(i+1);
      ctx.fillStyle = '#6b7280'; ctx.font = '10px system-ui,sans-serif'; ctx.textAlign = 'center';
      ctx.fillText(label, px(i), H-padB+18);
    });
    
    // 渐变填充
    var grad = ctx.createLinearGradient(0,padT,0,H-padB);
    grad.addColorStop(0,'rgba(59,130,246,.18)'); grad.addColorStop(.5,'rgba(59,130,246,.05)'); grad.addColorStop(1,'rgba(59,130,246,0)');
    ctx.beginPath(); prices.forEach(function(v,i){ i===0?ctx.moveTo(px(i),py(v)):ctx.lineTo(px(i),py(v)); });
    ctx.lineTo(px(prices.length-1),H-padB); ctx.lineTo(padL,H-padB); ctx.closePath();
    ctx.fillStyle = grad; ctx.fill();
    
    // 折线（平滑贝塞尔）+ 发光
    ctx.beginPath(); ctx.moveTo(px(0),py(prices[0]));
    for (var i=1; i<prices.length; i++) {
      ctx.bezierCurveTo(px(i-1)+pw/prices.length*.35, py(prices[i-1]), px(i)-pw/prices.length*.35, py(prices[i]), px(i), py(prices[i]));
    }
    ctx.strokeStyle = '#3b82f6'; ctx.lineWidth = 2.8; ctx.lineJoin = 'round';
    ctx.shadowColor = 'rgba(59,130,246,.5)'; ctx.shadowBlur = 10; ctx.stroke(); ctx.shadowBlur = 0;
    
    // 数据点
    prices.forEach(function(v,i){
      var r = (i===0||i===prices.length-1) ? 3.5 : 1.8;
      ctx.beginPath(); ctx.arc(px(i),py(v),r,0,Math.PI*2);
      ctx.fillStyle = '#0d1117'; ctx.fill();
      ctx.strokeStyle = 'rgba(59,130,246,.7)'; ctx.lineWidth = 2; ctx.stroke();
    });
    
    // 右侧信息面板
    var lastV = prices[prices.length-1], firstV = prices[0];
    var changePct = ((lastV-firstV)/firstV*100)||0;
    var isUp = changePct >= 0;
    var bx = W - padR + 10, by = padT + 10, bw = 64, bh = 56;
    ctx.fillStyle = 'rgba(30,41,59,.9)'; ctx.beginPath(); ctx.roundRect(bx,by,bw,bh,8); ctx.fill();
    ctx.strokeStyle = isUp ? 'rgba(52,211,153,.4)' : 'rgba(248,113,113,.4)'; ctx.lineWidth = 1; ctx.stroke();
    ctx.fillStyle = '#f1f5f9'; ctx.font = 'bold 15px system-ui,sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('¥'+lastV.toFixed(2), bx+bw/2, by+20);
    ctx.fillStyle = isUp ? '#34d399' : '#f87171'; ctx.font = 'bold 12px system-ui,sans-serif';
    ctx.fillText((isUp?'↑+':'↓')+Math.abs(changePct).toFixed(1)+'%', bx+bw/2, by+40);
    
    // 顶部信息行：最低价 | 最高价 | 波动幅度
    ctx.fillStyle = '#94a3b8'; ctx.font = '10px system-ui,sans-serif'; ctx.textAlign = 'left';
    var minV = Math.min.apply(null,prices), maxV = Math.max.apply(null,prices);
    ctx.fillText('低 ¥'+minV.toFixed(2), padL, padT-8);
    ctx.fillText('高 ¥'+maxV.toFixed(2), padL+pw/3, padT-8);
    ctx.fillText('波幅 '+(Math.abs(changePct)).toFixed(1)+'%', padL+pw*2/3, padT-8);
    
    // 底部信息
    var dates = Object.keys(data.eco||prices);
    var startDate = (data.eco||[{t:''}])[0] ? ((data.eco||[{t:''}])[0].t||'').substring(0,10) : '';
    var endDate = (data.eco||[{t:''}])[prices.length-1] ? ((data.eco||[{t:''}])[prices.length-1].t||'').substring(0,10) : '';
    ctx.fillStyle = '#526477'; ctx.font = '10px system-ui,sans-serif'; ctx.textAlign = 'right';
    ctx.fillText('BUFF | '+prices.length+'期 | '+(startDate||'')+(endDate?' → '+endDate:''), W-padR, H-padB+14);
  } catch(e) {
    document.getElementById('chartLoading').textContent = '❌ 加载失败';
  }
}

// ═══════════════ 推荐 · 行情终端渲染（v2 2026-09-17）═══════════════
// 口径不变：后端 recommendations.all 已按 _score 预排序；此处仅渲染 + 客户端排序。
var _recSortKey = 'score', _recSortDesc = true, _recSortedItems = [];
var REC_SORT_FIELDS = {
  score: function(it){ return typeof it.score === 'number' ? it.score : -1; },
  rate_7: function(it){ return typeof it.rate_7 === 'number' ? it.rate_7 : -1e9; },
  n_dev_steam: function(it){ return typeof it.n_dev_steam === 'number' ? it.n_dev_steam : -1e9; },
  eco_selling: function(it){ var v = parseFloat(it.n_supply_real); return (isFinite(v) && v > 0) ? v : (parseFloat(it.eco_selling) || -1); }
};
var REC_SORT_LABELS = { score:'评分', rate_7:'7日涨跌', n_dev_steam:'Steam偏离', eco_selling:'存世量' };

window.recSortBy = function(key) {
  if (_recSortKey === key) { _recSortDesc = !_recSortDesc; } else { _recSortKey = key; _recSortDesc = true; }
  document.querySelectorAll('.rt-chip[data-rsort]').forEach(function(c) {
    var k = c.getAttribute('data-rsort');
    c.classList.toggle('on', k === key);
    c.textContent = REC_SORT_LABELS[k] + (k === key ? (_recSortDesc ? ' ↓' : ' ↑') : '');
  });
  var th = document.getElementById('rth-score');
  if (th) th.innerHTML = '评分 <span class="ar">' + (_recSortKey === 'score' ? (_recSortDesc ? '▼' : '▲') : '') + '</span>';
  recPage = 1;
  renderAllRecs();
};

function recChannelLabel(ch) { return (window.CHANNEL_LABELS && window.CHANNEL_LABELS[ch]) || ch || ''; }
function recScoreColor(s) { return s >= 50 ? 'var(--amber)' : (s >= 35 ? 'var(--blue)' : 'var(--text3)'); }
function recMoney(v, d) { var n = Number(v); if (!isFinite(n)) return '—'; return '¥' + n.toLocaleString('zh-CN', { minimumFractionDigits: d || 0, maximumFractionDigits: d || 0 }); }
function recPct(v) {
  if (typeof v !== 'number' || !isFinite(v) || v === 0) return '<span class="rt-dim">—</span>';
  return '<span style="color:' + (v >= 0 ? 'var(--rise)' : 'var(--fall)') + '">' + (v > 0 ? '+' : '\u2212') + Math.abs(v).toFixed(1) + '%</span>';
}
// 信号推导（纯展示层，基于现有字段，不新增/不改动数据）
function recSignal(item) {
  var sc = typeof item.score === 'number' ? item.score : 0;
  var dev = item.n_dev_steam;
  var r7 = typeof item.rate_7 === 'number' ? item.rate_7 : 0;
  var r30 = typeof item.rate_30 === 'number' ? item.rate_30 : 0;
  var buy = item.buff_buy_num || 0, sell = item.buff_sell_num || 0;
  var s = (dev < -25) || (dev < 0 && sell > 0 && buy > 0 && sell / buy > 8);
  if (s) return { cls: 'avoid', txt: '避雷', conf: Math.max(50, 100 - Math.round(sc)) };
  if (sc >= 55 && (dev > 25 || (r7 > 0 && r30 > 0))) return { cls: 'buy', txt: '买入', conf: Math.min(95, Math.round(sc) + 10) };
  return { cls: 'watch', txt: '观望', conf: Math.max(40, Math.round(sc)) };
}

function recBuildRow(item, gi, zebra) {
  var nm = item.name || '--';
  var channel = item.tag || 'eco';
  var sNum = typeof item.score === 'number' ? item.score : 0;
  var rankCls = gi === 0 ? 'rt-rk t1' : (gi === 1 ? 'rt-rk t2' : (gi === 2 ? 'rt-rk t3' : 'rt-rk'));
  // 价格（BUFF 优先，回退 ECO）
  var bestPrice = item.price > 0 ? item.price : (item.eco_price > 0 ? item.eco_price : 0);
  var priceSrc = (item.price > 0 && item.eco_price > 0 && Math.abs(item.price - item.eco_price) < 0.5) ? 'ECO参考' : (item.price > 0 ? (item.buff_source || 'BUFF') : (item.eco_price > 0 ? 'ECO' : ''));
  // AI 操作建议徽章
  var ai = window._aiAnalysis || {};
  var aiData = ai[nm] || ai[item._hash || ''] || null;
  var aiBadge = '';
  if (aiData) {
    var v = typeof aiData === 'object' ? (aiData.verdict || '') : ((String(aiData).match(/操作建议[:：]\s*(\S+)/) || [])[1] || '');
    if (v) aiBadge = '<span class="rt-aib">🤖 ' + esc(v) + '</span>';
  }
  // 稀有度标签已移除：fp_rarity 为 FirePulse 遗留死字段（CSQAQ 排行榜仅覆盖 1/30，无有效来源）
  var chTag = channel ? '<span class="rt-ch">' + esc(recChannelLabel(channel)) + '</span>' : '';
  var buyNum = item.buff_buy_num || 0;
  // 存世量：优先真实值（CSQAQ statistic，2026-09-18 接入）；无则回退 ECO 在售件数代理
  var _supReal = parseFloat(item.n_supply_real);
  var _supIsReal = isFinite(_supReal) && _supReal > 0;
  var sup = _supIsReal ? _supReal : parseFloat(item.eco_selling);
  var _supFmt = function(v) { return v >= 10000 ? (v / 10000).toFixed(1) + '万' : Math.round(v).toLocaleString('zh-CN'); };
  var supTxt = sup > 0
    ? (_supIsReal ? _supFmt(sup) : _supFmt(sup) + '<span style="font-size:9px;color:var(--text3)">*代理</span>')
    : '—';
  if (_supIsReal && typeof item.supply_chg7 === 'number') {
    var _c7 = item.supply_chg7;
    supTxt += '<span style="font-size:9px;margin-left:3px;color:' + (_c7 > 0 ? 'var(--rise)' : 'var(--fall)') + '">'
      + (_c7 > 0 ? '+' : '') + _c7.toLocaleString('zh-CN') + '/7d</span>';
  }
  // Steam 偏离（唯一的真·跨市场信号）
  var nd = item.n_dev_steam, devHtml;
  if (typeof nd === 'number' && isFinite(nd)) {
    var a = Math.abs(nd);
    var txt = nd < -25 ? ('异常便宜 −' + a.toFixed(0) + '%') : (nd > 25 ? ('异常贵 +' + a.toFixed(0) + '%') : '正常');
    var cl = nd < -25 ? 'var(--fall)' : (nd > 25 ? 'var(--rise)' : 'var(--text3)');
    devHtml = '<span style="color:' + cl + ';font-weight:700" title="对比 Steam 独立市场常态比值 1.45，偏离 ' + (nd >= 0 ? '+' : '') + nd.toFixed(1) + '%">' + txt + '</span>';
  } else if ((item.n_steam || item.steam_sell) > 0) {
    devHtml = '<span class="rt-dim" title="已有多平台 Steam 价，但缺国内价，无法计算偏离">' + recMoney(item.n_steam || item.steam_sell, 0) + '</span>';
  } else { devHtml = '<span class="rt-dim" title="缺少 Steam 价或国内价，无法计算偏离度">无法计算</span>'; }
  // 走势（行内单线：ECO 优先，回退悠悠/BUFF）
  // 走势：优先「按天聚合」序列 → 「近30日」才名副其实；无日线则退回原始采样点
  var _dArr = item.eco_daily, _dTs = item.eco_daily_ts;
  var _dailyOk = !!(_dArr && _dArr.length >= 3);
  var _useEco = !!(item.eco_history && item.eco_history.length >= 2);
  var _lineArr = _dailyOk ? _dArr
    : (_useEco ? item.eco_history
      : ((item.yyyp_history && item.yyyp_history.length >= 2) ? item.yyyp_history : (item.multi_history || [])));
  var _lineTs = _dailyOk ? (_dTs || null)
    : (_useEco ? (item.eco_history_ts || null)
      : ((item.yyyp_history && item.yyyp_history.length >= 2) ? (item.yyyp_history_ts || null) : (item.multi_history_ts || null)));
  var _linePre = _dailyOk ? ('近' + _dArr.length + '日·日均') : null;
  var _lineColor = (_dailyOk || _useEco) ? 'var(--blue)' : 'var(--amber)';
  var _lineFull = (typeof window.sparklineInfo === 'function') ? window.sparklineInfo(_lineArr, _lineTs, false, _linePre) : '';
  var _lineShort = (typeof window.sparklineInfo === 'function')
    ? (_dailyOk ? (_dArr.length + '日·日均') : window.sparklineInfo(_lineArr, _lineTs, true))
    : '';
  var line = (typeof window.sparklineClean === 'function')
    ? window.sparklineClean(_lineArr, _lineColor, 68, 18)
    : sparkline(_lineArr, _lineColor, 68, 18);
  var lineCell = (line ? line : '<span class="rt-dim">无数据</span>')
    + (_lineShort ? '<div style="font-size:8px;color:var(--text3);line-height:1.3;margin-top:1px" title="' + _lineFull + '">' + _lineShort + '</div>' : '');
  var sig = recSignal(item);

  return '<tr class="rt-row' + (zebra ? ' z' : '') + '" data-gi="' + gi + '" role="button" tabindex="0" aria-expanded="false">' +
    '<td class="l"><span class="' + rankCls + '">' + (gi + 1) + '</span></td>' +
    '<td class="l"><div class="rt-nm" title="' + esc(nm) + '">' + esc(nm) + '</div>' +
      '<div class="rt-tags">' + chTag + aiBadge + (buyNum > 0 ? '<span class="rt-buyq">📥' + buyNum + '</span>' : '') + '</div></td>' +
    '<td><span class="rt-scw"><b style="color:' + recScoreColor(sNum) + '">' + sNum.toFixed(1) + '</b>' +
      '<span class="rt-scb"><i style="width:' + Math.min(100, Math.max(0, sNum)).toFixed(0) + '%;background:' + recScoreColor(sNum) + '"></i></span></span></td>' +
    '<td class="rt-pc">' + (bestPrice > 0 ? recMoney(bestPrice, 0) : '—') + (priceSrc ? '<span class="rt-src">' + esc(priceSrc) + '</span>' : '') + '</td>' +
    '<td>' + (item.eco_price > 0 ? recMoney(item.eco_price, 2) : '<span class="rt-dim">—</span>') + '</td>' +
    '<td>' + (item.buff_sell > 0 ? recMoney(item.buff_sell, 2) + (item.buff_buy > 0 ? '<span class="rt-sub">求 ' + recMoney(item.buff_buy, 2) + '</span>' : '') : '<span class="rt-dim">—</span>') + '</td>' +
    '<td>' + (item.yyyp_sell > 0 ? recMoney(item.yyyp_sell, 2) : '<span class="rt-dim">—</span>') + '</td>' +
    '<td style="color:#8b9dc3">' + ((item.n_steam || item.steam_sell) > 0 ? recMoney(item.n_steam || item.steam_sell, 2) : '<span class="rt-dim" title="数据源未返回 Steam 独立市场价（基准价覆盖率不足）">无数据</span>') + '</td>' +
    '<td>' + devHtml + '</td>' +
    '<td>' + recPct(item.rate_1) + '</td>' +
    '<td>' + recPct(item.rate_7) + '</td>' +
    '<td>' + recPct(item.rate_30) + '</td>' +
    '<td>' + supTxt + '</td>' +
    '<td class="l">' + lineCell + '</td>' +
    '<td><span class="rt-sig ' + sig.cls + '">' + sig.txt + ' ' + sig.conf + '</span></td>' +
  '</tr>';
}

function recBuildExpand(item, gi, aiReasonMap) {
  var src = item.buff_source || 'BUFF';
  var d1 = [];
  if (item.eco_price > 0) d1.push('<div class="ln"><span class="e1">ECO</span> <b>' + recMoney(item.eco_price, 2) + '</b>' + (item.eco_selling > 0 ? ' 在售 ▲' + item.eco_selling : '') + '</div>');
  if (item.buff_sell > 0) d1.push('<div class="ln"><span class="e1">' + esc(src) + '</span> <b>' + recMoney(item.buff_sell, 2) + '</b>' + (item.buff_buy > 0 ? ' 求购 <b>' + recMoney(item.buff_buy, 2) + '</b>' : '') + ' · 在售 ▲' + (item.buff_sell_num || 0) + ' 求购 ▼' + (item.buff_buy_num || 0) + '</div>');
  if (item.yyyp_sell > 0) d1.push('<div class="ln"><span class="e2">悠悠</span> <b>' + recMoney(item.yyyp_sell, 2) + '</b>' + (item.yyyp_sell_num > 0 ? ' 在售 ▲' + item.yyyp_sell_num : '') + '</div>');
  var st = item.n_steam || item.steam_sell || 0;
  if (st > 0) d1.push('<div class="ln"><span class="e3">Steam</span> <b>' + recMoney(st, 2) + '</b> · 独立市场基准（常态比 1.45）</div>');
  else d1.push('<div class="ln"><span class="e3">Steam</span> <span class="rt-dim">无数据（缺独立市场基准，溢价与偏离不可评估）</span></div>');
  if (!d1.length) d1.push('<div class="ln">暂无平台深度数据</div>');

  // 评分构成（真实字段：eco_score / buff_score / score）+ 多源覆盖率
  // ⚠ 2026-09-17：原版读 item.fp_dims（FirePulse 遗留字段，数据里出现 0 次）→ 永远显示"无评分维度数据"。
  var d2 = [];
  function _num(v) { var f = parseFloat(v); return isFinite(f) ? f : null; }
  [['ECO 分', _num(item.eco_score)], ['BUFF 分', _num(item.buff_score)], ['综合分', _num(item.score)]].forEach(function(p) {
    if (p[1] === null) return;
    var pc = Math.min(100, Math.max(0, p[1]));
    d2.push('<div class="rt-dimrow"><span class="dn2">' + p[0] + '</span><span class="dbar"><i style="width:' + pc.toFixed(0) + '%"></i></span><span class="dv">' + p[1].toFixed(1) + '</span></div>');
  });
  var _cov = _num(item.n_cov);
  if (_cov !== null && _cov > 0) {
    d2.push('<div class="rt-dimrow"><span class="dn2">多源覆盖</span><span class="dbar"><i style="width:' + Math.min(100, _cov * 100).toFixed(0) + '%;background:var(--amber)"></i></span><span class="dv">' + (_cov * 100).toFixed(0) + '%</span></div>');
  }
  // 数据缺口提示（2026-09-18）：评分对缺失子项按中性 0.5 计 → 必须让用户知道分数基于部分数据
  try {
    var _gaps = item.data_gaps;
    if (Object.prototype.toString.call(_gaps) === '[object Array]' && _gaps.length) {
      var _gname = { eco: 'ECO 盘口', buff: 'BUFF 盘口', yy: '悠悠盘口' };
      d2.push('<div class="ln" style="margin-top:4px;color:var(--amber)">⚠ 数据不全：' +
        esc(_gaps.map(function(g) { return _gname[g] || g; }).join('、')) +
        ' 有子项缺失，已按中性值计入</div>');
    }
  } catch (e) {}
  if (!d2.length) d2.push('<div class="ln">该件缺评分构成数据</div>');
  // 数据源与跨市场信号（真实字段）
  var _meta = [];
  if (item.n_ref_src) _meta.push('基准源 ' + esc(item.n_ref_src) + ((_num(item.n_ref) || 0) > 0 ? '（¥' + Number(item.n_ref).toFixed(2) + '）' : ''));
  var _dev = _num(item.n_dev_steam);
  if (_dev !== null) _meta.push('Steam 偏离 ' + (_dev >= 0 ? '+' : '') + _dev.toFixed(1) + '%');
  var _pb = _num(item.n_premium_buff);
  if (_pb !== null) _meta.push('BUFF 溢价 ' + _pb.toFixed(1) + '%');
  var _py = _num(item.n_premium_yyyp);
  if (_py !== null) _meta.push('悠悠溢价 ' + _py.toFixed(1) + '%');
  if (_meta.length) d2.push('<div class="ln" style="margin-top:5px">' + _meta.join(' · ') + '</div>');
  var _warn = item.n_warn;
  if (_warn && _warn.length) d2.push('<div class="ln" style="color:#fbbf24">⚠ ' + esc(String(_warn[0]).slice(0, 60)) + '</div>');

  var m = aiReasonMap[item.name] || aiReasonMap[item.hash_name] || {};
  var raw = m.reason || item._reason || '';
  var p = raw.indexOf('| ');
  var reason = p >= 0 ? raw.substring(p + 2) : raw;
  var pts = raw.match(/[❶❷❸❹❺][^❶❷❸❹❺]*/g);
  if (pts && pts.length >= 3) reason = pts.slice(0, 3).map(function(d) { return d.trim().replace(/^[❶❷❸❹❺]\s*/, '').replace(/[「」]/g, '').slice(0, 40); }).join(' · ');
  var d3 = '<div class="rt-reason">' + esc(reason || '暂无推荐理由') + '</div>';
  if (m.risk) d3 += '<div class="rt-risk">⚠ ' + esc(String(m.risk).slice(0, 90)) + '</div>';
  var _eDaily = !!(item.eco_daily && item.eco_daily.length >= 3);
  var _eArr = _eDaily ? item.eco_daily : (item.eco_history || []);
  var _eTss = _eDaily ? (item.eco_daily_ts || null) : item.eco_history_ts;
  var eSvg = (typeof window.sparklineClean === 'function')
    ? window.sparklineClean(_eArr, 'var(--blue)', 118, 22)
    : sparkline(_eArr, 'var(--blue)', 118, 22);
  var _eInfo = (typeof window.sparklineInfo === 'function')
    ? window.sparklineInfo(_eArr, _eTss, false, _eDaily ? ('近' + _eArr.length + '日·日均') : null)
    : '';
  var altHist = (item.yyyp_history && item.yyyp_history.length) ? item.yyyp_history : (item.multi_history || []);
  var aSvg = (typeof window.sparklineClean === 'function')
    ? window.sparklineClean(altHist, 'var(--amber)', 118, 22)
    : sparkline(altHist, 'var(--amber)', 118, 22);
  var _aTs = (item.yyyp_history && item.yyyp_history.length) ? (item.yyyp_history_ts || null) : (item.multi_history_ts || null);
  var _aInfo = (typeof window.sparklineInfo === 'function') ? window.sparklineInfo(altHist, _aTs) : '';
  var _aName = (item.yyyp_history && item.yyyp_history.length) ? '悠悠' : 'BUFF';
  if (eSvg || aSvg) {
    d3 += '<div class="rt-sparks">' +
      (eSvg ? '<div><div class="lbl2" style="color:var(--blue)">ECO · ' + _eInfo + '</div>' + eSvg + '</div>' : '') +
      (aSvg ? '<div><div class="lbl2" style="color:var(--amber)">' + _aName + ' · ' + _aInfo + '</div>' + aSvg + '</div>' : '') +
      '</div>';
  }
  d3 += '<div style="margin-top:8px"><span class="rt-chip rt-open" data-gi="' + gi + '">查看完整详情 →</span></div>';

  return '<tr class="rt-exp" style="display:none"><td colspan="15"><div class="rt-exgrid">' +
    '<div class="rt-excol"><div class="h">▸ 市场深度 · 在售 / 求购</div>' + d1.join('') + '</div>' +
    '<div class="rt-excol"><div class="h">▸ 评分构成 · 数据源</div>' + d2.join('') + '</div>' +
    '<div class="rt-excol"><div class="h">▸ 推荐理由 / 风险 / 走势</div>' + d3 +
    (typeof fcLine === 'function' ? fcLine(item) : '') + '</div>' +
    '</div></td></tr>';
}

function renderAllRecs() {
  const grid = DOM.recGrid;
  if (!grid) return;

  const allItems = (recData.all || []).slice();
  if (!allItems.length) {
    grid.innerHTML = '<tr><td colspan="15" style="text-align:center;padding:36px 0;color:var(--text3)"><div style="font-size:26px">🧠</div>暂无推荐<br><span style="font-size:11px">数据更新后自动生成</span></td></tr>';
    var pz = document.getElementById('recPager'); if (pz) pz.innerHTML = '';
    var cz = document.getElementById('recCount'); if (cz) cz.textContent = '';
    return;
  }

  // ── AI 推荐理由查找表（智谱 GLM-4）──
  var aiReasonMap = {};
  ((window._aiRecommendations || {}).picks || []).forEach(function(p) {
    if (p.name) aiReasonMap[p.name] = { reason: p.reason || '', risk: p.risk || '', operation: p.operation || '' };
  });

  renderRecCompare(allItems);
  _recAllItems = allItems;
  renderAIRecommendations();

  // ── 客户端排序（默认保持后端评分序）──
  var keyFn = REC_SORT_FIELDS[_recSortKey] || REC_SORT_FIELDS.score;
  var sorted = allItems.slice().sort(function(a, b) {
    var va = keyFn(a), vb = keyFn(b);
    return _recSortDesc ? (vb - va) : (va - vb);
  });
  _recSortedItems = sorted;

  var totalPages = Math.ceil(sorted.length / REC_PAGE_SIZE);
  if (recPage > totalPages) recPage = Math.max(1, totalPages);
  var start = (recPage - 1) * REC_PAGE_SIZE;
  var pageItems = sorted.slice(start, start + REC_PAGE_SIZE);

  var rows = [];
  pageItems.forEach(function(item, idx) {
    var gi = start + idx;                    // 全局排名（与当前排序一致）
    rows.push(recBuildRow(item, gi, idx % 2 === 1));
    rows.push(recBuildExpand(item, gi, aiReasonMap));
  });
  grid.innerHTML = rows.join('');

  // 行交互：点击/回车展开；展开区内「查看完整详情」打开原详情弹窗
  grid.querySelectorAll('.rt-row').forEach(function(tr) {
    var toggle = function() {
      var nx = tr.nextElementSibling;
      if (!nx || !nx.classList.contains('rt-exp')) return;
      var show = nx.style.display === 'none';
      nx.style.display = show ? '' : 'none';
      tr.setAttribute('aria-expanded', show ? 'true' : 'false');
    };
    tr.addEventListener('click', toggle);
    tr.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
    });
  });
  grid.querySelectorAll('.rt-open').forEach(function(b) {
    b.addEventListener('click', function(e) {
      e.stopPropagation();
      var gi = parseInt(b.getAttribute('data-gi'), 10);
      var it = _recSortedItems[gi];
      if (it && window.showRecModal) window.showRecModal(it);
    });
  });

  // 计数
  var cntEl = document.getElementById('recCount');
  if (cntEl) cntEl.textContent = '共 ' + sorted.length + ' 条 · 本页 ' + pageItems.length + ' 条 · 按「' + (REC_SORT_LABELS[_recSortKey] || '评分') + '」排序';

  // 排序控件绑定（仅一次）
  if (!window._recSortBound) {
    window._recSortBound = 1;
    document.querySelectorAll('.rt-chip[data-rsort]').forEach(function(c) {
      c.addEventListener('click', function() { window.recSortBy(c.getAttribute('data-rsort')); });
    });
    var th = document.getElementById('rth-score');
    if (th) th.addEventListener('click', function() { window.recSortBy('score'); });
  }

  // ── 分页器 ──
  var rc = document.getElementById('recContent');
  var pager = document.getElementById('recPager');
  if (!pager) {
    pager = document.createElement('div');
    pager.id = 'recPager';
    pager.className = 'rec-pager';
    if (rc) rc.appendChild(pager);
  }
  pager.innerHTML = '';
  var pageInfo = document.createElement('span');
  pageInfo.className = 'rec-page-info';
  pageInfo.textContent = totalPages > 1 ? '第' + recPage + '/' + totalPages + '页 共' + sorted.length + '条' : '共' + sorted.length + '条推荐';
  pager.appendChild(pageInfo);

  if (totalPages > 1) {
    var prevBtn = document.createElement('button');
    prevBtn.className = 'rec-page-btn';
    prevBtn.textContent = '←';
    prevBtn.disabled = recPage <= 1;
    if (!prevBtn.disabled) prevBtn.addEventListener('click', function() { goRecPage(recPage - 1); });
    pager.appendChild(prevBtn);

    var maxVisible = 7;
    var startPage = Math.max(1, recPage - Math.floor(maxVisible / 2));
    var endPage = Math.min(totalPages, startPage + maxVisible - 1);
    startPage = Math.max(1, endPage - maxVisible + 1);
    for (var p2 = startPage; p2 <= endPage; p2++) {
      (function(pageNum) {
        var btn = document.createElement('button');
        btn.className = 'rec-page-num' + (pageNum === recPage ? ' active' : '');
        btn.textContent = pageNum;
        btn.addEventListener('click', function() { goRecPage(pageNum); });
        pager.appendChild(btn);
      })(p2);
    }

    var nextBtn = document.createElement('button');
    nextBtn.className = 'rec-page-btn';
    nextBtn.textContent = '→';
    nextBtn.disabled = recPage >= totalPages;
    if (!nextBtn.disabled) nextBtn.addEventListener('click', function() { goRecPage(recPage + 1); });
    pager.appendChild(nextBtn);
  }
}

// ── 推荐池质量概览（真实统计，非价格对比）──
function renderRecCompare(items) {
  var bar = document.getElementById('recCompareBar');
  if (!bar) return;
  var cnt = items.length;
  if (!cnt) { bar.style.display = 'none'; return; }

  var scoreSum = 0, scoreN = 0, hi = 0;          // 平均评分 / 高分占比
  var covN = 0, covSum = 0;                      // 多源覆盖率（n_cov，真实字段）
  var supSum = 0, supN = 0;                      // 平均存世量
  var rarity = {};                               // 稀有度分布
  var weekSum = 0, weekUp = 0, weekN = 0;        // 周涨跌结构
  items.forEach(function(r) {
    var sc = r.score;
    if (typeof sc === 'number' && sc > 0) { scoreSum += sc; scoreN++; if (sc >= 60) hi++; }
    var cv = r.n_cov;
    if (typeof cv === 'number' && cv > 0) { covN++; covSum += cv; }
    var sup = r.eco_selling;   // ECO 在售量（≈存世量的可用代理）
    if (typeof sup === 'number' && sup > 0) { supSum += sup; supN++; }
    // fp_rarity 已废弃（无有效数据源）
    var wk = (typeof r.rate_7 === 'number') ? r.rate_7 / 100 : null;  // fp_week_ratio 为死字段，改用真实 7 日涨跌
    if (typeof wk === 'number') { weekN++; weekSum += wk; if (wk > 0) weekUp++; }
  });

  var avgScore = scoreN ? (scoreSum / scoreN).toFixed(1) : null;
  var hiRate = scoreN ? Math.round(hi / scoreN * 100) : 0;
  var avgSup = supN ? Math.round(supSum / supN) : null;
  var weekRate = weekN ? Math.round(weekUp / weekN * 100) : null;

  var chips = [];
  chips.push('<span class="rcq-chip"><b>' + cnt + '</b> 只候选</span>');
  if (avgScore !== null) {
    chips.push('<span class="rcq-chip"><b class="rcq-hi">' + avgScore + '</b> 均分</span>');
    chips.push('<span class="rcq-chip"><b>' + hi + '</b> 只 ≥60分</span>');
  }
  if (covN) chips.push('<span class="rcq-chip">多源覆盖 <b>' + Math.round(covSum / covN * 100) + '%</b></span>');
  if (avgSup !== null) chips.push('<span class="rcq-chip">均挂单 <b>' + avgSup.toLocaleString() + '</b> 件</span>');
  if (weekRate !== null && weekN >= cnt / 2) chips.push('<span class="rcq-chip">周线上涨 <b class="rcq-up">' + weekRate + '%</b></span>');


  bar.style.display = 'block';
  bar.innerHTML =
    '<div class="rcq">' +
      '<div class="rcq-head">' +
        '<span class="rcq-title">推荐池质量</span>' +
        '<span class="rcq-sub">数据源 ECO · CSQAQ · SteamDT</span>' +
      '</div>' +
      '<div class="rcq-chips">' + chips.join('') + '</div>' +
      
    '</div>';
}

function goRecPage(n) {
  recPage = Math.max(1, Math.min(n, Math.ceil(_recAllItems.length / REC_PAGE_SIZE)));
  renderAllRecs();
  var el = document.getElementById('recPanel');
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ═══════════════ TECHNICAL ANALYSIS HELPERS ═══════════════
/**
 * 计算均线 (MA)
 * @param {Array} prices 价格数组（按时间顺序，最新的在最后）
 * @param {number} period 周期
 * @returns {number|null} 均线值
 */
function calcMA(prices, period) {
  if (prices.length < period) return null;
  const slice = prices.slice(-period);
  return slice.reduce((a, b) => a + b, 0) / period;
}

/**
 * 计算布林带
 * @param {Array} prices 价格数组
 * @param {number} period 周期（默认10）
 * @param {number} stdDev 标准差倍数（默认2）
 * @returns {Object} {upper, middle, lower, width}
 */
function calcBollingerBands(prices, period = 10, stdDev = 2) {
  if (prices.length < period) return { upper: null, middle: null, lower: null, width: null };
  const slice = prices.slice(-period);
  const middle = slice.reduce((a, b) => a + b, 0) / period;
  const variance = slice.reduce((sum, p) => sum + Math.pow(p - middle, 2), 0) / period;
  const std = Math.sqrt(variance);
  return {
    upper: middle + stdDev * std,
    middle,
    lower: middle - stdDev * std,
    width: (2 * stdDev * std) / middle // 带宽，用于判断张口/收口
  };
}

/**
 * 判断均线排列
 * @param {Object} mas {ma5, ma10, ma30, ma60}
 * @returns {string} 'bull'|'bear'|'neutral'
 */
function checkMAStructure(mas) {
  const { ma5, ma10, ma30, ma60 } = mas;
  if (!ma5 || !ma10 || !ma30 || !ma60) return 'neutral';
  if (ma5 > ma10 && ma10 > ma30 && ma30 > ma60) return 'bull'; // 多头排列
  if (ma5 < ma10 && ma10 < ma30 && ma30 < ma60) return 'bear'; // 空头排列
  return 'neutral';
}

/**
 * 判断布林带形态
 * @param {Array} bandwidths 带宽数组（历史）
 * @returns {string} 'expanding_up'|'expanding_down'|'contracting'|'stable'
 */
function checkBollingerPattern(bandwidths) {
  if (bandwidths.length < 3) return 'stable';
  const recent = bandwidths.slice(-3);
  const trend = recent[2] - recent[0]; // 带宽变化趋势
  if (trend > 0.05) return 'expanding_up';  // 张口向上
  if (trend < -0.05) return 'expanding_down'; // 张口向下
  if (Math.max(...recent) - Math.min(...recent) < 0.02) return 'contracting'; // 收口
  return 'stable';
}

/**
 * 识别十字星形态
 * @param {Object} candle {open, close, high, low}
 * @returns {boolean} 是否为十字星
 */
function isDoji(candle) {
  if (!candle) return false;
  const { open, close, high, low } = candle;
  const body = Math.abs(close - open);
  const range = high - low;
  if (range === 0) return false;
  return body / range < 0.1; // 实体小于振幅的10%
}

/**
 * 识别启明十字星（底部）
 * @param {Array} candles 最近3根K线
 * @returns {boolean}
 */
function isMorningDoji(candles) {
  if (candles.length < 3) return false;
  const [prev2, prev1, curr] = candles.slice(-3);
  // 前两根下跌，当前是十字星，收盘高于前一根开盘
  const isDowntrend = prev2.close < prev2.open && prev1.close < prev1.open;
  return isDowntrend && isDoji(curr) && curr.close > prev1.open;
}

/**
 * 识别黄昏十字星（顶部）
 * @param {Array} candles 最近3根K线
 * @returns {boolean}
 */
function isEveningDoji(candles) {
  if (candles.length < 3) return false;
  const [prev2, prev1, curr] = candles.slice(-3);
  // 前两根上涨，当前是十字星，收盘低于前一根开盘
  const isUptrend = prev2.close > prev2.open && prev1.close > prev1.open;
  return isUptrend && isDoji(curr) && curr.close < prev1.open;
}

/**
 * 获取技术分析信号
 * @param {Object} params {price, prices, candles, maStructure, bollinger}
 * @returns {Object} {signal, reason, strength}
 */
function getTechSignal({ price, prices = [], candles = [], maStructure, bollinger }) {
  let signal = 'neutral';
  let reason = '';
  let strength = 0;
  
  // 均线排列信号
  if (maStructure === 'bull') {
    signal = 'bullish';
    reason = '均线多头排列';
    strength = 2;
  } else if (maStructure === 'bear') {
    signal = 'bearish';
    reason = '均线空头排列';
    strength = -2;
  }
  
  // 布林带位置信号
  if (bollinger.lower && price <= bollinger.lower * 1.02) {
    // 价格触及下轨
    if (signal !== 'bearish') {
      signal = 'support';
      reason = '触及布林下轨，可能有支撑';
      strength = 1;
    }
  } else if (bollinger.upper && price >= bollinger.upper * 0.98) {
    // 价格触及上轨
    if (signal !== 'bullish') {
      signal = 'resistance';
      reason = '触及布林上轨，可能回调';
      strength = -1;
    }
  }
  
  // 十字星信号
  if (isMorningDoji(candles)) {
    signal = 'buy';
    reason = '启明十字星，见底信号';
    strength = 3;
  } else if (isEveningDoji(candles)) {
    signal = 'sell';
    reason = '黄昏十字星，见顶信号';
    strength = -3;
  } else if (isDoji(candles[candles.length - 1])) {
    if (!reason) reason = '十字星形态，多空平衡';
  }
  
  return { signal, reason, strength };
}

// ═══════════════ PORTFOLIO ANALYSIS ═══════════════
function renderAnalysis() {
  const container = document.getElementById('analysisGrid');
  if (!container) return;

  const items = H || [];
  if (!items || items.length === 0) {
    container.innerHTML = '<div style="text-align:center;color:var(--text3);padding:40px;font-size:13px">暂无持仓数据</div>';
    return;
  }


  // Build name → is recommended
  const allRecs = (recData?.all || []);
  const recSet = new Set(allRecs.map(r => r.name));

  // Get market recommendations for comparison signals
  const recs = window.recData || {};
  const recNames = new Set(
    (recs.all || []).map(r => r.name)
  );
  const rateMap = window._rateMap || {};

  // ── Per-item analysis ──
  const analyses = items.map(item => {
    const name = item.n;
    const cost = item.c;
    const price = item.p;
    const pnl = price - cost;
    const pnlPct = cost > 0 ? (pnl / cost * 100) : 0;

    // 优先使用持仓自带的rate数据（update.py已写入）
    // fallback到alerts匹配
    const r1 = item.rate_1 !== undefined ? item.rate_1 : (rateMap[name]?.r1 || 0);
    const r7 = item.rate_7 !== undefined ? item.rate_7 : (rateMap[name]?.r7 || 0);
    const r30 = item.rate_30 !== undefined ? item.rate_30 : (rateMap[name]?.r30 || 0);

    const isRec = recSet.has(name);

    // ── 技术分析（需要历史数据）──
    const priceHistory = item.price_history || [];
    const prices = priceHistory.map(h => h.price);
    const hasTechData = prices.length >= 5;
    
    // 计算均线（需要至少对应周期的数据）
    const mas = {
      ma5: prices.length >= 5 ? calcMA(prices, 5) : null,
      ma10: prices.length >= 10 ? calcMA(prices, 10) : null,
      ma30: prices.length >= 30 ? calcMA(prices, 30) : null,
      ma60: prices.length >= 60 ? calcMA(prices, 60) : null
    };
    
    // 计算布林带（需要至少10天数据）
    const bollinger = prices.length >= 10 ? calcBollingerBands(prices, 10, 2) : { upper: null, middle: null, lower: null, width: null };
    
    // 均线排列
    const maStructure = checkMAStructure(mas);
    
    // 技术信号
    const techSignal = hasTechData ? getTechSignal({ price, prices, mas, bollinger }) : { signal: 'neutral', reason: '', strength: 0 };

    // ── Trend determination (分数制) ──
    let trendScore = 0;
    // 7日涨跌权重最大
    if (r7 > 0) trendScore += Math.min(r7 * 2, 30);
    else trendScore += Math.max(r7 * 2, -30);
    // 30日趋势辅助判断
    if (r30 > 0) trendScore += Math.min(r30, 15);
    else trendScore += Math.max(r30, -15);
    // 1日短线动量
    if (r1 > 0) trendScore += Math.min(r1 * 3, 10);
    else trendScore += Math.max(r1 * 3, -10);
    // 均线结构加分
    if (maStructure === 'bull') trendScore += 10;
    else if (maStructure === 'bear') trendScore -= 10;
    // 触布林带下轨（超卖）加分，触上轨（超买）减分
    if (bollinger.lower && price <= bollinger.lower * 1.02) trendScore += 8;
    if (bollinger.upper && price >= bollinger.upper * 0.98) trendScore -= 8;

    let trend = 'neutral';
    if (trendScore >= 20) trend = 'strong_up';
    else if (trendScore >= 8) trend = 'up';
    else if (trendScore <= -20) trend = 'weak';
    else if (trendScore <= -8) trend = 'rebound';  // 弱→反弹看后续确认

    // 用技术分析微调
    if (techSignal.signal === 'bullish' && trendScore < 20) trendScore += 5;
    if (techSignal.signal === 'bearish' && trendScore > -20) trendScore -= 5;

    // ── Sell signal ──
    let sellSignal = '持有';
    let sellReason = '';
    
    // 技术分析信号优先（如黄昏十字星）
    if (techSignal.signal === 'sell') {
      sellSignal = '技术卖';
      sellReason = techSignal.reason;
    } else if (techSignal.signal === 'buy') {
      sellSignal = '技术买';
      sellReason = techSignal.reason;
    } else if (pnlPct >= 30) { 
      sellSignal = '止盈'; sellReason = '盈利已达30%，可考虑分批止盈'; 
    } else if (pnlPct <= -15) { 
      sellSignal = '止损'; sellReason = '浮亏超15%，风险较大，建议止损换品'; 
    } else if (isRec) { 
      sellSignal = '持有观察'; sellReason = '属于推荐品类，可继续持有观察'; 
    } else if (trendScore <= -15 && pnlPct < -3) { 
      sellSignal = '减仓'; sellReason = '趋势走弱' + (r7 <= -8 ? '，7日跌幅较大' : '') + '，建议控制仓位'; 
    } else if (trend === 'rebound' && pnlPct > 5) { 
      sellSignal = '反弹卖'; sellReason = '属于超跌反弹，建议趁反弹卖出锁定收益'; 
    } else if (trend === 'neutral' && pnlPct < -5) { 
      sellSignal = '观望'; sellReason = '短期方向不明，亏损不大可等待反弹'; 
    } else if (techSignal.reason) {
      // 有技术信号但未触发买卖
      sellReason = techSignal.reason;
    }

    // ── Future outlook ──
    let outlook = '';
    let outlookColor = 'var(--text3)';
    if (trend === 'strong_up') { outlook = '📈 强势上升'; outlookColor = 'var(--rise)'; }
    else if (trend === 'up') { outlook = '↗ 温和上涨'; outlookColor = '#86efac'; }
    else if (trend === 'rebound') { outlook = '↙ 超跌反弹'; outlookColor = 'var(--amber)'; }
    else if (trend === 'weak') { outlook = '📉 下行通道'; outlookColor = 'var(--fall)'; }
    else { outlook = '→ 横盘整理'; outlookColor = 'var(--text3)'; }

    // ── Target price range (基于实际波动率) ──
    let targetLow = '', targetHigh = '';
    // 用历史价格估算日均波动率
    let dailyVol = 0.03; // 默认3%
    if (prices.length >= 5) {
      var returns = [];
      for (var vi = 1; vi < prices.length; vi++) {
        if (prices[vi-1] > 0) returns.push(Math.abs(prices[vi] - prices[vi-1]) / prices[vi-1]);
      }
      if (returns.length > 0) {
        var avgRet = returns.reduce(function(a,b){return a+b;}, 0) / returns.length;
        dailyVol = Math.min(Math.max(avgRet, 0.01), 0.15); // 1%-15%之间
      }
    }
    // 30天波动范围 = 日均波动率 * sqrt(30)
    var monthVol = dailyVol * Math.sqrt(30);
    if (trendScore > 0) {
      targetLow = (price * (1 - monthVol * 0.5)).toFixed(0);
      targetHigh = (price * (1 + monthVol)).toFixed(0);
    } else if (trendScore < -8) {
      targetLow = (price * (1 - monthVol * 1.2)).toFixed(0);
      targetHigh = (price * (1 + monthVol * 0.3)).toFixed(0);
    } else {
      targetLow = (price * (1 - monthVol * 0.6)).toFixed(0);
      targetHigh = (price * (1 + monthVol * 0.6)).toFixed(0);
    }

    // ── Confidence ──
    // 可信度基于数据质量和管理方向一致性
    let confidence = '低';
    let confColor = 'var(--text3)';
    const histLen = (item.price_history || []).length;
    if (histLen >= 7) {
      // 历史数据充足 + 均线/短线方向一致 → 高可信
      if (Math.abs(trendScore) >= 15) { confidence = '高'; confColor = 'var(--rise)'; }
      else { confidence = '中'; confColor = 'var(--amber)'; }
    } else if (histLen >= 2) { confidence = '中'; confColor = 'var(--amber)'; }
    // 1天都不到 → 低

    // ── 技术分析摘要 ──
    let techSummary = '';
    if (hasTechData) {
      const parts = [];
      if (maStructure === 'bull') parts.push('多头排列');
      else if (maStructure === 'bear') parts.push('空头排列');
      if (bollinger.lower && price <= bollinger.lower * 1.02) parts.push('触下轨');
      if (bollinger.upper && price >= bollinger.upper * 0.98) parts.push('触上轨');
      if (techSignal.reason) parts.push(techSignal.reason);
      techSummary = parts.join(' · ') || '正常区间';
    }

    return {
      name, cost, price, pnl, pnlPct,
      r1, r7, r30, isRec,
      trend, sellSignal, sellReason, outlook, outlookColor,
      targetLow, targetHigh,
      confidence, confColor,
      // 技术分析数据
      hasTechData,
      ma5: mas.ma5, ma10: mas.ma10, ma30: mas.ma30, ma60: mas.ma60,
      maStructure,
      bollUpper: bollinger.upper, bollMiddle: bollinger.middle, bollLower: bollinger.lower,
      techSignal: techSignal.signal,
      techSummary
    };
  });

  // Sort by: sell signals first (止损 > 止盈 > 反弹卖), then by 7-day change
  const signalOrder = { '止损': 0, '止盈': 1, '反弹卖': 2, '减仓': 3, '观望': 4, '持有观察': 5, '持有': 6 };
  analyses.sort((a, b) => {
    const oa = signalOrder[a.sellSignal] ?? 9;
    const ob = signalOrder[b.sellSignal] ?? 9;
    if (oa !== ob) return oa - ob;
    return a.r7 - b.r7;
  });

  // ── Generate HTML ──
  const TREND_COLORS = {
    'strong_up': 'var(--rise)',
    'up': '#86efac',
    'rebound': 'var(--amber)',
    'weak': 'var(--fall)',
    'neutral': 'var(--text3)'
  };
  const SIGNAL_COLORS = {
    '止损': '#f87171',
    '止盈': '#4ade80',
    '反弹卖': 'var(--amber)',
    '减仓': '#fb923c',
    '观望': 'var(--text2)',
    '持有观察': 'var(--blue)',
    '技术卖': '#f87171',
    '技术买': '#4ade80',
    '持有': 'var(--text3)'
  };

  container.innerHTML = analyses.map(a => {
    // Determine badge class
    let badgeCls = 'ac-badge';
    if (a.sellSignal === '止盈' || a.sellSignal === '技术买') badgeCls += ' buy';
    else if (a.sellSignal === '止损' || a.sellSignal === '减仓' || a.sellSignal === '反弹卖') badgeCls += ' sell';
    else if (a.sellSignal === '持有观察' || a.sellSignal === '技术卖') badgeCls += ' wait';
    else if (a.sellSignal === '观望') badgeCls += ' stop';
    // Card PnL class
    let cardCls = a.pnl >= 0 ? ' analysis-card rise' : 'analysis-card fall';
    // Reason class
    let reasonCls = a.pnl >= 0 ? 'ac-reason buy' : 'ac-reason sell';
    return `
    <div class="${cardCls}">
      <div class="ac-header">
        <span class="ac-name" title="${a.name}">${a.name.length > 22 ? a.name.substring(0, 20) + '…' : a.name}</span>
        <span class="${badgeCls}">${a.sellSignal}</span>
      </div>
      <div class="ac-metrics">
        <div class="ac-m"><span class="ac-ml">现价</span><span class="ac-mv mono">¥${a.price.toFixed(0)}</span></div>
        <div class="ac-m"><span class="ac-ml">成本</span><span class="ac-mv mono">¥${a.cost.toFixed(0)}</span></div>
        <div class="ac-m"><span class="ac-ml">1日</span><span class="ac-mv mono" style="color:${a.r1 >= 0 ? 'var(--rise)' : 'var(--fall)'}">${a.r1 >= 0 ? '+' : ''}${a.r1.toFixed(1)}%</span></div>
        <div class="ac-m"><span class="ac-ml">7日</span><span class="ac-mv mono" style="color:${a.r7 >= 0 ? 'var(--rise)' : 'var(--fall)'}">${a.r7 >= 0 ? '+' : ''}${a.r7.toFixed(1)}%</span></div>
      </div>
      <div class="ac-row">
        <span class="ac-label">盈亏</span>
        <span style="color:${a.pnl >= 0 ? 'var(--rise)' : 'var(--fall)'};font-size:14px;font-weight:800;font-family:DM Mono,monospace">${a.pnl >= 0 ? '+' : ''}¥${a.pnl.toFixed(0)} (${a.pnlPct >= 0 ? '+' : ''}${a.pnlPct.toFixed(1)}%)</span>
      </div>
      <div class="ac-row">
        <span class="ac-label">走势 · ${a.outlook}</span>
        <span style="color:${a.outlookColor};font-size:12px;font-weight:600">${a.isRec ? '📌 推荐' : ''}</span>
      </div>
      ${a.sellReason ? '<div class="' + reasonCls + '">' + a.sellReason + '</div>' : ''}
    </div>`;
  }).join('');

  // Also inject analysis data for KPI
  updateAnalysisKPI(analyses);
}

// Inject analysis indicators into KPI strip
function updateAnalysisKPI(analyses) {
  // No KPI strip to update for now, analysis is its own section
}

// ═══════════════ 全市场扫描 ═══════════════
function renderScan() {
  fetch('market_scan.json?_t=' + Date.now()).then(function(r) { return r.ok ? r.json() : null; }).then(function(scan) {
    window._marketScan = scan || {};
    if (!scan) return;
    var kpis = document.getElementById('scanKpis');
    var gainers = document.getElementById('scanGainers');
    var losers = document.getElementById('scanLosers');

    // ═══ Hero KPI ───
    if (kpis) {
      var trackedPct = scan.total > 0 ? (scan.tracked / scan.total * 100) : 0;
      // 更新副标题
      var sub = document.getElementById('scanSubtitle');
      if (sub) sub.textContent = (scan.total||0).toLocaleString() + '件 · 武器/刀/手套/探员';
      kpis.innerHTML =
        '<div class="kpi-card k-accent"><div class="k-label">全量饰品</div><div class="k-value">' + (scan.total || 0).toLocaleString() + '</div><div class="k-sub">' + (scan.tracked||0).toLocaleString() + '个追踪 (' + trackedPct.toFixed(1) + '%)</div></div>' +
        '<div class="kpi-card"><div class="k-label">均价</div><div class="k-value">¥' + (scan.avg_p||0).toFixed(0) + '</div><div class="k-sub">中位¥' + (scan.median_p||0).toFixed(0) + '</div></div>' +
        '<div class="kpi-card"><div class="k-label">最高价</div><div class="k-value">¥' + (scan.max_p||0).toFixed(0) + '</div><div class="k-sub">最低¥' + (scan.min_p||0).toFixed(2) + '</div></div>' +
        '<div class="kpi-card"><div class="k-label">品类</div><div class="k-value">' + (scan.categories ? Object.keys(scan.categories).length : 0) + '</div><div class="k-sub">武器+刀+手套+贴纸等</div></div>';
    }

    // ═══ 涨跌榜 ───
    if (gainers && scan.movers && scan.movers.gainers) {
      var maxR = Math.max.apply(null, scan.movers.gainers.map(function(g){return g.r7||0;})) || 1;
      var html = '<div class="scan-card-head rise">📈 24h涨幅 TOP ' + scan.movers.gainers.length + '</div>';
      scan.movers.gainers.forEach(function(g, i) {
        var barW = Math.max(8, (g.r7 / maxR * 100).toFixed(0));
        html += '<div class="scan-row">' +
          '<span class="scan-rank">' + (i+1) + '</span>' +
          '<span class="scan-name" title="' + esc(g.n) + '">' + esc(g.n) + '</span>' +
          '<span class="scan-pct rise">+' + g.r7.toFixed(1) + '%</span>' +
          '<span class="scan-bar"><span class="scan-bar-fill rise" style="width:' + barW + '%"></span></span>' +
        '</div>';
      });
      gainers.innerHTML = html;
    }
    if (losers && scan.movers && scan.movers.losers) {
      var maxR = Math.abs(Math.min.apply(null, scan.movers.losers.map(function(l){return l.r7||0;}))) || 1;
      var html = '<div class="scan-card-head fall">📉 24h跌幅 TOP ' + scan.movers.losers.length + '</div>';
      scan.movers.losers.forEach(function(l, i) {
        var barW = Math.max(8, (Math.abs(l.r7) / maxR * 100).toFixed(0));
        html += '<div class="scan-row">' +
          '<span class="scan-rank">' + (i+1) + '</span>' +
          '<span class="scan-name" title="' + esc(l.n) + '">' + esc(l.n) + '</span>' +
          '<span class="scan-pct fall">' + l.r7.toFixed(1) + '%</span>' +
          '<span class="scan-bar"><span class="scan-bar-fill fall" style="width:' + barW + '%"></span></span>' +
        '</div>';
      });
      losers.innerHTML = html;
    }

    var ut = document.getElementById('scanUpdateTime');
    if (ut && scan.updated) ut.textContent = '数据 ' + scan.updated.slice(0, 10);
    // 触发AI研判更新
    if (window._aiAnalysis && Object.keys(window._aiAnalysis).length) generateAIInsight();
  }).catch(function() {});
}

// ═══════════════ START ═══════════════
updateWatchCount();
loadAll().catch(err => { console.error(err); hideSkeleton(); });

// ═══════════════ 自定义持仓管理 ═══════════════
const CUSTOM_HOLDINGS_KEY = 'cs2_custom_holdings';
const HIDDEN_ITEMS_KEY = 'cs2_hidden_items';
const SOLD_ITEMS_KEY = 'cs2_sold_items';

function loadCustomHoldings() {
  try {
    const saved = localStorage.getItem(CUSTOM_HOLDINGS_KEY);
    return saved ? JSON.parse(saved) : [];
  } catch(e) { return []; }
}

function saveCustomHoldings(items) {
  try { localStorage.setItem(CUSTOM_HOLDINGS_KEY, JSON.stringify(items)); } catch(e) {}
}

function loadHiddenItems() {
  try {
    const saved = localStorage.getItem(HIDDEN_ITEMS_KEY);
    return saved ? JSON.parse(saved) : [];
  } catch(e) { return []; }
}

function saveHiddenItems(items) {
  try { localStorage.setItem(HIDDEN_ITEMS_KEY, JSON.stringify(items)); } catch(e) {}
}

function loadSoldItems() {
  // 优先从 localStorage 读取（快速、同步）
  try {
    const saved = localStorage.getItem(SOLD_ITEMS_KEY);
    return saved ? JSON.parse(saved) : [];
  } catch(e) { return []; }
}

function saveSoldItems(items) {
  // 先写本地（即时生效）
  try { localStorage.setItem(SOLD_ITEMS_KEY, JSON.stringify(items)); } catch(e) {}
  // 再异步推送到 Worker（跨设备持久化）
  if (items.length > 0) {
    var last = items[items.length - 1];
    try {
      fetch(WORKER_BASE + '/api/sold', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(last),
      }).catch(function(){});
    } catch(e) {}
  }
}

// Add custom holdings to H on load (must be called after H is populated)
function mergeCustomHoldings() {
  var customs = loadCustomHoldings();
  customs.forEach(function(c) {
    // Check if already exists (by unique name + wear)
    var exists = H.some(function(h) { return h.n === c.n && h.w === c.w; });
    if (!exists) {
      H.push({
        n: c.n, w: c.w || 'FN', c: c.c || 0, p: c.p || 0,
        gid: 0, mh: '', pnl: 0, pnlPct: 0,
        _custom: true
      });
    }
  });
}

// Filter out hidden items
function filterHidden() {
  var hidden = loadHiddenItems();
  if (hidden.length === 0) return;
  H = H.filter(function(h) {
    return !hidden.some(function(hh) { return hh.n === h.n && hh.w === h.w; });
  });
  window.H = H;  // filter 创建了新数组，更新全局引用
}

// Setup add item button
var addBtn = document.getElementById('addItemBtn');
if (addBtn) {
  addBtn.addEventListener('click', function() {
    var overlay = document.getElementById('addItemOverlay');
    if (overlay) { overlay.classList.add('show'); document.getElementById('addItemName').focus(); }
  });
}

// Setup add item modal
(function() {
  var overlay = document.getElementById('addItemOverlay');
  if (!overlay) return;
  overlay.addEventListener('click', function(e) {
    if (e.target === overlay) overlay.classList.remove('show');
  });
  document.getElementById('addItemCancel').onclick = function() { overlay.classList.remove('show'); };
  document.getElementById('addItemConfirm').onclick = function() {
    var name = document.getElementById('addItemName').value.trim();
    var wear = document.getElementById('addItemWear').value;
    var cost = parseFloat(document.getElementById('addItemCost').value) || 0;
    if (!name) { alert('请输入饰品名称'); return; }
    var customs = loadCustomHoldings();
    customs.push({ n: name, w: wear, c: cost, p: cost });
    saveCustomHoldings(customs);
    overlay.classList.remove('show');
    // Clear inputs
    document.getElementById('addItemName').value = '';
    document.getElementById('addItemCost').value = '';
    loadAll();
  };
})();

// ── 生成单件饰品的分析 HTML ──
function buildItemAnalysisHTML(item) {
  if (!item) return '';
  const name = item.n, cost = item.c, price = item.p;
  const pnl = price - cost, pnlPct = cost > 0 ? (pnl / cost * 100) : 0;
  const rateMap = window._rateMap || {};
  const r1 = item.rate_1 !== undefined ? item.rate_1 : (rateMap[name]?.r1 || 0);
  const r7 = item.rate_7 !== undefined ? item.rate_7 : (rateMap[name]?.r7 || 0);
  const r30 = item.rate_30 !== undefined ? item.rate_30 : (rateMap[name]?.r30 || 0);
  const allRecs = (window.recData?.all || []);
  const isRec = allRecs.some(function(r) { return r.name === name; });

  // ── BUFF 市场深度分析 ──
  var buffSell = item.buff_sell || 0;
  var buffBuy = item.buff_buy || 0;
  var buffSellNum = item.buff_sell_num || 0;
  var buffBuyNum = item.buff_buy_num || 0;
  var hasBuff = buffSell > 0;
  var hasBuffBuy = buffBuy > 0;
  var spread = 0, spreadRate = 0;
  if (hasBuff && hasBuffBuy) {
    spread = buffSell - buffBuy;
    spreadRate = buffBuy > 0 ? (spread / buffBuy * 100) : 0;
  }
  var ecoVsBuff = hasBuff ? ((price - buffSell) / buffSell * 100) : 0;

  // ── 流动性评估 ──
  var liq = '正常';
  var liqColor = 'var(--text2)';
  var supplyDemand = '';
  if (hasBuff && hasBuffBuy) {
    var totalDepth = buffSellNum + buffBuyNum;
    if (totalDepth > 0) {
      var ratio = buffBuyNum / buffSellNum; // 求购/在售比
      if (ratio > 2) supplyDemand = '求购旺盛';
      else if (ratio > 1) supplyDemand = '需求偏强';
      else if (ratio > 0.5) supplyDemand = '供需平衡';
      else supplyDemand = '供大于求';
    }
    if (spreadRate < 3 && buffBuyNum > 10) { liq = '活跃'; liqColor = 'var(--fall)'; }
    else if (spreadRate > 8 || (buffSellNum > 100 && buffBuyNum < 5)) { liq = '较差'; liqColor = 'var(--rise)'; }
  } else if (hasBuff) {
    liq = '一般'; liqColor = 'var(--amber)';
  }

  // ── BUFF 溢价分析 ──
  var buffPremium = '';
  var buffPremiumColor = '';
  if (hasBuff) {
    if (ecoVsBuff < -2) { buffPremium = 'BUFF溢价' + Math.abs(ecoVsBuff).toFixed(1) + '%'; buffPremiumColor = 'var(--fall)'; }
    else if (ecoVsBuff > 2) { buffPremium = 'ECO溢价' + ecoVsBuff.toFixed(1) + '%'; buffPremiumColor = 'var(--rise)'; }
    else { buffPremium = '价格持平'; buffPremiumColor = 'var(--text3)'; }
  }

  // ── Trend ──
  var trend = 'neutral', trendLabel = '→ 横盘整理', trendColor = 'var(--text3)';
  if (r7 >= 5 && r1 >= 1) { trend = 'strong_up'; trendLabel = '📈 强势上升'; trendColor = 'var(--rise)'; }
  else if (r7 >= 2 && r1 >= 0.5) { trend = 'up'; trendLabel = '↗ 温和上涨'; trendColor = '#86efac'; }
  else if (r7 <= -5) { trend = 'weak'; trendLabel = '📉 下行通道'; trendColor = 'var(--fall)'; }
  else if (r7 >= -1 && r1 <= -1) { trend = 'rebound'; trendLabel = '↙ 超跌反弹'; trendColor = 'var(--amber)'; }
  // 趋势 + 流动性修正
  if (trend === 'weak' && liq === '活跃') { trendLabel = '📉 缩量下跌'; }
  if (trend === 'up' && liq === '较差') { trendLabel = '↗ 有价无市'; trendColor = 'var(--amber)'; }

  // ── 智能信号判断 ──
  var sellSignal = '持有', sellReason = '';
  // 多维评分：-5 ~ +5
  var score = 0;
  if (r7 > 0) score += 1;
  if (r1 > 0) score += 1;
  if (r30 > 0) score += 1;
  if (pnlPct > 20) score += 1;  // 盈利多加分
  if (pnlPct < -10) score -= 1; // 亏损大减分
  if (isRec) score += 1;
  if (liq === '活跃') score += 1;
  if (liq === '较差') score -= 1;
  if (hasBuffBuy && buffBuy > price * 0.95) score += 1; // 求购价接近市价 → 需求好
  if (hasBuff && ecoVsBuff > 3) score -= 1; // ECO价比BUFF贵 → 可能买贵了
  // 供需加分
  if (supplyDemand === '求购旺盛') score += 1;
  if (buffBuyNum > buffSellNum && buffSellNum > 0) score += 1; // 求购量 > 在售量
  // 悠悠数据加分
  var yyypSell = item.yyyp_sell || 0;
  var yyypSellNum = item.yyyp_sell_num || 0;
  if (yyypSell > 0 && price > 0 && yyypSell > price * 1.02) score += 1; // 悠悠溢价→看好
  if (yyypSellNum > 0 && yyypSellNum < 100) score += 1; // 悠悠在售少→稀缺
  if (yyypSellNum > 0 && yyypSellNum > 500) score -= 0.5; // 在售太多→供过于求

  // ── 生成信号 ──
  if (score >= 3) {
    sellSignal = '强势';
    var parts = [];
    if (trend === 'strong_up') parts.push('量价齐升');
    if (liq === '活跃') parts.push('流动性好');
    if (hasBuffBuy) parts.push('求购强劲');
    sellReason = parts.length > 0 ? '✅ ' + parts.join('，') + '，可继续持有' : '✅ 综合表现强势，继续持有';
  } else if (score >= 1) {
    sellSignal = '持有';
    var hints = [];
    if (trend === 'up') hints.push('趋势偏暖');
    if (liq === '活跃') hints.push('交投活跃');
    if (pnlPct > 10) hints.push('浮盈可观');
    if (isRec) hints.push('推荐品类');
    sellReason = hints.length > 0 ? '📊 ' + hints.join('，') + '，暂时持有观察' : '📊 基本面正常，继续持有';
  } else if (score >= -1) {
    sellSignal = '观望';
    if (pnlPct < -5 && r7 < -3) sellReason = '⏳ 短期承压，但观察是否有资金回补，暂不建议割肉';
    else if (r7 > 0 && pnlPct < 0) sellReason = '⏳ 价格在回暖，浮亏有望收窄，再观察几天';
    else if (r7 < 0 && liq === '活跃') sellReason = '⏳ 下跌但流动性尚可，可能有短线机会';
    else sellReason = '⏳ 方向不明，等待信号明确再做决定';
  } else {
    sellSignal = '谨慎';
    var warns = [];
    if (pnlPct < -10) warns.push('浮亏较深');
    if (trend === 'weak') warns.push('趋势偏弱');
    if (liq === '较差') warns.push('流动性差');
    if (r7 < -8) warns.push('加速下跌');
    sellReason = '⚠ ' + (warns.length > 0 ? warns.join('，') + '，' : '') + '建议分批减仓降低风险，保留现金等机会';
  }

  // ── 目标价（基于 BUFF 数据校准）──
  var basePrice = hasBuff ? buffSell : price;
  var targetLow, targetHigh;
  if (trend === 'weak') {
    targetLow = (basePrice * 0.92).toFixed(0);
    targetHigh = (basePrice * 1.03).toFixed(0);
  } else if (trend === 'strong_up') {
    targetLow = (basePrice * 1.03).toFixed(0);
    targetHigh = (basePrice * 1.15).toFixed(0);
  } else {
    targetLow = (basePrice * 0.97).toFixed(0);
    targetHigh = (basePrice * 1.08).toFixed(0);
  }

  var histLen = (item.price_history || []).length;
  var confidence = histLen >= 7 ? '高' : histLen >= 2 ? '中' : '低';
  var confColor = histLen >= 7 ? 'var(--fall)' : histLen >= 2 ? 'var(--amber)' : 'var(--text3)';

  var badgeCls = 'ac-badge';
  if (sellSignal === '强势') badgeCls += ' buy';
  else if (sellSignal === '谨慎') badgeCls += ' sell';
  else if (sellSignal === '观望') badgeCls += ' stop';
  else badgeCls += ' wait';

  // ── 价格来源 & 备选平台 ──
  var sourceLabel = hasBuff ? (item.buff_source || 'BUFF') : '';
  var yyypSell = item.yyyp_sell || 0;
  var yyypSellNum = item.yyyp_sell_num || 0;
  // 检查 platforms 中有没有其他有价格的平台做备选
  var platforms = item.platforms || {};
  var altPlatforms = '';
  if (!hasBuff && Object.keys(platforms).length > 0) {
    var alts = [];
    Object.keys(platforms).forEach(function(p) {
      var pd = platforms[p];
      if (pd && pd.sell > 0) alts.push(p + '¥' + pd.sell.toFixed(2));
    });
    if (alts.length > 0) altPlatforms = '<br><span style="font-size:10px;color:var(--amber)">备选: ' + alts.join(' / ') + '</span>';
  }
  var buffTag = hasBuff ? '<span style="font-size:10px;color:' + buffPremiumColor + ';margin-left:6px">' + buffPremium + '</span>' : '';
  var liqTag = hasBuff ? '<span style="font-size:10px;color:' + liqColor + ';margin-left:6px">流动性' + liq + '</span>' : '';

  // 折线图
  var ph = item.price_history || []
  var ecoPrices = ph.map(function(p){ return p.price; }).filter(Boolean)
  var chartHtml = ''
  if (ph.length > 0) {
    var chartW = 200, chartH = 36
    // ECO 折线
    var chartEco = window.sparkline(ecoPrices, 'var(--blue)', chartW, chartH)
    // BUFF 折线（从 buff_history 取）
    // buff_history.json 结构: {date: {item_name: {buff_sell, ...}}}
    var mh = item.mh || item.n || ''
    var bh = window._buffHistory || {}
    var buffPrices = []
    if (bh && mh) {
      var dates = Object.keys(bh).sort()
      dates.forEach(function(d) {
        if (bh[d] && bh[d][mh] && bh[d][mh].buff_sell) {
          buffPrices.push(bh[d][mh].buff_sell)
        }
      })
    }
    var chartBuff = window.sparkline(buffPrices, 'var(--rise)', chartW, chartH)
    if (chartEco || chartBuff) {
      chartHtml = '<div class="ra-chart" style="padding:6px 0 2px">' +
        (chartEco ? '<div style="display:flex;gap:6px;align-items:center;font-size:9px;color:var(--blue)">' + chartEco + '<span>ECO</span></div>' : '') +
        (chartBuff ? '<div style="display:flex;gap:6px;align-items:center;font-size:9px;color:var(--rise);margin-top:2px">' + chartBuff + '<span>BUFF</span></div>' : '') +
        '</div>'
    }
  }

  return '<div class="row-analysis-inner">' +
    '<div><div class="ra-label">趋势</div><div class="ra-val" style="color:' + trendColor + ';font-size:12px">' + trendLabel + '</div></div>' +
    '<div><div class="ra-label">信号</div><div class="ra-val"><span class="' + badgeCls + '" style="font-size:11px">' + sellSignal + '</span></div></div>' +
    '<div><div class="ra-label">涨跌率</div><div class="ra-val" style="font-size:12px"><span class="' + (r1 >= 0 ? 'clr-rise' : 'clr-fall') + '">' + (r1 >= 0 ? '+' : '') + r1.toFixed(1) + '%</span> · <span class="' + (r7 >= 0 ? 'clr-rise' : 'clr-fall') + '">' + (r7 >= 0 ? '+' : '') + r7.toFixed(1) + '%</span> · <span class="' + (r30 >= 0 ? 'clr-rise' : 'clr-fall') + '">' + (r30 >= 0 ? '+' : '') + r30.toFixed(1) + '%</span></div></div>' +
    '<div><div class="ra-label">市场</div><div class="ra-val" style="font-size:12px"><span style="color:' + (hasBuff ? 'var(--fall)' : 'var(--text3)') + '">' + sourceLabel + '</span> 在售¥' + (hasBuff ? buffSell.toFixed(2) + '<sup style="font-size:8px;color:var(--rise);margin-left:1px">实时</sup>' : '--') + ' · 求购¥' + (hasBuffBuy ? buffBuy.toFixed(2) : '--') + buffTag + liqTag + '<br><span style="font-size:10px;color:var(--text3)">' + (hasBuff ? '▲' + buffBuyNum + '件求购 · ▼' + buffSellNum + '件在售' + (supplyDemand ? ' · ' + supplyDemand : '') : '暂无BUFF数据') + '</span>' + (yyypSell > 0 ? '<br><span style="font-size:10px;color:var(--amber)">悠悠 ¥' + yyypSell.toFixed(2) + '<sup style="font-size:8px;color:var(--rise);margin-left:1px">实时</sup>' + (yyypSellNum > 0 ? ' · ' + yyypSellNum + '件在售' : '') + '</span>' : '') + altPlatforms + '</div></div>' +
    chartHtml +
    '<div><div class="ra-label">盈亏 · 目标区间</div><div class="ra-val" style="font-size:12px"><span class="' + (pnl >= 0 ? 'clr-rise' : 'clr-fall') + '">' + (pnl >= 0 ? '+' : '') + '¥' + pnl.toFixed(2) + '</span> · ¥' + targetLow + '~¥' + targetHigh + ' <span style="font-size:10px;color:' + confColor + '">' + confidence + '置信</span></div></div>' +
    (sellReason ? '<div class="ra-reason' + (sellSignal === '强势' ? ' buy' : (sellSignal === '谨慎' ? ' sell' : '')) + '">' + sellReason + '</div>' : '') +
    (function() {
      // ── AI 智谱分析 ──
      var ai = window._aiAnalysis || {};
      var aiText = ai[name] || ai[item.mh || ''] || ai[item.market_hash_name || ''] || null;
      // 全量模糊匹配：去掉空格后查子串
      if (!aiText && name) {
        var aiKeys = Object.keys(ai).filter(function(k){ return !k.startsWith('_'); });
        var nameCompact = name.replace(/\s+/g,'');
        for (var ki = 0; ki < aiKeys.length; ki++) {
          var ak = aiKeys[ki];
          var akCompact = ak.replace(/\s+/g,'');
          // 双向包含：AK包含name或name包含AK
          if ((nameCompact.length >= 4 && akCompact.includes(nameCompact.substring(0,8))) ||
              (akCompact.length >= 4 && nameCompact.includes(akCompact.substring(0,8))) ||
              ak === name) {
            aiText = ai[ak];
            break;
          }
        }
      }
      // 如果 AI 数据还没加载
      if (!aiText) {
        var aiCount = Object.keys(ai).filter(function(k){ return !k.startsWith('_'); }).length;
        if (aiCount === 0) {
          // AI 文件还没下载完
          return '<div class="ra-reason" style="border-left-color:#a78bfa;margin-top:8px;background:linear-gradient(135deg,rgba(168,85,247,.06),rgba(59,130,246,.04));opacity:.85" id="ai-loading-row">' +
            '<div style="display:flex;align-items:center;gap:8px">' +
              '<span class="ai-spinner"></span>' +
              '<span style="font-size:11px;color:#c084fc;font-weight:600">AI 分析加载中...</span>' +
              '<button onclick="event.stopPropagation();var p=this.closest(\'.ra-reason\');if(p)p.innerHTML=\'<span style=font-size:11px;color:var(--text3)>AI 未就绪</span>\'" style="margin-left:auto;background:rgba(168,85,247,.15);color:#c084fc;border:1px solid rgba(168,85,247,.3);font-size:10px;padding:2px 8px;border-radius:6px;cursor:pointer">跳过</button>' +
            '</div></div>';
        }
        // AI 已加载但没匹配到
        return '<div class="ra-reason" style="border-left-color:#a78bfa;margin-top:8px;background:linear-gradient(135deg,rgba(168,85,247,.06),rgba(59,130,246,.04));opacity:.7">' +
          '<span style="font-size:11px;color:var(--text3)">🤖 暂无 AI 分析数据</span></div>';
      }
      var v, c, reason, risk;
      if (typeof aiText === 'object') {
        v = aiText.verdict || ''; c = aiText.confidence || 0;
        reason = aiText.reason || ''; risk = aiText.risk || '';
      } else {
        v = (aiText.match(/操作建议[:：]\s*(\S+)/)||[])[1]||'';
        c = parseInt((aiText.match(/置信度[:：]\s*(\d+)/)||[])[1]||'0');
        reason = (aiText.match(/核心逻辑[:：]\s*(.+)/)||[])[1]||'';
        risk = (aiText.match(/风险[:：]\s*(.+)/)||[])[1]||'';
      }
      var vc = v.includes('减仓')||v.includes('卖出') ? '#ff6b6b' : v.includes('持有')||v.includes('加仓') ? '#4ade80' : '#fbbf24';
      var vb = v.includes('减仓')||v.includes('卖出') ? 'rgba(255,107,107,.15)' : v.includes('持有')||v.includes('加仓') ? 'rgba(74,222,128,.15)' : 'rgba(251,191,36,.15)';
      return '<div style="margin-top:12px;border-radius:12px;overflow:hidden;border:1px solid rgba(168,85,247,.3);box-shadow:0 0 20px rgba(168,85,247,.08)">' +
        // 头部：AI 标识
        '<div style="background:linear-gradient(135deg,rgba(168,85,247,.25),rgba(99,102,241,.15));padding:10px 14px;display:flex;align-items:center;gap:10px">' +
          '<span style="font-size:12px;background:linear-gradient(135deg,#c084fc,#818cf8);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-weight:800">🤖 AI 持仓分析</span>' +
          '<span style="flex:1"></span>' +
          '<span style="font-size:14px;font-weight:800;color:' + vc + ';background:' + vb + ';padding:3px 12px;border-radius:6px">' + (v||'--') + '</span>' +
          '<span style="font-size:10px;color:var(--text3)">置信度 ' + (c||0) + '%</span>' +
        '</div>' +
        // 内容区
        '<div style="padding:12px 14px;display:flex;flex-direction:column;gap:10px">' +
          // 理由
          (reason ? '<div style="display:flex;gap:8px;align-items:flex-start">' +
            '<span style="font-size:14px;flex-shrink:0;margin-top:1px">💡</span>' +
            '<div style="flex:1"><div style="font-size:10px;color:var(--text3);margin-bottom:3px;font-weight:600;text-transform:uppercase;letter-spacing:.5px">分析理由</div>' +
            '<div style="font-size:12px;color:var(--text);line-height:1.6">' + reason + '</div></div>' +
          '</div>' : '') +
          // 风险
          (risk ? '<div style="display:flex;gap:8px;align-items:flex-start">' +
            '<span style="font-size:14px;flex-shrink:0;margin-top:1px">⚠️</span>' +
            '<div style="flex:1"><div style="font-size:10px;color:var(--text3);margin-bottom:3px;font-weight:600;text-transform:uppercase;letter-spacing:.5px">风险提示</div>' +
            '<div style="font-size:12px;color:#ff6b6b;line-height:1.6">' + risk + '</div></div>' +
          '</div>' : '') +
        '</div>' +
      '</div>';
      '</div>';
    })() +
    '</div>';
}

// Setup sell buttons via event delegation on tbody
var tbody = document.getElementById('tbody');
if (tbody) {
  tbody.addEventListener('click', function(e) {
    // Sell button
    var btn = e.target.closest('.sell-btn');
    if (btn) {
      var itemName = btn.dataset.name;
      var itemWear = btn.dataset.wear || '';
      // Find item by name + wear (stable lookup, not by index)
      var item = null;
    for (var i = 0; i < H.length; i++) {
      if (H[i].n === itemName && (H[i].w || '') === itemWear) {
        item = H[i];
        break;
      }
    }
    if (!item) return;
    // Show sell confirm modal with P&L stats
    var sOverlay = document.getElementById('sellConfirmOverlay');
    if (!sOverlay) return;
    document.getElementById('sellConfirmItem').textContent = item.n;
    document.getElementById('sellConfirmWear').textContent = item.w ? wearCN(item.w) : '--';
    document.getElementById('sellConfirmCost').textContent = '¥' + item.c.toFixed(2);
    document.getElementById('sellConfirmEco').textContent = '¥' + item.p.toFixed(2);
    document.getElementById('sellConfirmMulti').textContent = item.buff_sell > 0 ? '¥' + item.buff_sell.toFixed(2) : '--';
    var pnl = item.pnl || 0;
    var pnlPct = item.pnlPct || 0;
    var pnlCls = pnl >= 0 ? 'var(--rise)' : 'var(--fall)';
    document.getElementById('sellConfirmPnl').style.borderLeftColor = pnl >= 0 ? 'var(--rise)' : 'var(--fall)';
    document.getElementById('sellConfirmPnlVal').textContent = (pnl >= 0 ? '+' : '') + '¥' + pnl.toFixed(2);
    document.getElementById('sellConfirmPnlVal').style.color = pnl >= 0 ? 'var(--rise)' : 'var(--fall)';
    document.getElementById('sellConfirmPnlPct').textContent = (pnlPct >= 0 ? '+' : '') + pnlPct.toFixed(2) + '%';
    document.getElementById('sellConfirmPnlPct').style.color = pnl >= 0 ? 'var(--rise)' : 'var(--fall)';
    sOverlay._sellItem = item;
    sOverlay.classList.add('show');
    } // end if(btn)
  });
}

// Sell confirm modal handlers
(function(){
  var overlay = document.getElementById('sellConfirmOverlay');
  if (!overlay) return;
  overlay.addEventListener('click', function(e) {
    if (e.target === overlay) overlay.classList.remove('show');
  });
  document.getElementById('sellConfirmCancel').onclick = function() { overlay.classList.remove('show'); };
  document.getElementById('sellConfirmOk').onclick = function() {
    var item = overlay._sellItem;
    if (!item) return;
    // Record sold item with P&L
    var sold = loadSoldItems();
    sold.push({
      n: item.n, w: item.w, c: item.c, p: item.p,
      pnl: item.pnl || 0, pnlPct: item.pnlPct || 0,
      date: new Date().toLocaleString('zh-CN')
    });
    saveSoldItems(sold);
    if (item._custom) {
      var customs = loadCustomHoldings();
      customs = customs.filter(function(c) { return c.n !== item.n || c.w !== item.w; });
      saveCustomHoldings(customs);
    } else {
      var hidden = loadHiddenItems();
      hidden.push({ n: item.n, w: item.w });
      saveHiddenItems(hidden);
    }
    overlay.classList.remove('show');
    loadAll();
  };
})();

// Override loadAll to merge customs + filter hidden
var _origInitDashboard = initDashboard;
initDashboard = function() {
  mergeCustomHoldings();
  filterHidden();
  _origInitDashboard();
  invalidateCache();
  render();
  renderScan();
};

// ── 暴露接口到全局 ──
window.H = H;
window.recData = recData;
window.WEAR_MAP = WEAR_MAP;
window.CAT_MAP = CAT_MAP;
window.CAT_LABELS = CAT_LABELS;

})();
