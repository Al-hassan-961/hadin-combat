/*
 * HADIN-COMBAT – js/dashboard.js
 * Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
 * All rights reserved.
 *
 * Fetches backend stats from /api/stats and renders a lightweight
 * real-time dashboard using the Canvas API (no external chart library).
 * Load this script on a separate dashboard page.
 */
(function () {
    'use strict';

    const REFRESH_MS = 2000;
    const history = [];
    const MAX_POINTS = 60;

    let canvas, ctx, statsEl;

    function ready(fn) {
        if (document.readyState !== 'loading') fn();
        else document.addEventListener('DOMContentLoaded', fn);
    }

    ready(() => {
        canvas = document.getElementById('chart');
        statsEl = document.getElementById('stats');
        if (canvas) ctx = canvas.getContext('2d');
        poll();
        setInterval(poll, REFRESH_MS);
    });

    async function poll() {
        try {
            const res = await fetch('/api/stats');
            const data = await res.json();
            renderStats(data);
            renderChart(data);
        } catch (err) {
            console.error('dashboard poll failed:', err);
        }
    }

    function renderStats(data) {
        if (!statsEl) return;
        const html = [
            `Backend: <b>${data.backend || 'n/a'}</b>`,
            `Active sessions: <b>${(data.sessions || []).length}</b>`,
            `Latency target: <b>${data.latency_target_ms || '—'} ms</b>`,
        ].join(' · ');
        statsEl.innerHTML = html;
    }

    function renderChart(data) {
        if (!ctx || !canvas) return;
        const sessions = data.sessions || [];
        const total = sessions.reduce((acc, s) => acc + (s.frames || 0), 0);
        history.push({ t: Date.now(), total });
        if (history.length > MAX_POINTS) history.shift();

        const W = canvas.width, H = canvas.height;
        ctx.clearRect(0, 0, W, H);

        // Grid
        ctx.strokeStyle = 'rgba(255,255,255,0.08)';
        ctx.lineWidth = 1;
        for (let i = 1; i < 5; i++) {
            const y = (H / 5) * i;
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(W, y);
            ctx.stroke();
        }

        if (history.length < 2) {
            ctx.fillStyle = '#8a8aa3';
            ctx.font = '13px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('Collecting data…', W / 2, H / 2);
            return;
        }

        const max = Math.max(1, ...history.map((p) => p.total));
        const pad = 8;
        ctx.strokeStyle = '#00ffc8';
        ctx.lineWidth = 2;
        ctx.beginPath();
        history.forEach((p, i) => {
            const x = pad + (i / (MAX_POINTS - 1)) * (W - pad * 2);
            const y = H - pad - (p.total / max) * (H - pad * 2);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();
    }
})();
