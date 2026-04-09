/**
 * SteamDT 价格代理 Worker
 * 
 * 部署方式：
 * 1. 安装 Wrangler: npm install -g wrangler
 * 2. 登录: npx wrangler login
 * 3. 部署: npx wrangler deploy
 * 
 * 部署前需设置环境变量：
 * npx wrangler secret put STEAMDT_API_KEY
 * （输入你的 SteamDT API Key）
 */

const STEAMDT_BASE = 'https://open.steamdt.com/open/cs2';

// SteamDT API Key（通过 wrangler secret 设置，不写在代码里）
const getApiKey = () => ENVIRONMENT?.STEAMDT_API_KEY || '';

const JSON_HEADERS = {
  'Content-Type': 'application/json',
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
};

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // 预检请求
    if (request.method === 'OPTIONS') {
      return new Response(null, { headers: JSON_HEADERS });
    }

    // ── 路由分发 ──
    if (url.pathname === '/price/batch') {
      return handleBatchPrice(request, env);
    }
    if (url.pathname === '/price/single') {
      return handleSinglePrice(request, env);
    }
    if (url.pathname === '/kline') {
      return handleKline(request, env);
    }
    if (url.pathname === '/market/index') {
      return handleMarketIndex(request, env);
    }
    if (url.pathname === '/health') {
      return new Response(JSON.stringify({ ok: true, ts: Date.now() }), {
        headers: JSON_HEADERS,
      });
    }

    // 默认返回帮助信息
    return new Response(JSON.stringify({
      ok: true,
      routes: [
        'POST /price/batch    — 批量饰品价格（body: {marketHashNames:string[]}）',
        'GET  /price/single  — 单饰品价格（?name=xxx）',
        'POST /kline          — K线数据（body: {marketHashName,type}）',
        'GET  /market/index   — 大盘指数（等权6只饰品）',
        'GET  /health         — 健康检查',
      ],
    }), { headers: JSON_HEADERS });
  },
};

// ── 批量价格 ───────────────────────────────────────────────
async function handleBatchPrice(request, env) {
  const key = env.STEAMDT_API_KEY;
  if (!key) return json({ error: 'STEAMDT_API_KEY not configured' }, 500);

  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: 'Invalid JSON body' }, 400);
  }

  const { marketHashNames = [] } = body;
  if (!Array.isArray(marketHashNames) || marketHashNames.length === 0) {
    return json({ error: 'marketHashNames array required' }, 400);
  }

  // SteamDT 限制 100 个/批
  if (marketHashNames.length > 100) {
    return json({ error: 'Max 100 items per batch' }, 400);
  }

  try {
    const upstream = await fetch(`${STEAMDT_BASE}/v1/price/batch`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${key}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ marketHashNames }),
    });
    const data = await upstream.json();
    return json(data);
  } catch (e) {
    return json({ error: 'Upstream failed', detail: e.message }, 502);
  }
}

// ── 单品价格 ───────────────────────────────────────────────
async function handleSinglePrice(request, env) {
  const key = env.STEAMDT_API_KEY;
  if (!key) return json({ error: 'STEAMDT_API_KEY not configured' }, 500);

  const name = new URL(request.url).searchParams.get('name');
  if (!name) return json({ error: 'name query param required' }, 400);

  try {
    const upstream = await fetch(
      `${STEAMDT_BASE}/v1/price/single?marketHashName=${encodeURIComponent(name)}`,
      { headers: { 'Authorization': `Bearer ${key}` } }
    );
    const data = await upstream.json();
    return json(data);
  } catch (e) {
    return json({ error: 'Upstream failed', detail: e.message }, 502);
  }
}

// ── K线数据 ────────────────────────────────────────────────
async function handleKline(request, env) {
  const key = env.STEAMDT_API_KEY;
  if (!key) return json({ error: 'STEAMDT_API_KEY not configured' }, 500);

  let body;
  try {
    body = await request.json();
  } catch {
    return json({ error: 'Invalid JSON body' }, 400);
  }

  const { marketHashName, type = 2, platform = 'ALL', specialStyle } = body;
  if (!marketHashName) return json({ error: 'marketHashName required' }, 400);

  const params = new URLSearchParams({ marketHashName, type, platform });
  if (specialStyle) params.set('specialStyle', specialStyle);

  try {
    const upstream = await fetch(`${STEAMDT_BASE}/item/v1/kline?${params}`, {
      headers: { 'Authorization': `Bearer ${key}` },
    });
    const data = await upstream.json();
    return json(data);
  } catch (e) {
    return json({ error: 'Upstream failed', detail: e.message }, 502);
  }
}

// ── 大盘指数 ───────────────────────────────────────────────
async function handleMarketIndex(request, env) {
  const key = env.STEAMDT_API_KEY;
  if (!key) return json({ error: 'STEAMDT_API_KEY not configured' }, 500);

  // 6只热门饰品（等权）
  const ITEMS = [
    'AK-47 Redline',
    'M4A1-Silencer Classic',
    'AWP Dragon Lore',
    'Desert Eagle Blaze',
    'AK-47 Fire Serpent',
    'M4A4 Howl',
  ];

  const MARKET_NAMES = [
    'AK-47 - Redline (Field-Tested)',
    'M4A1-Silencer - Classic (Field-Tested)',
    'AWP - Dragon Lore (Factory New)',
    'Desert Eagle - Blaze (Field-Tested)',
    'AK-47 - Fire Serpent (Field-Tested)',
    'M4A4 - Howl (Field-Tested)',
  ];

  try {
    const upstream = await fetch(`${STEAMDT_BASE}/v1/price/batch`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${key}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ marketHashNames: MARKET_NAMES }),
    });
    const res = await upstream.json();

    if (!res.success || !Array.isArray(res.data)) {
      return json({ error: 'SteamDT batch failed', detail: res }, 502);
    }

    // 计算等权指数（以各平台 Steam 价为基准，基期 = 首次查询日均值）
    const prices = res.data.map(entry => {
      const steam = entry.dataList?.find(d => d.platform === 'STEAM');
      return steam ? steam.sellPrice : (entry.dataList?.[0]?.sellPrice ?? 0);
    });

    const BASE = 1000; // 基期指数
    // 这里用简单等权平均作为指数值（实际可对比历史基期做归一化）
    const avgPrice = prices.reduce((a, b) => a + b, 0) / prices.length;
    const latest = Math.round(avgPrice * 100) / 100;

    return json({
      success: true,
      index: {
        latest,
        change: 0,  // 需对比上次价格算变化率，这里简化为0
        changePct: 0,
        items: MARKET_NAMES.map((n, i) => ({
          name: n,
          price: prices[i],
          steamName: ITEMS[i],
        })),
        ts: Date.now(),
      },
    });
  } catch (e) {
    return json({ error: 'Upstream failed', detail: e.message }, 502);
  }
}

// ── 工具 ────────────────────────────────────────────────────
function json(data, status = 200) {
  return new Response(JSON.stringify(data, null, 2), {
    status,
    headers: JSON_HEADERS,
  });
}
