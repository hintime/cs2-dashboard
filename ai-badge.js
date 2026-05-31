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

  /* ── 解析 AI 文本中的 verdict ── */
  window.aiVerdict = function(text) {
    if (!text) return null;
    var m = text.match(/🎯\s*操作建议\s*[:：]\s*(.+)/);
    return m ? m[1].trim() : null;
  };
  window.aiConfidence = function(text) {
    if (!text) return null;
    var m = text.match(/置信度\s*[:：]\s*(\d+)/);
    return m ? parseInt(m[1]) : null;
  };
  window.aiBadge = function(name) {
    var a = window._aiAnalysis[name];
    if (!a) return '';
    var v = window.aiVerdict(a), c = window.aiConfidence(a);
    if (!v) return '<span class="ai-dot" title="AI已分析"></span>';
    var color = v.includes('买入')||v.includes('加仓') ? 'var(--rise)' : v.includes('减仓')||v.includes('卖出') ? 'var(--fall)' : 'var(--blue)';
    return '<span class="ai-badge-mini" style="background:'+color+';color:#fff;font-size:9px;padding:1px 6px;border-radius:8px;margin-left:6px" title="AI: '+v+' (信心'+(c||'?')+')">AI</span>';
  };
})();
