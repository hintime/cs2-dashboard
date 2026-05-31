/* ═══════ 共享 AI 分析加载器 ═══════ */
(function() {
  if (window._aiReady) return;
  window._aiReady = true;
  window._aiAnalysis = {};

  fetch('ai_analysis.json?v=' + Date.now())
    .then(function(r) { return r.ok ? r.json() : {}; })
    .catch(function() { return {}; })
    .then(function(data) {
      window._aiAnalysis = data || {};
      var keys = Object.keys(window._aiAnalysis);
      if (keys.length) console.log('[AI] Loaded ' + keys.length + ' analyses');
      // 触发自定义事件，页面可以监听
      document.dispatchEvent(new CustomEvent('ai-loaded', { detail: window._aiAnalysis }));
    });

  /* ── 解析 AI 分析（兼容 JSON 对象 + 文本） ── */
  function parseAI(val) {
    if (!val) return null;
    if (typeof val === 'object') return val;  // 已是 JSON 对象
    // 文本格式解析
    var v = (val.match(/🎯\s*操作建议\s*[:：]\s*(.+)/) || [])[1];
    var c = parseInt((val.match(/置信度\s*[:：]\s*(\d+)/) || [])[1] || '0');
    var reason = (val.match(/📊\s*核心逻辑\s*[:：]\s*(.+)/) || [])[1] || '';
    var risk = (val.match(/⚠️\s*风险\s*[:：]\s*(.+)/) || [])[1] || '';
    return { verdict: v ? v.trim() : '', confidence: c, reason: reason.trim(), risk: risk.trim() };
  }
  window.aiVerdict = function(name) {
    var a = window._aiAnalysis[name];
    var p = parseAI(a);
    return p ? p.verdict : null;
  };
  window.aiConfidence = function(name) {
    var a = window._aiAnalysis[name];
    var p = parseAI(a);
    return p ? p.confidence : null;
  };
  window.aiBadge = function(name) {
    var a = window._aiAnalysis[name];
    if (!a) return '';
    var p = parseAI(a);
    if (!p || !p.verdict) return '<span class="ai-dot" title="AI已分析"></span>';
    var v = p.verdict;
    var c = p.confidence || 0;
    var color = v.includes('买入')||v.includes('加仓') ? 'var(--rise)' : v.includes('减仓')||v.includes('卖出') ? 'var(--fall)' : 'var(--blue)';
    return '<span class="ai-badge-mini" style="background:'+color+';color:#fff;font-size:9px;padding:1px 6px;border-radius:8px;margin-left:6px" title="AI: '+v+' (信心'+c+')">AI</span>';
  };
  window.aiMarketSummary = function() {
    var s = window._aiAnalysis['_market_summary'];
    return s || '';
  };
})();
