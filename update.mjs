import https from 'https';
import fs from 'fs';

const STEAMDT_KEY = process.env.STEAMDT_KEY || '';
if (!STEAMDT_KEY || STEAMDT_KEY === 'test_key') {
  console.log('STEAMDT_KEY not configured - skipping API calls, preserving existing data');
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

const STEAMDT_HOST = 'https://open.steamdt.com';

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

async function fetchPrice(name, apiName) {
  const queryName = apiName || name;
  try {
    const url = STEAMDT_HOST + '/open/cs2/v1/price/single?marketHashName=' + encodeURIComponent(queryName);
    const res = await httpGet(url, { 'Authorization': 'Bearer ' + STEAMDT_KEY });
    const resp = JSON.parse(res.body);
    if (resp.success && resp.data && resp.data.length > 0) {
      const yp = resp.data.find(p => p.platform === 'YOUPIN');
      const price = yp ? yp.sellPrice : resp.data[0].sellPrice;
      const src = yp ? 'YOUPIN' : resp.data[0].platform;
      data.items[name].latest = price;
      console.log('[Price OK]', name, '->', price, '(' + src + ')');
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
    const body = JSON.stringify({ marketHashName: queryName, type: 2, platform: 'YOUPIN' });
    const res = await httpPost(STEAMDT_HOST + '/open/cs2/item/v1/kline', body, {
      'Authorization': 'Bearer ' + STEAMDT_KEY, 'Content-Type': 'application/json'
    });
    const resp = JSON.parse(res.body);
    if (resp.success && resp.data && Array.isArray(resp.data)) {
      let bars = resp.data;
      if (bars.length > 90) bars = bars.slice(-90);
      // SteamDT YOUPIN: [ts, open, close, high, low]
      const kline = bars.map(k => [
        Number(k[0]) || 0,
        Number(k[1]) || 0,
        Number(k[3]) || 0,  // high
        Number(k[4]) || 0,  // low
        Number(k[2]) || 0,  // close
        0                   // vol
      ]);
      data.items[name].kline = kline;
      console.log('[K-line OK]', name, '->', kline.length, 'bars (YOUPIN)');
    } else {
      console.log('[K-line WARN]', name, ':', resp.errorMsg || 'no data');
    }
  } catch (e) {
    console.log('[K-line ERR]', name, e.message);
  }
}

const INDEX_ITEM = 'AK-47 | Redline (Field-Tested)';

async function fetchIndexKline() {
  try {
    const body = JSON.stringify({ marketHashName: INDEX_ITEM, type: 2, platform: 'YOUPIN' });
    const res = await httpPost(STEAMDT_HOST + '/open/cs2/item/v1/kline', body, {
      'Authorization': 'Bearer ' + STEAMDT_KEY, 'Content-Type': 'application/json'
    });
    const resp = JSON.parse(res.body);
    if (!resp.success || !Array.isArray(resp.data)) {
      console.log('[Index ERR]', resp.errorMsg || 'no data');
      return;
    }

    let bars = resp.data;
    if (bars.length > 90) bars = bars.slice(-90);

    const dates = [], values = [], ohlc = [], volBar = [], volColor = [];
    const closes = [];

    bars.forEach((k, i) => {
      const ts = Number(k[0]) || 0;
      const d = new Date(ts * 1000);
      const date = (d.getUTCMonth() + 1) + '-' + String(d.getUTCDate()).padStart(2, '0');
      const o = Number(k[1]) || 0;
      const c = Number(k[2]) || 0;
      const h = Number(k[3]) || 0;
      const l = Number(k[4]) || 0;

      dates.push(date);
      closes.push(c);
      values.push(parseFloat(c.toFixed(2)));
      ohlc.push({ date, open: parseFloat(o.toFixed(2)), high: parseFloat(h.toFixed(2)), low: parseFloat(l.toFixed(2)), close: parseFloat(c.toFixed(2)), volume: 0 });

      const prev = i > 0 ? closes[i - 1] : c;
      const mag = Math.abs(c - prev) / prev || 0;
      const barH = Math.max(20, Math.round(Math.min(mag * 5000 + 20, 150)));
      volBar.push(barH);
      volColor.push(c >= prev ? '#ef4444' : '#22c55e');
    });

    const lt = values[values.length - 1] || 0;
    const pv = values[values.length - 2] || lt;
    const chg = parseFloat(((lt - pv) / pv * 100).toFixed(2));

    data.index = {
      latest: lt, change: chg, dates, values,
      min: parseFloat(Math.min(...values).toFixed(2)),
      max: parseFloat(Math.max(...values).toFixed(2)),
      ohlc, volBar, volColor, source: 'steamdt-youpin'
    };
    console.log('[Index OK] SteamDT YOUPIN AK-47 Redline', lt.toFixed(2), 'change', (chg >= 0 ? '+' : '') + chg + '%', bars.length + ' bars');
  } catch (e) {
    console.log('[Index ERR]', e.message);
  }
}

try {
  for (const name of names) {
    const apiName = ALT_NAMES[name] || name;
    await fetchPrice(name, apiName);
    await fetchKline(name, apiName);
  }

  await fetchIndexKline();

  data.update_time = new Date().toISOString().replace('T', ' ').slice(0, 16);
  for (const name of names) {
    if (NAME_CN[name]) data.items[name].name_cn = NAME_CN[name];
  }

  fs.writeFileSync('market.json', JSON.stringify(data, null, 2));
  console.log('\n=== Done! market.json updated ===');
} catch (e) {
  console.error('FATAL:', e);
  process.exit(1);
}
