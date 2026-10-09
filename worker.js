/**
 * CS2 Dashboard — Cloudflare Worker v3
 *
 * API 路由：
 *   POST /api/sold          → 追加卖出记录
 *   GET/POST /api/holdings-sync → 持仓云端同步（手机 ↔ KV ↔ 服务器采集）
 *   GET  /api/steam-market  → 代理 Steam 社区市场搜索（服务器在国内被墙）
 *   GET  /api/inventory     → 代理 Steam 公开库存（CS2 默认，分页合并 + KV 缓存）
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
      'Access-Control-Allow-Headers': 'Content-Type, x-sync-key',
    }
    if (method === 'OPTIONS') return new Response(null, { headers: cors })

    // 轻量共享密钥网关：仅当 env.SYNC_KEY 已配置时才校验写接口；未配置则向后兼容（旧部署不中断）。
    // 客户端在请求头带 x-sync-key，与 CF Worker 环境变量 SYNC_KEY 保持一致即启用。
    function syncOk(req) {
      if (!env.SYNC_KEY) return true;
      const k = req.headers.get('x-sync-key') || '';
      return k === env.SYNC_KEY;
    }

    try {
      // ── 卖出记录 CRUD ──
      if (path === '/api/sold') {
        if (method === 'GET') {
          const raw = await env.SOLD_KV.get(KV_KEY)
          return json(raw ? JSON.parse(raw) : [], 200, cors)
        }
        if (method === 'POST') {
          if (!syncOk(request)) return json({ error: 'unauthorized' }, 401, cors);
          const body = await request.json()
          const raw = await env.SOLD_KV.get(KV_KEY)
          const items = raw ? JSON.parse(raw) : []
          items.push(body)
          await env.SOLD_KV.put(KV_KEY, JSON.stringify(items))
          return json({ ok: true, count: items.length }, 200, cors)
        }
        if (method === 'DELETE') {
          if (!syncOk(request)) return json({ error: 'unauthorized' }, 401, cors);
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
        const pcKey = 'pc:' + name;
        // 先查 KV 缓存（避免每次都拉 17MB 解析）—— buff_history 每天才更新，1h TTL 足够
        try {
          const cached = await env.SOLD_KV.get(pcKey);
          if (cached) return json(JSON.parse(cached), 200, cors);
        } catch (_) {}
        // 读 buff_history.json（17MB，按日期组织），提取指定物品的价格序列
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
        const out = { eco: prices };
        try { await env.SOLD_KV.put(pcKey, JSON.stringify(out), { expirationTtl: 3600 }); } catch (_) {}
        return json(out, 200, cors);
      }

      // ── 持仓同步（手机/浏览器 → KV → 服务器采集）──
      if (path === '/api/holdings-sync') {
        const KEY = 'hpsync:admin'
        if (method === 'GET') {
          const raw = await env.SOLD_KV.get(KEY)
          if (!raw) return json({ ok: true, empty: true, ts: 0, items: [] }, 200, cors)
          return new Response(raw, { status: 200, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...cors } })
        }
        if (method === 'PUT' || method === 'POST') {
          if (!syncOk(request)) return json({ error: 'unauthorized' }, 401, cors);
          const body = await request.json()
          const items = Array.isArray(body && body.items) ? body.items : null
          if (!items) return json({ error: 'missing items' }, 400, cors)
          if (items.length > 500) return json({ error: 'too many items' }, 400, cors)
          // 只保留必要字段，防垃圾数据膨胀
          const clean = items.slice(0, 500).map(function (it) {
            return {
              market_hash: String(it.market_hash || '').slice(0, 200),
              name: String(it.name || '').slice(0, 200),
              cost: Number(it.cost) || 0,
              qty: Number(it.qty) || 1,
              wear: String(it.wear || '').slice(0, 20),
            }
          }).filter(function (it) { return it.market_hash })
          const payload = { ok: true, ts: Date.now(), count: clean.length, items: clean }
          await env.SOLD_KV.put(KEY, JSON.stringify(payload))
          return json({ ok: true, count: clean.length, ts: payload.ts }, 200, cors)
        }
      }

      // ── Steam 市场代理（服务器在国内访问 steamcommunity 被墙）──
      //   Steam 市场抓取模块（steam_market.py）原直连 steamcommunity.com，
      //   实测从腾讯云北京 000 超时；api.steampowered.com 可达但没有市场搜索接口。
      //   故经本 Worker 中转（Worker 在海外，可正常访问）。
      if (path === '/api/steam-market') {
        try {
          const qs = url.searchParams.toString()
          const stUrl = 'https://steamcommunity.com/market/search/render/?' + qs
          const stResp = await fetch(stUrl, {
            headers: {
              'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
              'Accept': 'application/json, text/plain, */*',
              'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            },
            cf: { cacheTtl: 300, cacheEverything: true },
          })
          const body = await stResp.text()
          return new Response(body, {
            status: 200,
            headers: {
              'Content-Type': 'application/json; charset=utf-8',
              'Cache-Control': 'public, max-age=300',
              'Access-Control-Allow-Origin': '*',
            },
          })
        } catch (e) {
          return json({ success: false, error: 'steam proxy failed: ' + e.message }, 200, cors)
        }
      }

      // ── Steam 库存导入（公开库存，无需登录 / 无需 API key）──
      //   用途：把玩家的 CS2 库存拉进来做持仓导入。
      //   前提：目标库存必须设为「公开」。私有库存 Steam 直接拒绝（403 或 success!==1），
      //         无任何绕过手段 —— OpenID 登录也不授予库存权限。
      //   位置：必须走本 Worker。steamcommunity.com 在国内被 DNS 污染，直连/国内服务器均不通。
      //   参数：
      //     steamid   必填，17 位 SteamID64
      //     appid     默认 730（CS2）
      //     contextid 默认 2
      //     nocache=1 跳过 KV 缓存强制回源（首次验证用）
      //     raw=1     返回原始 assets/descriptions（体积大、不写缓存）
      //     maxpages  默认 30，上限 60
      if (path === '/api/inventory') {
        const t0 = Date.now()
        const steamid = (url.searchParams.get('steamid') || '').trim()
        const appid = (url.searchParams.get('appid') || '730').trim()
        const contextid = (url.searchParams.get('contextid') || '2').trim()
        const nocache = url.searchParams.get('nocache') === '1'
        const wantRaw = url.searchParams.get('raw') === '1'
        const maxPages = Math.min(Math.max(parseInt(url.searchParams.get('maxpages') || '30', 10) || 30, 1), 60)

        if (!/^\d{17}$/.test(steamid)) {
          return json({ ok: false, error: 'invalid steamid64：需要 17 位数字' }, 400, cors)
        }
        if (!/^\d+$/.test(appid) || !/^\d+$/.test(contextid)) {
          return json({ ok: false, error: 'invalid appid/contextid' }, 400, cors)
        }

        const cacheKey = 'inv:' + appid + ':' + contextid + ':' + steamid
        if (!nocache && !wantRaw) {
          const hit = await env.SOLD_KV.get(cacheKey)
          if (hit) {
            return new Response(hit, {
              status: 200,
              headers: { 'Content-Type': 'application/json; charset=utf-8', 'X-Inv-Cache': 'hit', ...cors },
            })
          }
        }

        const pageLog = []
        const assetsAll = []
        const descMap = {}
        let startAssetid = null
        let reportedTotal = 0
        let rateLimited = false
        let errMsg = null
        let errCode = null
        let done = false

        for (let page = 0; page < maxPages; page++) {
          const qp = new URLSearchParams({ l: 'english', count: '2000' })
          if (startAssetid) qp.set('start_assetid', startAssetid)
          const stUrl = 'https://steamcommunity.com/inventory/' + steamid + '/' + appid + '/' + contextid + '?' + qp.toString()

          let resp
          try {
            resp = await fetch(stUrl, {
              headers: {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'en-US,en;q=0.9',
              },
              cf: { cacheTtl: 0 },
            })
          } catch (e) {
            pageLog.push({ page: page, error: 'fetch: ' + e.message })
            errMsg = 'steam fetch failed: ' + e.message
            break
          }

          pageLog.push({ page: page, status: resp.status })
          if (resp.status === 429) {
            rateLimited = true
            errCode = 'RATE_LIMITED'
            errMsg = 'Steam 限流 429（该出口 IP 已被限，需降低频率或加缓存）'
            break
          }
          if (resp.status === 403) {
            errCode = 'INVENTORY_PRIVATE'
            errMsg = 'Steam 库存未设为「公开」，无法读取'
            break
          }
          if (!resp.ok) {
            errCode = 'STEAM_ERROR'
            errMsg = 'Steam 返回 HTTP ' + resp.status
            break
          }

          let data
          try { data = await resp.json() } catch (e) { errCode = 'STEAM_ERROR'; errMsg = 'Steam 返回非 JSON'; break }
          if (data.success !== 1) {
            errCode = 'INVENTORY_PRIVATE'
            errMsg = 'Steam 库存未设为「公开」，无法读取'
            break
          }

          reportedTotal = data.total_inventory_count || reportedTotal
          if (Array.isArray(data.assets)) for (const a of data.assets) assetsAll.push(a)
          if (Array.isArray(data.descriptions)) {
            for (const d of data.descriptions) descMap[d.classid + '_' + d.instanceid] = d
          }
          done = true

          if ((Number(data.more_items) === 1 || data.more_items === true) && data.last_assetid) {
            startAssetid = String(data.last_assetid)
            // 页间隔，降低被限流概率
            await new Promise(function (r) { setTimeout(r, 350 + Math.floor(Math.random() * 350)) })
            continue
          }
          break
        }

        const elapsed = Date.now() - t0

        // 原始模式：直接回吐 Steam 的两张表
        if (wantRaw) {
          return json({
            ok: done && !errMsg, steamid, appid, contextid,
            total_inventory_count: reportedTotal,
            assets_fetched: assetsAll.length,
            descriptions_fetched: Object.keys(descMap).length,
            pages: pageLog,
            rate_limited: rateLimited,
            error: errMsg,
            error_code: errCode,
            elapsed_ms: elapsed,
            assets: assetsAll,
            descriptions: Object.values(descMap),
          }, 200, cors)
        }

        // 聚合：asset 实例 → 按 market_hash_name 归并（数量在 asset.amount）
        const agg = {}
        for (const a of assetsAll) {
          const d = descMap[a.classid + '_' + a.instanceid] || {}
          const hn = d.market_hash_name || d.name || ('unknown_' + a.classid)
          const amt = parseInt(a.amount, 10) || 1
          if (!agg[hn]) {
            agg[hn] = {
              market_hash_name: hn,
              name: d.name || '',
              type: d.type || '',
              tradable: d.tradable === 1,
              marketable: d.marketable === 1,
              icon: d.icon_url ? 'https://community.cloudflare.steamstatic.com/economy/image/' + d.icon_url : '',
              amount: 0,
              stacks: 0,
            }
          }
          agg[hn].amount += amt
          agg[hn].stacks += 1
        }
        const items = Object.keys(agg).map(function (k) { return agg[k] })
        items.sort(function (x, y) { return y.amount - x.amount })

        // 私有库存 → 返回结构化提示 + 切换「公开」的操作指引
        let guide = null
        if (errCode === 'INVENTORY_PRIVATE') {
          guide = {
            what: 'Steam 库存必须设为「公开」才能被读取，当前不是公开状态。',
            steps: [
              '1. 打开下面「privacy_settings」链接（需先登录 Steam；打不开就先登录再点）',
              '2. 把「我的个人资料」改为「公开」',
              '3. 把「库存」改为「公开」（这是独立设置，必须单独改这一项）',
              '4. 无需点保存，Steam 会自动生效；等约 1 分钟后重试',
            ],
            by_client: 'Steam 客户端：头像 → 查看我的个人资料 → 编辑个人资料 → 隐私设置',
            by_mobile: '手机 Steam App：个人资料 → 编辑个人资料 → 隐私设置 → 库存改为公开',
            links: {
              privacy_settings: 'https://steamcommunity.com/profiles/' + steamid + '/edit/settings',
              profile: 'https://steamcommunity.com/profiles/' + steamid + '/',
              verify: 'https://steamcommunity.com/profiles/' + steamid + '/inventory',
            },
            note: '改完后打开 verify 链接自检：能看到物品就说明已公开。',
          }
        }

        const payload = {
          ok: done && !errMsg,
          steamid: steamid, appid: appid, contextid: contextid,
          total_inventory_count: reportedTotal,
          assets_fetched: assetsAll.length,
          distinct_items: items.length,
          rate_limited: rateLimited,
          pages: pageLog,
          error: errMsg,
          error_code: errCode,
          ...(guide ? { guide: guide } : {}),
          elapsed_ms: elapsed,
          fetched_at: new Date().toISOString(),
          items: items,
        }

        if (done && !errMsg) {
          try { await env.SOLD_KV.put(cacheKey, JSON.stringify(payload), { expirationTtl: 300 }) } catch (_) {}
        }
        return json(payload, 200, cors)
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
      // 404 / 5xx 不进边缘缓存（避免"文件已补上仍 404"），2xx 按 cacheSec 缓存
      const resp = await fetch(target, {
        cf: { cacheTtlByStatus: { '200-299': cacheSec, '404': 0, '500-599': 0 }, cacheEverything: true },
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
