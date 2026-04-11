import https from 'https';
import fs from 'fs';

const STEAMDT_KEY = process.env.STEAMDT_KEY || '';
if (!STEAMDT_KEY || STEAMDT_KEY === 'test_key') {
  console.log('STEAMDT_KEY not configured — skipping API calls, preserving existing data');
  process.exit(0);
}

const data = JSON.parse(fs.readFileSync('market.json', 'utf8'));
const names = Object.keys(data.items);
console.log('Items to fetch:', names.length);

function httpGet(url, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { headers }, res => {
      let body = '';
      res.on('data', c => body += c);
      res.on('end', () => resolve({ status: res.statusCode, body }));
    });
    req.on('error', reject);
    req.setTimeout(30000, () => { req.destroy(); reject(new Error('timeout')); });
  });
}

function httpPost(url, bodyStr, headers = {}) {
  return new Promise((resolve, reject) => {
    const urlObj = new URL(url);
    const req = https.request({
      hostname: urlObj.hostname,
      path: urlObj.pathname + urlObj.search,
      method: 'POST',
      headers: { ...headers, 'Content-Length': Buffer.byteLength(bodyStr) }
    }, res => {
      let body = '';
      res.on('data', c => body += c);
      res.on('end', () => resolve({ status: res.statusCode, body }));
    });
    req.on('error', reject);
    req.setTimeout(30000, () => { req.destroy(); reject(new Error('timeout')); });
    req.write(bodyStr);
    req.end();
  });
}

async function fetchPrice(name, apiName) {
  const queryName = apiName || name;
  try {
    const url = 'https://open.steamdt.com/open/cs2/v1/price/single?marketHashName=' + encodeURIComponent(queryName);
    const res = await httpGet(url, { 'Authorization': 'Bearer ' + STEAMDT_KEY });
    const resp = JSON.parse(res.body);
    if (resp.success && resp.data && resp.data[0]) {
      const price = resp.data[0].sellPrice;
      data.items[name].latest = price;
      console.log('[Price OK]', name, '->', price);
    } else {
      console.log('[Price WARN]', name, ':', resp.errorMsg || 'no data');
    }
  } catch (e) {
    console.log('[Price ERR]', name, e.message);
  }
}

async function fetchKline(name, apiName) {
  const queryName = apiName || name;
  try {
    const body = JSON.stringify({ marketHashName: queryName, type: 2, platform: 'BUFF' });
    const res = await httpPost('https://open.steamdt.com/open/cs2/item/v1/kline', body, {
      'Authorization': 'Bearer ' + STEAMDT_KEY,
      'Content-Type': 'application/json'
    });
    const resp = JSON.parse(res.body);
    console.log('[K-line raw]', name, ': success=' + resp.success, 'errorCode=' + resp.errorCode);

    if (resp.success && resp.data) {
      let klineArr = resp.data;
      if (typeof klineArr === 'object' && !Array.isArray(klineArr)) {
        const keys = Object.keys(klineArr).sort((a, b) => Number(a) - Number(b));
        if (keys.length > 0 && /^\d+$/.test(keys[0])) {
          klineArr = keys.map(k => klineArr[k]);
        } else {
          klineArr = [];
        }
      }
      if (Array.isArray(klineArr) && klineArr.length > 0) {
        const kline = klineArr.map(k => {
          if (Array.isArray(k)) {
            const ts = Number(k[0]) || 0;
            const o = Number(k[1]) || 0;
            const c = Number(k[2]) || 0;
            const h = Number(k[3]) || 0;
            const l = Number(k[4]) || 0;
            return [ts, o, h, l, c, 0];
          }
          return [Number(k.timestamp || k.ts || k.time) || 0,
                  Number(k.open || k.o) || 0,
                  Number(k.high || k.h) || 0,
                  Number(k.low || k.l) || 0,
                  Number(k.close || k.c) || 0, 0];
        });
        data.items[name].kline = kline;
        console.log('[K-line OK]', name, '->', kline.length, 'points');
      } else {
        console.log('[K-line WARN]', name, ': no data');
      }
    } else {
      console.log('[K-line WARN]', name, ':', resp.errorMsg || 'no data');
    }
  } catch (e) {
    console.log('[K-line ERR]', name, e.message);
  }
}

