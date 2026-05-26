/**
 * CS2 Dashboard — Cloudflare Worker v3
 *
 * API 路由：
 *   POST /api/sold          → 追加卖出记录
 *   GET  /api/sold          → 获取所有卖出记录
 *   DELETE /api/sold        → 清空卖出记录
 *   GET  /api/csqaq/batch   → 实时查价（CSQAQ 优先 → SteamDT 兜底）
 *   GET  /api/csqaq/alerts  → CSQAQ 排行榜
 *   GET  /api/ping          → 健康检查
 *   /*                      → 代理 GitHub Pages
 *
 * 环境变量：
 *   CSQAQ_API_TOKEN  — CSQAQ API Token
 *   STEAMDT_KEY      — SteamDT API Key（兜底用）
 *
 * KV 绑定：
 *   名称: SOLD_KV
 *   用途: 存储卖出记录
 */

const GH_PAGES = 'https://raw.githubusercontent.com/hintime/cs2-dashboard/main'
const CSQAQ_BATCH = 'https://api.csqaq.com/v2/multi/batch'
const CSQAQ_ALERTS = 'https://api.csqaq.com/v2/multi/alert'
const STEAMDT_BATCH = 'https://open.steamdt.com/open/cs2/v1/price/batch'
const KV_KEY = 'sold:items'

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url)
    const path = url.pathname
    const method = request.method
    const cors = {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    }
    if (method === 'OPTIONS') return new Response(null, { headers: cors })

    try {
      // ── 卖出记录 CRUD ──
      if (path === '/api/sold') {
        if (method === 'GET') {
          const raw = await env.SOLD_KV.get(KV_KEY)
          return json(raw ? JSON.parse(raw) : [], 200, cors)
        }
        if (method === 'POST') {
          const body = await request.json()
          const raw = await env.SOLD_KV.get(KV_KEY)
          const items = raw ? JSON.parse(raw) : []
          items.push(body)
          await env.SOLD_KV.put(KV_KEY, JSON.stringify(items))
          return json({ ok: true, count: items.length }, 200, cors)
        }
        if (method === 'DELETE') {
          await env.SOLD_KV.delete(KV_KEY)
          return json({ ok: true }, 200, cors)
        }
      }

      // ── 实时查价（双源兜底）──
      if (path === '/api/csqaq/batch') {
        const names = url.searchParams.get('names')
        if (!names) return json({ error: 'missing names' }, 400, cors)
        const hnList = names.split(',').slice(0, 50)

        // 1️⃣ 优先 CSQAQ
        if (env.CSQAQ_API_TOKEN) {
          try {
            const resp = await fetch(CSQAQ_BATCH, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', 'ApiToken': env.CSQAQ_API_TOKEN },
              body: JSON.stringify({ hash_names: hnList }),
            })
            if (resp.ok) {
              const data = await resp.json()
              if (data && !data.error) {
                // 标记来源
                Object.keys(data).forEach(function(k) { if (typeof data[k] === 'object') data[k]._source = 'csqaq'; });
                return json(data, 200, cors)
              }
            }
          } catch (_) {}
        }

        // 2️⃣ CSQAQ 不可用 → SteamDT 兜底
        if (env.STEAMDT_KEY) {
          try {
            const resp = await fetch(STEAMDT_BATCH, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + env.STEAMDT_KEY },
              body: JSON.stringify({ marketHashNames: hnList }),
            })
            if (resp.ok) {
              const raw = await resp.json()
              if (raw.success && Array.isArray(raw.data)) {
                const result = {}
                raw.data.forEach(item => {
                  const hn = item.marketHashName
                  if (!hn || !Array.isArray(item.dataList)) return
                  let buffInfo = null, uuypInfo = null
                  item.dataList.forEach(p => {
                    const plat = (p.platform || '').toUpperCase()
                    if (plat === 'BUFF') buffInfo = p
                    if (plat === 'UUYP' || plat === 'YOUPIN') uuypInfo = p
                  })
                  const entry = {}
                  if (buffInfo) {
                    entry.buff_sell = buffInfo.sellPrice || 0
                    entry.buff_buy = buffInfo.biddingPrice || 0
                    entry.buff_sell_num = buffInfo.sellCount || 0
                    entry.buff_buy_num = buffInfo.biddingCount || 0
                    entry.source = 'BUFF'
                    entry.buff_source = 'BUFF'
                  }
                  if (uuypInfo) {
                    entry.yyyp_sell = uuypInfo.sellPrice || 0
                    entry.yyyp_sell_num = uuypInfo.sellCount || 0
                  }
                  if (Object.keys(entry).length) {
                    entry._source = 'steamdt'
                    result[hn] = entry
                  }
                })
                if (Object.keys(result).length) {
                  return json(result, 200, cors)
                }
              }
            }
          } catch (_) {}
        }

        return json({ error: '价格源不可用（CSQAQ 和 SteamDT 都挂了）' }, 502, cors)
      }

      // ── CSQAQ 排行榜 ──
      if (path === '/api/csqaq/alerts') {
        if (!env.CSQAQ_API_TOKEN) return json({ error: 'CSQAQ not configured' }, 400, cors)
        const resp = await fetch(CSQAQ_ALERTS, {
          headers: { 'ApiToken': env.CSQAQ_API_TOKEN },
        })
        if (!resp.ok) return json({ error: 'CSQAQ error' }, 502, cors)
        return json(await resp.json(), 200, cors)
      }

      // ── 健康检查 ──
      if (path === '/api/ping') return json({ ok: true, ts: Date.now() }, 200, cors)

      // ── 价格走势图数据 ──
      if (path === '/api/pricechart') {
        const name = url.searchParams.get('name') || '';
        if (!name) return json({ error: 'missing name' }, 400, cors);
        // 读 buff_history.json（4MB，按日期组织），提取指定物品的价格序列
        const historyUrl = 'https://raw.githubusercontent.com/hintime/cs2-dashboard/main/buff_history.json';
        const resp = await fetch(historyUrl, { cf: { cacheTtl: 300, cacheEverything: true } });
        if (!resp.ok) return json({ error: 'history not available' }, 502, cors);
        const allData = await resp.json();
        var prices = [];
        Object.keys(allData).sort().forEach(function(date) {
          var day = allData[date];
          if (day && day[name]) {
            var item = day[name];
            if (item.buff_sell && item.buff_sell > 0) {
              prices.push({ t: date.substring(0,16), p: item.buff_sell });
            }
          }
        });
        if (prices.length < 2) return json({ error: 'not enough data' }, 404, cors);
        // 返回格式与前端预期兼容：{ eco: [{t, p}, ...] }
        return json({ eco: prices }, 200, cors);
      }

      // ── 代理 GitHub Pages 静态文件 ──
      const target = GH_PAGES + (path === '/' ? '/index.html' : path)
      const resp = await fetch(target, { cf: { cacheTtl: 60, cacheEverything: true } })
      const text = await resp.text()
      const ext = path.split('.').pop()
      const ct = ext === 'json' ? 'application/json' :
        ext === 'html' || path === '/' || !ext ? 'text/html; charset=utf-8' :
        ext === 'css' ? 'text/css' : ext === 'js' ? 'application/javascript' : 'text/plain'
      return new Response(text, {
        headers: { 'Content-Type': ct, 'Cache-Control': 'public, max-age=60', 'Access-Control-Allow-Origin': '*' },
      })
    } catch (e) {
      return json({ error: e.message }, 500, cors)
    }
  },
}

function json(data, status, cors) {
  return new Response(JSON.stringify(data), {
    status: status || 200,
    headers: { 'Content-Type': 'application/json', ...cors },
  })
}
