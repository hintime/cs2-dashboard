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

async function fetchPrice(name) {
  try {
    const url = 'https://open.steamdt.com/open/cs2/v1/price/single?marketHashName=' + encodeURIComponent(name);
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

async function fetchKline(name) {
  try {
    const body = JSON.stringify({ marketHashName: name, type: 2, platform: 'BUFF' });
    const res = await httpPost('https://open.steamdt.com/open/cs2/item/v1/kline', body, {
      'Authorization': 'Bearer ' + STEAMDT_KEY,
      'Content-Type': 'application/json'
    });
    const resp = JSON.parse(res.body);
    console.log('[K-line raw]', name, ': success=' + resp.success, 'errorCode=' + resp.errorCode, 'data type=' + (resp.data ? typeof resp.data : 'null'));
    
    if (resp.success && resp.data) {
      let klineArr = resp.data;
      if (Array.isArray(klineArr) && klineArr.length > 0 && Array.isArray(klineArr[0])) {
        klineArr = klineArr.flat();
      }
      if (Array.isArray(klineArr) && klineArr.length > 0) {
        const kline = klineArr.map(k => {
          if (Array.isArray(k)) return k;
          return [k.timestamp || k.ts || k.time, k.open || k.o, k.high || k.h, k.low || k.l, k.close || k.c, k.volume || k.v || 0];
        });
        data.items[name].kline = kline;
        console.log('[K-line OK]', name, '->', kline.length, 'points, last:', JSON.stringify(kline[kline.length - 1]));
      } else {
        console.log('[K-line WARN]', name, ': empty data array');
      }
    } else {
      console.log('[K-line WARN]', name, ':', resp.errorMsg || 'no data');
    }
  } catch (e) {
    console.log('[K-line ERR]', name, e.message);
  }
}

try {
  for (const name of names) {
    await fetchPrice(name);
    await fetchKline(name);
  }
  data.update_time = new Date().toISOString().replace('T', ' ').slice(0, 16);
  fs.writeFileSync('market.json', JSON.stringify(data, null, 2));
  console.log('\n=== Done! market.json updated ===');
} catch (e) {
  console.error('FATAL:', e);
  process.exit(1);
}
