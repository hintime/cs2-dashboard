// ==UserScript==
// @name         CS2 库存一键复制
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  在 Steam 库存 JSON 页面自动复制到剪贴板，配合 CS2 看板使用
// @author       hintime
// @match        https://steamcommunity.com/*/inventory/json/730/2*
// @match        https://steamcommunity.com/inventory/*/730/2*
// @grant        GM_setClipboard
// @grant        GM_notification
// ==/UserScript==

(function() {
    'use strict';

    // 页面加载完成后执行
    function init() {
        // 检查是否是有效的 JSON 页面
        const pre = document.querySelector('pre');
        if (!pre) return;

        const jsonText = pre.textContent;
        if (!jsonText.includes('"assets"') || !jsonText.includes('"success":true')) {
            return; // 不是有效的库存 JSON
        }

        // 复制到剪贴板
        if (typeof GM_setClipboard !== 'undefined') {
            GM_setClipboard(jsonText);
            showNotification('✓ CS2 库存 JSON 已复制到剪贴板', '请回到 CS2 看板粘贴导入');
        } else {
            // 降级：使用原生 API
            navigator.clipboard.writeText(jsonText).then(() => {
                showNotification('✓ CS2 库存 JSON 已复制', '请回到 CS2 看板粘贴');
            });
        }

        // 添加页面内提示
        addPageHint();
    }

    function showNotification(title, text) {
        if (typeof GM_notification !== 'undefined') {
            GM_notification({
                title: title,
                text: text,
                timeout: 5000
            });
        }
    }

    function addPageHint() {
        const hint = document.createElement('div');
        hint.style.cssText = `
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: #2a2a2a;
            color: #4ade80;
            padding: 16px 24px;
            border-radius: 12px;
            border: 1px solid #22c55e;
            font-family: system-ui, -apple-system, sans-serif;
            font-size: 14px;
            z-index: 999999;
            box-shadow: 0 4px 20px rgba(0,0,0,0.5);
            text-align: center;
        `;
        hint.innerHTML = `
            <div style="font-weight: 600; margin-bottom: 4px;">✓ 库存 JSON 已自动复制</div>
            <div style="font-size: 12px; color: #aaa;">请切换回 CS2 看板 → 导入库存 → 粘贴</div>
        `;
        document.body.appendChild(hint);

        // 3 秒后淡出
        setTimeout(() => {
            hint.style.transition = 'opacity 0.5s';
            hint.style.opacity = '0';
            setTimeout(() => hint.remove(), 500);
        }, 3000);
    }

    // 页面加载完成后执行
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
