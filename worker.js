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
const CSQAQ_BATCH = 'https://api.csqaq.com/api/v1/goods/getPriceByMarketHashName'
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
              body: JSON.stringify({ marketHashNameList: hnList }),
            })
            if (resp.ok) {
              const data = await resp.json()
              if (data && (data.code === 0 || data.code === 200) && data.data && data.data.success) {
                var result = {};
                Object.keys(data.data.success).forEach(function(k){
                  var item = data.data.success[k];
                  result[k] = {
                    buff_sell: item.buffSellPrice || 0,
                    buff_sell_num: item.buffSellNum || 0,
                    yyyp_sell: item.yyypSellPrice || 0,
                    yyyp_sell_num: item.yyypSellNum || 0,
                    // ★ 独立市场基准价：Steam 社区市场（CSQAQ 免费返回）。
                    //   没有它前端就算不出跨市场偏离度，只能退回同源假指标。
                    steam_sell: item.steamSellPrice || 0,
                    steam_sell_num: item.steamSellNum || 0,
                    _source: 'csqaq'
                  };
                });
                return json(result, 200, cors)
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
                  let buffInfo, uuypInfo
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

        // 3️⃣ 双源都挂了 → buff_history 兜底
        try {
          const historyUrl = 'https://raw.githubusercontent.com/hintime/cs2-dashboard/main/buff_history.json';
          const resp = await fetch(historyUrl, { cf: { cacheTtl: 300, cacheEverything: true } });
          if (resp.ok) {
            const allData = await resp.json();
            var dates = Object.keys(allData).sort();
            var latest = dates[dates.length - 1];
            if (latest && allData[latest]) {
              var result = {};
              hnList.forEach(function(name) {
                var item = allData[latest][name];
                if (item && item.buff_sell > 0) {
                  result[name] = { buff_sell: item.buff_sell, buff_buy: item.buff_buy || 0, source: 'BUFF', buff_source: 'BUFF', buff_sell_num: item.buff_sell_num || 0, buff_buy_num: item.buff_buy_num || 0, _source: 'buff_history' };
                  if (item.yyyp_sell > 0) { result[name].yyyp_sell = item.yyyp_sell; result[name].yyyp_sell_num = item.yyyp_sell_num || 0; }
                }
              });
              if (Object.keys(result).length) return json(result, 200, cors);
            }
          }
        } catch (_) {}

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
      // 缓存策略（2026-09-15 修正）：
      //   ① data_status.json —— **必须 0 缓存**。它是前端的「缓存版本号」来源，
      //      前端用它的 updated 字段拼出 market.json?v=<updated>。
      //      旧版把它和别的 .json 一起缓存 4 小时 → 版本号自己就是陈旧的
      //      → 整个版本号机制失效，数据更新后最长 4 小时看不到新值。
      //      （实测线上 6 次采样出现 2 种 updated 值，正是此因）
      //   ② 其它数据文件(.json) —— 短缓存 120 秒。它们靠 ?v=<版本号> 天然区分，
      //      但前提是①能及时回源；再加一层短 TTL 兜底，避免边缘节点长期不一致。
      //   ③ 页面/JS/CSS 保持 60 秒，改版能及时生效。
      // 另外：上游 raw.githubusercontent 自身也有约 5 分钟的 CDN 缓存，
      //       故把 cacheTtl 归零/设短，让 Worker 侧不与上游延迟叠加。
      const isStatus = /^\/data_status\.json$/i.test(path)
      const isData = /\.json$/i.test(path)
      const cacheSec = isStatus ? 0 : (isData ? 120 : 60)
      const resp = await fetch(target, {
        cf: { cacheTtl: cacheSec, cacheEverything: true },
      })
      const text = await resp.text()
      const ext = path.split('.').pop()
      const ct = ext === 'json' ? 'application/json' :
        ext === 'html' || path === '/' || !ext ? 'text/html; charset=utf-8' :
        ext === 'css' ? 'text/css' : ext === 'js' ? 'application/javascript' : 'text/plain'
      // ⚠️ 2026-09-16 修复：原实现在这里**没有传 status**。
      //    `new Response(body, {headers})` 不指定 status 时默认 200，
      //    于是上游（raw.githubusercontent）返回的 404 被包装成了 HTTP 200。
      //    后果（都是实际危害）：
      //      · 搜索引擎会把不存在的页面当正常页面收录
      //      · 任何按状态码做的监控 / 爬虫 / 健康检查都会误判
      //      · 排查线上问题的人被误导 —— 本项目就因此白查了一轮
      //    实测：/definitely-not-exist-12345.html → HTTP 200，正文却是 "404: Not Found"。
      //
      //    修法 ①：透传上游 status。
      //    修法 ②：404 不缓存。否则某个路径被探过一次 404 后，
      //            边缘节点会把这个 404 缓存 60~120 秒，期间即使文件补上了也仍然 404。
      //    注：204/304 按规范不允许带 body，而这里总是构造带 body 的 Response，
      //        故这两种状态码退回 200，避免 new Response 抛错。
      const upstreamStatus = (resp.status === 204 || resp.status === 304) ? 200 : resp.status
      const cacheHeader = upstreamStatus === 404
        ? 'no-store'
        : isStatus
          ? 'no-store, no-cache, must-revalidate, max-age=0'
          : 'public, max-age=' + cacheSec
      return new Response(text, {
        status: upstreamStatus,
        headers: { 'Content-Type': ct, 'Cache-Control': cacheHeader, 'Access-Control-Allow-Origin': '*' },
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
