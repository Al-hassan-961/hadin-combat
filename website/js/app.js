/*
 * HADIN-COMBAT – js/app.js
 * Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
 * All rights reserved.
 *
 * Handles camera capture, WebSocket streaming, skeleton/opponent overlays,
 * real-time feedback, and automatic reconnection.
 */
(function () {
    'use strict';

    const $ = (id) => document.getElementById(id);

    const els = {
        video: $('camera'),
        overlay: $('overlay'),
        startBtn: $('startBtn'),
        resetBtn: $('resetBtn'),
        stageMessage: $('stageMessage'),
        backendPill: $('backendPill'),
        hudFps: $('hudFps'),
        hudLatency: $('hudLatency'),
        hudDifficulty: $('hudDifficulty'),
        grade: $('grade'),
        feedbackList: $('feedbackList'),
    };

    const ctx = els.overlay.getContext('2d');
    const CLIENT_ID = 'web-' + Math.random().toString(36).slice(2, 10);

    // COCO 17 keypoint bone connections.
    const BONES = [
        [0,1],[0,2],[1,3],[2,4],[5,6],[5,7],[7,9],[6,8],[8,10],
        [5,11],[6,12],[11,12],[11,13],[13,15],[12,14],[14,16],
    ];

    let ws = null;
    let running = false;
    let showOpponent = false;   // ghost off by default (avoid confusion)
    let showSkeleton = true;    // stickman on by default
    let mirrorView = false;     // natural view by default (no flip)
    let stream = null;
    let captureTimer = null;
    let lastFrameTime = 0;
    let framesInWindow = 0;
    let fpsWindowStart = 0;
    let reconnectDelay = 800;
    let voiceOn = false;
    let lastSpoken = '';
    let lastTechniqueType = null;
    let tipLastShown = 0;
    let tipCurrent = '';

    // ---- Text-to-speech voice coaching (Web Speech API) -------------------
    function speak(text) {
        if (!voiceOn || !('speechSynthesis' in window)) return;
        const clean = (text || '').replace(/[^\w\s.,'’\-:!]/g, ' ').trim();
        if (!clean || clean === lastSpoken) return;
        window.speechSynthesis.cancel();
        const u = new SpeechSynthesisUtterance(clean);
        u.rate = 1.0;
        u.pitch = 1.0;
        window.speechSynthesis.speak(u);
        lastSpoken = clean;
        setTimeout(() => { lastSpoken = ''; }, 4000);
    }

    // ---- WebSocket connection with auto-reconnect (backoff) -----------------
    function connect() {
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        const url = `${proto}://${location.host}/ws/${CLIENT_ID}`;
        ws = new WebSocket(url);

        ws.onopen = () => {
            reconnectDelay = 800;             // reset backoff on success
            setPill('connected', 'cpp');
            addFeedback('Session connected. Ready to train.');
        };

        ws.onmessage = (event) => onMessage(event.data);

        ws.onclose = () => {
            setPill('reconnecting…', 'none');
            setTimeout(connect, reconnectDelay);
            reconnectDelay = Math.min(8000, reconnectDelay * 1.8);  // backoff
        };

        ws.onerror = () => ws.close();
    }

    function onMessage(raw) {
        let msg;
        try {
            msg = typeof raw === 'string' ? JSON.parse(raw) : raw;
        } catch (_) {
            return;
        }

        if (msg.type === 'ping') return;          // server keep-alive

        if (msg.type === 'hello') {
            setPill(msg.backend, msg.backend);
            addFeedback(msg.message);
            if (msg.profiles) initProfileChips(msg.profiles);
            return;
        }
        if (msg.type === 'frame') {
            renderFrame(msg);
            return;
        }
        if (msg.type === 'feedback') {
            addFeedback(msg.message);
        }
        if (msg.type === 'reset_ack') {
            addFeedback('Difficulty reset to ' + Math.round(msg.difficulty * 100) + '%.');
        }
        if (msg.type === 'profile_ack') {
            addFeedback('Sparring profile: ' + (msg.profile || '') + '.');
        }
        if (msg.type === 'match_summary') {
            showMatchSummary(msg);
        }
        if (msg.type === 'error') {
            addFeedback('⚠ ' + (msg.message || 'Unknown error'));
        }
    }

    // ---- Camera -----------------------------------------------------------
    function isSecureOrigin() {
        // getUserMedia only works on secure origins: https, or http on
        // localhost/127.0.0.1. Plain http over a LAN IP is BLOCKED by browsers
        // even when the user granted camera permission.
        return window.isSecureContext ||
            location.hostname === 'localhost' || location.hostname === '127.0.0.1';
    }

    function showCameraError(err) {
        let title = '📵 Camera unavailable';
        let msg = '';

        if (!isSecureOrigin()) {
            title = '🔒 Camera needs a secure page';
            msg =
                'Your browser blocks the camera on plain http for non-localhost ' +
                'addresses, even with permission granted.<br><br>' +
                '• On THIS phone, open <b>http://127.0.0.1:8000</b> instead.<br>' +
                '• For other devices, start the server with HTTPS: ' +
                '<b>bash scripts/run.sh --ssl</b> (accept the certificate warning).';
        } else if (err.name === 'NotAllowedError' || err.message === 'no-getusermedia') {
            msg =
                'Camera permission denied. Tap the camera/🔒 icon in the address ' +
                'bar, choose <b>Allow</b>, then press Start again.';
        } else if (err.name === 'NotFoundError') {
            msg = 'No camera was found on this device.';
        } else if (err.name === 'NotReadableError') {
            msg = 'The camera is in use by another app. Close it and retry.';
        } else if (err.name === 'SecurityError') {
            msg =
                'Camera blocked by browser policy. Use <b>http://127.0.0.1:8000</b> ' +
                'or HTTPS (<b>bash scripts/run.sh --ssl</b>).';
        } else {
            msg = 'Camera error: ' + (err.message || err.name || 'unknown');
        }

        els.stageMessage.innerHTML =
            '<div class="msg-box"><span class="msg-emoji">' +
            title.split(' ')[0] + '</span>' +
            '<p class="msg-title">' + title + '</p>' +
            '<p>' + msg + '</p></div>';
    }

    async function startCamera() {
        try {
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                throw new Error('no-getusermedia');
            }
            // Modest resolution keeps the phone camera + pipeline smooth.
            stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'user', width: { ideal: 480 }, height: { ideal: 360 } },
                audio: false,
            });
            els.video.srcObject = stream;
            await els.video.play();
            els.stageMessage.style.display = 'none';
        } catch (err) {
            showCameraError(err);
            console.error(err);
        }
    }

    function stopCamera() {
        if (stream) {
            stream.getTracks().forEach((t) => t.stop());
            stream = null;
        }
        if (captureTimer) {
            clearInterval(captureTimer);
            captureTimer = null;
        }
        els.overlay.width = els.overlay.height = 0;
    }

    // ---- Frame capture -----------------------------------------------------
    function applyViewTransforms() {
        // Mirroring is a DISPLAY-only effect: flip the video element via CSS.
        // The overlay canvas is NOT CSS-flipped — mapPoint() applies the same
        // flip mathematically so the stickman stays aligned with the video.
        if (els.video) {
            els.video.style.transform = mirrorView ? 'scaleX(-1)' : 'none';
        }
    }

    function captureLoop() {
        // 10 fps keeps the phone CPU, WebSocket and analysis smooth.
        const FPS = 10;
        const interval = Math.max(80, Math.round(1000 / FPS));
        captureTimer = setInterval(() => {
            if (!running || !els.video.readyState) return;

            const canvas = document.createElement('canvas');
            canvas.width = els.video.videoWidth || 320;
            canvas.height = els.video.videoHeight || 240;
            const c = canvas.getContext('2d');
            // Always draw the RAW frame (CSS transforms don't affect
            // drawImage), so server coordinates = raw camera pixels.
            c.drawImage(els.video, 0, 0);
            canvas.toBlob((blob) => {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(blob);
                    updateFps();
                }
            }, 'image/jpeg', 0.6);
        }, interval);
    }

    function updateFps() {
        const now = performance.now();
        framesInWindow++;
        if (!fpsWindowStart) fpsWindowStart = now;
        if (now - fpsWindowStart >= 1000) {
            const fps = Math.round((framesInWindow * 1000) / (now - fpsWindowStart));
            els.hudFps.textContent = fps + ' fps';
            framesInWindow = 0;
            fpsWindowStart = now;
        }
    }

    // ---- Rendering ----------------------------------------------------------
    // The overlay canvas sits on top of the LIVE <video> — there is no
    // debug-frame round trip. Server keypoints are in RAW camera pixel
    // coordinates; we map them onto the stage box using the same cover-crop
    // the video applies, plus the optional mirror flip, so the stickman
    // always lines up with the body.
    function stageBox() {
        const r = els.stage.getBoundingClientRect();
        return { w: Math.max(1, r.width), h: Math.max(1, r.height) };
    }

    function mapPoint(px, py) {
        const vw = els.video.videoWidth || 1;
        const vh = els.video.videoHeight || 1;
        const box = stageBox();
        const scale = Math.max(box.w / vw, box.h / vh);
        const dw = vw * scale;
        const dh = vh * scale;
        const ox = (box.w - dw) / 2;
        const oy = (box.h - dh) / 2;
        let x = ox + px * scale;
        if (mirrorView) x = box.w - x;   // match the flipped video
        return { x: x, y: oy + py * scale };
    }

    function renderFrame(msg) {
        const box = stageBox();
        els.overlay.width = Math.round(box.w);
        els.overlay.height = Math.round(box.h);
        ctx.clearRect(0, 0, box.w, box.h);

        if (showSkeleton && msg.keypoints && msg.keypoints.length) {
            drawSkeleton(msg.keypoints);
        }
        if (showOpponent && msg.opponent && msg.opponent.length) {
            drawOpponent(msg.opponent);
        }

        els.hudLatency.textContent = (msg.latency_ms || 0) + ' ms';
        els.hudDifficulty.textContent =
            'Difficulty: ' + Math.round((msg.difficulty || 0) * 100) + '%';

        if (msg.feedback) {
            updateFeedback(msg.feedback);
        }
        if (msg.coach) {
            updateCoachMove(msg.coach);
            updateCoachCounts(msg.coach);
            const last = msg.coach.last;
            if (last && last.type && last.type !== lastTechniqueType) {
                lastTechniqueType = last.type;
                if (last.advice && last.advice[0]) speak(last.advice[0]);
            }
        }
        if (msg.fatigue) updateFatigue(msg.fatigue);
        if (msg.analysis) updateLivePanel(msg.analysis);
    }

    function drawSkeleton(kps) {
        const box = stageBox();
        const pts = kps.map((k) => {
            const p = mapPoint(k.x, k.y);
            return { x: p.x, y: p.y, on: (k.score || 0) >= 0.3 };
        });

        ctx.strokeStyle = '#00ffc8';
        ctx.lineWidth = Math.max(2, box.w / 220);
        ctx.lineCap = 'round';
        for (const [a, b] of BONES) {
            if (pts[a] && pts[b] && pts[a].on && pts[b].on) {
                ctx.beginPath();
                ctx.moveTo(pts[a].x, pts[a].y);
                ctx.lineTo(pts[b].x, pts[b].y);
                ctx.stroke();
            }
        }
        ctx.fillStyle = '#00ffc8';
        for (const p of pts) {
            if (!p.on) continue;
            ctx.beginPath();
            ctx.arc(p.x, p.y, Math.max(2, box.w / 320), 0, Math.PI * 2);
            ctx.fill();
        }
    }

    function drawOpponent(opp) {
        const box = stageBox();
        const vw = els.video.videoWidth || 1;
        const vh = els.video.videoHeight || 1;
        // Opponent points are normalized 0..1 -> raw pixels -> mapped.
        const pts = opp.map((k) => mapPoint(k.x * vw, k.y * vh));

        ctx.save();
        ctx.globalAlpha = 0.55;
        ctx.strokeStyle = '#ff285c';
        ctx.lineWidth = Math.max(2, box.w / 170);
        ctx.lineCap = 'round';
        for (const [a, b] of BONES) {
            if (pts[a] && pts[b]) {
                ctx.beginPath();
                ctx.moveTo(pts[a].x, pts[a].y);
                ctx.lineTo(pts[b].x, pts[b].y);
                ctx.stroke();
            }
        }
        ctx.fillStyle = '#ff285c';
        for (const p of pts) {
            ctx.beginPath();
            ctx.arc(p.x, p.y, Math.max(3, box.w / 220), 0, Math.PI * 2);
            ctx.fill();
        }
        ctx.restore();
    }

    // ---- Feedback / coach UI -------------------------------------------------
    const MOVE_LABELS = {
        jab: '👊 Jab', cross: '👊 Cross', hook: '🥊 Hook', uppercut: '🥊 Uppercut',
        front_kick: '🦵 Front Kick', roundhouse_kick: '🦵 Roundhouse Kick',
        knee_raise: '🦵 Knee Raise', block: '🛡️ Block', guard: '🧤 Guard',
        stance: '🧍 Stance',
    };

    function updateCoachMove(coach) {
        const last = coach && coach.last;
        els.moveName = els.moveName || document.getElementById('moveName');
        els.moveSide = els.moveSide || document.getElementById('moveSide');
        els.moveQ = els.moveQ || document.getElementById('moveQ');
        els.qualityFill = els.qualityFill || document.getElementById('qualityFill');

        if (last && MOVE_LABELS[last.type]) {
            els.moveName.textContent = MOVE_LABELS[last.type];
            els.moveSide.textContent = last.side === 'left' ? 'L' : last.side === 'right' ? 'R' : '';
            els.moveQ.textContent = (last.quality || 0) + '%';
            const fill = els.qualityFill;
            fill.style.width = (last.quality || 0) + '%';
            fill.style.background = (last.quality || 0) >= 85 ? 'var(--neon)'
                : (last.quality || 0) >= 60 ? '#ffd166' : 'var(--accent)';
        } else {
            els.moveName.textContent = '—';
            els.moveSide.textContent = '';
            els.moveQ.textContent = '';
        }
    }

    function updateCoachCounts(coach) {
        els.coachCounts = els.coachCounts || document.getElementById('coachCounts');
        if (!coach || !coach.counts) return;
        const chips = Object.entries(coach.counts)
            .filter(([, c]) => c > 0)
            .slice(0, 8)
            .map(([t, c]) => {
                const label = (MOVE_LABELS[t] || t).replace(/^[^ ]+ /, '');
                return '<span class="chip">' + label + ' <b>' + c + '</b></span>';
            })
            .join('');
        els.coachCounts.innerHTML = chips
            ? chips
            : '<span class="chip chip-dim">no techniques yet</span>';
    }

    // ---- Sparring profile selector -----------------------------------------
    function initProfileChips(profiles) {
        els.profileChips = els.profileChips || document.getElementById('profileChips');
        if (!els.profileChips) return;
        const names = Array.isArray(profiles)
            ? profiles : ['balanced', 'aggressive', 'counter_puncher', 'defensive', 'pressure_fighter'];
        const pretty = { balanced: '🥊 Balanced', aggressive: '🔥 Aggressive',
            counter_puncher: '🛡️ Counter', defensive: '🧱 Defensive',
            pressure_fighter: '🚀 Pressure' };
        els.profileChips.innerHTML = '';
        names.forEach((p) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'chip chip-btn';
            b.dataset.profile = p;
            b.textContent = pretty[p] || p;
            b.addEventListener('click', () => selectProfile(p));
            els.profileChips.appendChild(b);
        });
        // default active = balanced
        els.profileChips.querySelectorAll('.chip-btn').forEach((c) =>
            c.classList.toggle('chip-active', c.dataset.profile === 'balanced'));
    }

    function selectProfile(profile) {
        els.profileChips = els.profileChips || document.getElementById('profileChips');
        if (els.profileChips) {
            els.profileChips.querySelectorAll('.chip-btn').forEach((c) =>
                c.classList.toggle('chip-active', c.dataset.profile === profile));
        }
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'set_profile', profile }));
        }
    }

    // ---- Fatigue meter -------------------------------------------------------
    function updateFatigue(fatigue) {
        els.fatigueFill = els.fatigueFill || document.getElementById('fatigueFill');
        els.fatigueVal = els.fatigueVal || document.getElementById('fatigueVal');
        els.fatigueLevel = els.fatigueLevel || document.getElementById('fatigueLevel');
        if (!els.fatigueFill || !fatigue) return;
        const s = fatigue.score || 0;
        els.fatigueFill.style.width = s + '%';
        els.fatigueFill.style.background =
            s < 30 ? 'var(--neon)' : s < 60 ? '#ffd166' : 'var(--accent)';
        if (els.fatigueVal) els.fatigueVal.textContent = s;
        if (els.fatigueLevel) {
            els.fatigueLevel.textContent = fatigue.level || 'fresh';
            els.fatigueLevel.style.color =
                s < 30 ? 'var(--neon)' : s < 60 ? '#ffd166' : 'var(--accent)';
        }
    }

    // ---- LIVE ANALYSIS PANEL ------------------------------------------------
    function fmtClock(sec) {
        sec = Math.max(0, Math.floor(sec || 0));
        const m = Math.floor(sec / 60), s = sec % 60;
        return m + ':' + (s < 10 ? '0' : '') + s;
    }

    function updateLivePanel(a) {
        if (!a) return;
        const g = (id) => document.getElementById(id);

        // Strike + confidence
        const strike = a.strike;
        if (g('liveStrike')) {
            g('liveStrike').textContent = strike && MOVE_LABELS[strike.type]
                ? MOVE_LABELS[strike.type] : '—';
        }
        if (g('liveStrikeConf')) {
            g('liveStrikeConf').textContent = strike
                ? (strike.confidence_pct || 0) + '% conf · quality ' + (strike.quality || 0)
                : '';
        }
        // Fatigue
        if (g('liveFatigue')) g('liveFatigue').textContent = a.fatigue_score || 0;
        if (g('liveFatigueFill')) {
            const fs = a.fatigue_score || 0;
            g('liveFatigueFill').style.width = fs + '%';
            g('liveFatigueFill').style.background =
                fs < 30 ? 'var(--neon)' : fs < 60 ? '#ffd166' : 'var(--accent)';
        }
        // Profile
        if (g('liveProfile')) g('liveProfile').textContent = a.profile || 'Balanced';
        // Round + duration
        if (g('liveRound')) g('liveRound').textContent = 'R' + (a.round || 1);
        if (g('liveRoundTime')) {
            g('liveRoundTime').textContent =
                (a.phase === 'rest' ? 'rest ' : '') + fmtClock(a.phase_remain);
        }
        if (g('liveDuration')) g('liveDuration').textContent = fmtClock(a.elapsed_s);
        // Speed
        if (g('liveSpeed')) {
            const sp = a.speed_band || 'slow';
            g('liveSpeed').textContent = sp;
            g('liveSpeed').style.color =
                sp === 'fast' ? 'var(--accent)' : sp === 'medium' ? '#ffd166' : 'var(--neon)';
        }
        // Latest action
        if (g('liveAction') && a.action) g('liveAction').textContent = '🎯 ' + a.action;
        // Coaching tip — refresh at most every 10 seconds
        if (a.tip) {
            const now = Date.now();
            if (now - tipLastShown >= 10000 || !tipCurrent) {
                tipCurrent = a.tip;
                tipLastShown = now;
                if (g('liveTip')) g('liveTip').textContent = '💬 ' + a.tip;
            }
        }
    }

    // ---- MATCH SUMMARY MODAL --------------------------------------------------
    function showMatchSummary(s) {
        const g = (id) => document.getElementById(id);
        if (!g('summaryMask')) return;
        g('sumStrikes').textContent = s.total_strikes || 0;
        g('sumLanded').textContent = s.landed || 0;
        g('sumAccuracy').textContent = (s.accuracy_pct || 0) + '%';
        g('sumPerformance').textContent = s.performance || 0;
        g('sumMost').textContent = 'Most used: ' + ((s.most_used || 'none').replace(/_/g, ' '));
        g('sumReaction').textContent = 'Reaction: ' + (s.reaction_s || 0).toFixed(2) + 's';
        g('sumFatigue').textContent = 'Final fatigue: ' + (s.final_fatigue || 0);
        g('sumTime').textContent = 'Duration: ' + fmtClock(s.duration_s);
        const ul = g('sumSuggestions');
        ul.innerHTML = '';
        ((s.suggestions || []).length ? s.suggestions
            : ['Complete a session to receive tips.']).forEach((tip) => {
            const li = document.createElement('li');
            li.textContent = tip;
            ul.appendChild(li);
        });
        g('summaryMask').hidden = false;
    }

    function hideMatchSummary() {
        const m = document.getElementById('summaryMask');
        if (m) m.hidden = true;
    }

    function updateFeedback(fb) {
        els.grade.textContent = fb.grade || 'C';
        els.grade.className = 'grade ' + (fb.grade || 'c').toLowerCase();
        els.feedbackList.innerHTML = '';
        const notes = (fb.notes && fb.notes.length) ? fb.notes : ['Keep moving – stay active.'];
        notes.slice(0, 3).forEach((n) => {
            const li = document.createElement('li');
            li.textContent = n;
            els.feedbackList.appendChild(li);
        });
    }

    function addFeedback(text) {
        const li = document.createElement('li');
        li.textContent = text;
        els.feedbackList.prepend(li);
        while (els.feedbackList.children.length > 3) {
            els.feedbackList.removeChild(els.feedbackList.lastChild);
        }
    }

    // ---- Status pill -----------------------------------------------------------
    function setPill(text, cls) {
        els.backendPill.textContent = text;
        els.backendPill.className = 'backend-pill ' + (cls || '');
    }

    // ---- Controls ---------------------------------------------------------------
    els.startBtn.addEventListener('click', async () => {
        if (!running) {
            hideMatchSummary();
            await startCamera();
            running = true;
            els.startBtn.textContent = '■ Stop';
            els.startBtn.classList.add('recording');
            captureLoop();
            if (!ws || ws.readyState !== WebSocket.OPEN) connect();
        } else {
            running = false;
            els.startBtn.textContent = '▶ Start';
            els.startBtn.classList.remove('recording');
            stopCamera();
            els.stageMessage.style.display = 'flex';
            // Ask the server for the end-of-session match summary.
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'summary' }));
            }
        }
    });

    const summaryClose = document.getElementById('summaryClose');
    const summaryOk = document.getElementById('summaryOk');
    if (summaryClose) summaryClose.addEventListener('click', hideMatchSummary);
    if (summaryOk) summaryOk.addEventListener('click', hideMatchSummary);

    els.resetBtn.addEventListener('click', () => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'reset' }));
        }
    });

    // ---- View toggles: skeleton / ghost / mirror ----------------------------
    function bindToggle(id, get, set, onLabel, offLabel) {
        const btn = document.getElementById(id);
        if (!btn) return;
        const refresh = () => {
            const on = get();
            btn.textContent = on ? onLabel : offLabel;
            btn.classList.toggle('btn-active', on);
        };
        btn.addEventListener('click', () => {
            set(!get());
            if (id === 'mirrorBtn') applyViewTransforms();
            refresh();
        });
        refresh();
    }
    bindToggle('skeletonBtn', () => showSkeleton, (v) => { showSkeleton = v; },
               '🦴 Skeleton', '🦴 Skeleton');
    bindToggle('ghostBtn', () => showOpponent, (v) => { showOpponent = v; },
               '👻 Ghost', '👻 Ghost');
    bindToggle('mirrorBtn', () => mirrorView, (v) => { mirrorView = v; },
               '🪞 Mirror', '🪞 Mirror');
    bindToggle('voiceBtn', () => voiceOn, (v) => { voiceOn = v; },
               '🔊 Voice', '🔇 Voice');
    // Prime the TTS engine on first user gesture (autoplay policies).
    document.addEventListener('click', () => {
        if ('speechSynthesis' in window) window.speechSynthesis.getVoices();
    }, { once: true });

    // ---- Connection / share bar ---------------------------------------------
    function setupConnectBar() {
        const url = location.protocol + '//' + location.host + '/';
        els.connectUrl = document.getElementById('connectUrl');
        els.copyUrl = document.getElementById('copyUrl');
        if (els.connectUrl) els.connectUrl.textContent = url;

        if (els.copyUrl) {
            els.copyUrl.addEventListener('click', async () => {
                try {
                    await navigator.clipboard.writeText(url);
                    els.copyUrl.textContent = '✓';
                    setTimeout(() => (els.copyUrl.textContent = '📋'), 1500);
                } catch (_) {
                    // Clipboard blocked (non-HTTPS); fall back to selecting.
                    if (els.connectUrl) {
                        const range = document.createRange();
                        range.selectNodeContents(els.connectUrl);
                        const sel = window.getSelection();
                        sel.removeAllRanges();
                        sel.addRange(range);
                    }
                }
            });
        }
    }

    // Poll the health endpoint so the UI reflects live server state.
    function pollHealth() {
        fetch('/api/health')
            .then((r) => r.json())
            .then((d) => {
                setPill('v' + (d.version || '?') + ' · ' + (d.backend || '?'), d.backend || 'none');
            })
            .catch(() => setPill('offline', 'none'));
    }

    // ---- Init -----------------------------------------------------------------
    setupConnectBar();
    applyViewTransforms();
    pollHealth();
    setInterval(pollHealth, 10000);

    // Warn up-front if the camera will be blocked by browser policy (plain
    // http on a non-localhost address).
    if (!isSecureOrigin()) {
        showCameraError({ name: 'SecurityError' });
    }

    // Initial connection attempt.
    connect();
})();
