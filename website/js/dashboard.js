/*
 * HADIN-COMBAT – js/dashboard.js
 * Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
 * All rights reserved.
 *
 * Performance dashboard: fetches /api/history + /api/stats and renders
 * lightweight canvas charts (strike mix, fatigue trend, profile usage) plus
 * personalised improvement suggestions. No external chart library.
 */
(function () {
    'use strict';

    const TECHNIQUES = ['jab', 'cross', 'hook', 'uppercut', 'front_kick',
        'roundhouse_kick', 'superman_punch', 'spinning_backfist',
        'axe_kick', 'question_mark_kick'];
    const TECH_ICONS = { jab: '👊', cross: '👊', hook: '🥊', uppercut: '🥊',
        front_kick: '🦵', roundhouse_kick: '🦵', superman_punch: '🦸',
        spinning_backfist: '🌀', axe_kick: '🪓', question_mark_kick: '❓' };
    const PROFILE_PRETTY = {
        balanced: 'Balanced', aggressive: 'Aggressive',
        counter_puncher: 'Counter-Puncher', defensive: 'Defensive',
        pressure_fighter: 'Pressure Fighter',
    };

    const els = {
        sessions: document.getElementById('statSessions'),
        strikes: document.getElementById('statStrikes'),
        time: document.getElementById('statTime'),
        fatigue: document.getElementById('statFatigue'),
        tech: document.getElementById('chartTechniques'),
        fat: document.getElementById('chartFatigue'),
        prof: document.getElementById('chartProfiles'),
        acc: document.getElementById('chartAccuracy'),
        eff: document.getElementById('chartEffReaction'),
        spm: document.getElementById('statSpm'),
        reaction: document.getElementById('statReaction'),
        improv: document.getElementById('improvementList'),
        sessionsList: document.getElementById('sessionList'),
    };

    function barChart(canvas, labels, values, color) {
        if (!canvas || !canvas.getContext) return;
        const ctx = canvas.getContext('2d');
        const W = canvas.width, H = canvas.height;
        ctx.clearRect(0, 0, W, H);
        ctx.strokeStyle = 'rgba(255,255,255,0.06)';
        ctx.lineWidth = 1;
        for (let i = 1; i < 5; i++) {
            const y = (H / 5) * i;
            ctx.beginPath(); ctx.moveTo(28, y); ctx.lineTo(W - 8, y); ctx.stroke();
        }
        const max = Math.max(1, ...values);
        const n = labels.length;
        const slot = (W - 30) / Math.max(1, n);
        const bw = Math.min(slot * 0.6, 26);
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        labels.forEach((lab, i) => {
            const x = 16 + slot * i + slot / 2;
            const bh = (values[i] / max) * (H - 30);
            ctx.fillStyle = color;
            ctx.fillRect(x - bw / 2, H - 20 - bh, bw, bh);
            ctx.fillStyle = '#8a8aa3';
            ctx.fillText(lab, x, H - 7);
        });
    }

    // Two time-series polylines (e.g. strikes/min and reaction time).
    function lineChart(canvas, series, colorA, colorB) {
        if (!canvas || !canvas.getContext) return;
        const ctx = canvas.getContext('2d');
        const W = canvas.width, H = canvas.height;
        ctx.clearRect(0, 0, W, H);
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        const n = series.a.length;
        if (!n) return;
        const max = Math.max(1, ...series.a, ...series.b);
        const left = 30, right = W - 8, top = 8, bottom = H - 12;
        const x = (i) => n === 1 ? (left + right) / 2 : left + (i / (n - 1)) * (right - left);
        const y = (v) => bottom - (v / max) * (bottom - top);
        [[series.a, colorA], [series.b, colorB]].forEach(([vals, col]) => {
            ctx.strokeStyle = col;
            ctx.lineWidth = 2;
            ctx.beginPath();
            vals.forEach((v, i) => { const px = x(i), py = y(v); i ? ctx.lineTo(px, py) : ctx.moveTo(px, py); });
            ctx.stroke();
        });
        ctx.fillStyle = '#8a8aa3';
        // index labels every session
        if (n <= 12) {
            for (let i = 0; i < n; i++) ctx.fillText(String(i + 1), x(i), H - 2);
        }
    }

    async function refresh() {
        let data = { history: [], improvement: [] };
        try {
            const r = await fetch('/api/history');
            data = await r.json();
        } catch (_) { /* offline */ }

        const history = data.history || [];

        // ---- Summary cards --------------------------------------------------
        let strikes = 0, duration = 0, fatigueSum = 0;
        const techCounts = {};
        const profileCounts = {};
        history.forEach((h) => {
            strikes += h.total_strikes || 0;
            duration += h.duration_s || 0;
            fatigueSum += h.fatigue || 0;
            const p = h.profile || 'balanced';
            profileCounts[p] = (profileCounts[p] || 0) + 1;
            Object.entries(h.techniques || {}).forEach(([t, c]) => {
                techCounts[t] = (techCounts[t] || 0) + c;
            });
        });
        if (els.sessions) els.sessions.textContent = history.length;
        if (els.strikes) els.strikes.textContent = strikes;
        if (els.time) els.time.textContent = Math.round(duration / 60);
        if (els.fatigue) {
            els.fatigue.textContent = history.length ? Math.round(fatigueSum / history.length) : 0;
        }

        // ---- Charts -------------------------------------------------------------
        barChart(els.tech, TECHNIQUES.map((t) => TECH_ICONS[t] || t),
            TECHNIQUES.map((t) => techCounts[t] || 0), '#00ffc8');
        barChart(els.fat, history.map(() => ''), history.map((h) => h.fatigue || 0), '#ff285c');
        const pk = Object.keys(profileCounts);
        barChart(els.prof, pk.map((k) => (PROFILE_PRETTY[k] || k).slice(0, 6)),
            pk.map((k) => profileCounts[k]), '#ffd166');

        // ---- Accuracy + efficiency / reaction (new, additive) -------------------
        barChart(els.acc, history.map((_, i) => 'S' + (i + 1)),
            history.map((h) => h.avg_quality || 0), '#00ffc8');
        lineChart(els.eff,
            { a: history.map((h) => h.strikes_per_min || 0),
              b: history.map((h) => (h.reaction_s || 0) * 100) },  // *100 to share scale
            '#ffd166', '#ff285c');
        let spmSum = 0, reactSum = 0, nSess = 0;
        history.forEach((h) => { spmSum += h.strikes_per_min || 0;
            reactSum += h.reaction_s || 0; nSess++; });
        if (els.spm) els.spm.textContent = nSess ? Math.round(spmSum / nSess) : 0;
        if (els.reaction) els.reaction.textContent = nSess
            ? (reactSum / nSess).toFixed(2) + 's' : '0.0s';

        // ---- Improvement --------------------------------------------------------
        const tips = (data.improvement && data.improvement.length)
            ? data.improvement : ['Complete a session to receive personalised tips.'];
        els.improv.innerHTML = '';
        tips.slice(0, 3).forEach((tip) => {
            const li = document.createElement('li');
            li.textContent = tip;
            els.improv.appendChild(li);
        });

        // ---- Recent sessions ------------------------------------------------------
        els.sessionsList.innerHTML = '';
        history.slice().reverse().slice(0, 6).forEach((h) => {
            const li = document.createElement('li');
            const t = TECHNIQUES.reduce((a, k) => a + (h.techniques?.[k] || 0), 0);
            const when = new Date((h.ended || 0) * 1000).toLocaleTimeString([], {
                hour: '2-digit', minute: '2-digit' });
            li.textContent = `${when} · ${PROFILE_PRETTY[h.profile] || h.profile} · ` +
                `${t} strikes · fatigue ${h.fatigue || 0}`;
            els.sessionsList.appendChild(li);
        });
    }

    document.addEventListener('DOMContentLoaded', () => {
        refresh();
        setInterval(refresh, 4000);
    });
})();