const ALT_NAMES = {
  'M4A1-S | Mecha-Industries (Field-Tested)': 'M4A1-S | Mecha Industries (Field-Tested)',
};

const NAME_CN = {
  'AK-47 | Redline (Field-Tested)': 'AK-47 红线 FT',
  'AWP | Asiimov (Field-Tested)': 'AWP 二西莫夫 FT',
  'M4A4 | Asiimov (Battle-Scarred)': 'M4A4 二西莫夫 BS',
  'M4A1-S | Mecha-Industries (Field-Tested)': 'M4A1-S 怪兽 FT',
  'USP-S | Kill Confirmed (Field-Tested)': 'USP-S 杀戮确认 FT',
  'Glock-18 | Fade (Factory New)': 'Glock-18 渐变 FN',
};

try {
  for (const name of names) {
    const apiName = ALT_NAMES[name] || name;
    await fetchPrice(name, apiName);
    await fetchKline(name, apiName);
  }
  data.update_time = new Date().toISOString().replace('T', ' ').slice(0, 16);
  for (const name of names) {
    if (NAME_CN[name]) data.items[name].name_cn = NAME_CN[name];
  }

  // === CSQAQ 大盘指数日K线 + 真实成交量 ===
  try {
    const httpGet2 = (url) => new Promise((ok, fail) => {
      https.get(url, { headers: { 'ApiToken': 'HXGPY1R7L5W7K7F3O4K1E2N8', 'User-Agent': 'Mozilla/5.0' } }, res => {
        let b = ''; res.on('data', c => b += c);
        res.on('end', () => { try { ok(JSON.parse(b)); } catch(e) { fail(e); } });
      }).on('error', fail).setTimeout(20000, function() { this.destroy(); fail(new Error('timeout')); });
    });

    const [dailyResp, hourlyResp] = await Promise.all([
      httpGet2('https://api.csqaq.com/api/v1/sub/kline?type=1day&id=1'),
      httpGet2('https://api.csqaq.com/api/v1/sub/kline?type=1hour&id=1'),
    ]);

    // Aggregate hourly -> daily volume (bar count per UTC day)
    const hourlyVolMap = {};
    if (hourlyResp && hourlyResp.data) {
      for (const h of hourlyResp.data) {
        const ms = parseInt(h.t);
        const dt = new Date(ms + new Date().getTimezoneOffset() * 60000); // UTC
        const key = (dt.getUTCMonth() + 1) + '-' + dt.getUTCDate();
        hourlyVolMap[key] = (hourlyVolMap[key] || 0) + 1;
      }
    }

    const daily = (dailyResp.data || []).slice(-90);
    const ohlc = daily.map(k => {
      const ms = parseInt(k.t);
      const dt = new Date(ms + new Date().getTimezoneOffset() * 60000);
      const key = (dt.getUTCMonth() + 1) + '-' + dt.getUTCDate();
      const o = Math.round(parseFloat(k.o) * 100) / 100;
      const h = Math.round(parseFloat(k.h) * 100) / 100;
      const l = Math.round(parseFloat(k.l) * 100) / 100;
      const c = Math.round(parseFloat(k.c) * 100) / 100;
      return {
        date: key,
        open: o, high: h, low: l, close: c,
        vol: hourlyVolMap[key] || 1
      };
    });

    const values = ohlc.map(k => k.close);
    const dates  = ohlc.map(k => k.date);
    const lt = values[values.length - 1];
    const pv = values[values.length - 2] || lt;
    data.index = {
      dates, values,
      latest: lt,
      change: Math.round((lt - pv) / pv * 10000) / 100,
      min: Math.round(Math.min(...values) * 100) / 100,
      max: Math.round(Math.max(...values) * 100) / 100,
      ohlc,
      source: 'csqaq'
    };
    console.log('[Index OK] CSQAQ', lt.toFixed(2), 'change', ((lt-pv)/pv*100).toFixed(2) + '%', ohlc.length + ' candles, vol=' + (hourlyVolMap[dates[dates.length-1]] || '?') + '/day');
  } catch(e) {
    console.log('[Index ERR]', e.message);
  }

  fs.writeFileSync('market.json', JSON.stringify(data, null, 2));
  console.log('\n=== Done! market.json updated ===');
} catch (e) {
  console.error('FATAL:', e);
  process.exit(1);
}
