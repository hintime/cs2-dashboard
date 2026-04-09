export default async function handler(req, res) {
  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  
  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }
  
  const STEAMDT_KEY = 'fb73ba391b4542a1bd182d92a93f10d4';
  
  try {
    const fetch = (await import('node-fetch')).default;
    
    if (req.method === 'POST') {
      const body = req.body || {};
      const response = await fetch('https://open.steamdt.com/open/cs2/v1/price/batch', {
        method: 'POST',
        headers: {
          'Authorization': 'Bearer ' + STEAMDT_KEY,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(body)
      });
      const data = await response.json();
      return res.status(200).json(data);
    }
    
    if (req.method === 'GET') {
      const name = req.query.name;
      if (!name) {
        return res.status(400).json({ error: 'Missing name parameter' });
      }
      const response = await fetch('https://open.steamdt.com/open/cs2/v1/price/single?marketHashName=' + encodeURIComponent(name), {
        headers: { 'Authorization': 'Bearer ' + STEAMDT_KEY }
      });
      const data = await response.json();
      return res.status(200).json(data);
    }
    
    res.status(405).json({ error: 'Method not allowed' });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
}