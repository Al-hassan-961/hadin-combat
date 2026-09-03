/*
 * HADIN-COMBAT – js/settings.js
 * Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
 * All rights reserved.
 *
 * Settings / profile page: persists athlete name + training defaults to
 * localStorage (read by app.js on the training page at startup) and applies
 * the chosen theme. Shows live backend info from /api/stats.
 */
(function () {
    'use strict';

    function $(id) { return document.getElementById(id); }
    function toast(text) {
        const stack = $('toastStack');
        if (!stack) return;
        const t = document.createElement('div');
        t.className = 'toast';
        t.innerHTML = '<span class="t-ic">✅</span><span>' + text + '</span>';
        stack.appendChild(t);
        setTimeout(() => { t.classList.add('out'); setTimeout(() => t.remove(), 350); }, 2600);
    }

    function applyTheme() {
        const light = localStorage.getItem('hc.theme') === 'light';
        document.documentElement.classList.toggle('light', light);
        const b = $('themeToggle');
        if (b) b.textContent = light ? '☀️' : '🌙';
    }

    function readPrefs() {
        $('profileName').value = localStorage.getItem('hc.name') || '';
        $('optVoice').checked = localStorage.getItem('hc.voice') === '1';
        $('optMirror').checked = localStorage.getItem('hc.mirror') === '1';
        $('optSkeleton').checked = localStorage.getItem('hc.skeleton') !== '0';
        $('optGhost').checked = localStorage.getItem('hc.ghost') === '1';
    }

    function save() {
        localStorage.setItem('hc.name', $('profileName').value.trim());
        localStorage.setItem('hc.voice', $('optVoice').checked ? '1' : '0');
        localStorage.setItem('hc.mirror', $('optMirror').checked ? '1' : '0');
        localStorage.setItem('hc.skeleton', $('optSkeleton').checked ? '1' : '0');
        localStorage.setItem('hc.ghost', $('optGhost').checked ? '1' : '0');
        toast('Preferences saved — they apply on the training page.');
    }

    async function backendInfo() {
        const el = $('backendInfo');
        try {
            const r = await fetch('/api/stats');
            const d = await r.json();
            const p = d.profile || {};
            const lvl = Math.round((p.progress_score || 0) * 100);
            el.innerHTML =
                'Backend: ' + (d.backend || '?') + ' · profiles: ' +
                Object.keys(d.profiles || {}).length + '<br>' +
                'Co-evolution: <b>' + (p.total_sessions || 0) + '</b> sessions · ' +
                'AI level <b>' + lvl + '%</b>';
        } catch (_) { el.textContent = 'Backend: unreachable'; }
    }

    document.addEventListener('DOMContentLoaded', () => {
        applyTheme();
        readPrefs();
        backendInfo();
        const toggle = $('themeToggle');
        if (toggle) toggle.addEventListener('click', () => {
            localStorage.setItem('hc.theme',
                document.documentElement.classList.contains('light') ? 'dark' : 'light');
            applyTheme();
        });
        const saveBtn = $('saveBtn');
        if (saveBtn) saveBtn.addEventListener('click', save);
    });
})();
