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
    let stream = null;
    let captureTimer = null;
    let lastFrameTime = 0;
    let framesInWindow = 0;
    let fpsWindowStart = 0;

    // ---- WebSocket connection with auto-reconnect -------------------------
    function connect() {
        const proto = location.protocol === 'https:' ? 'wss' : 'ws';
        const url = `${proto}://${location.host}/ws/${CLIENT_ID}`;
        ws = new WebSocket(url);

        ws.onopen = () => {
            setPill('connected', 'cpp');
            addFeedback('Session connected. Ready to train.');
        };

        ws.onmessage = (event) => onMessage(event.data);

        ws.onclose = () => {
            setPill('reconnecting…', 'none');
            setTimeout(connect, 1500);
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

        if (msg.type === 'hello') {
            setPill(msg.backend, msg.backend);
            addFeedback(msg.message);
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
            stream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } },
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
    function captureLoop() {
        // ~15 fps stream keeps bandwidth and latency low.
        const FPS = 15;
        const interval = Math.max(50, Math.round(1000 / FPS));
        captureTimer = setInterval(() => {
            if (!running || !els.video.readyState) return;

            const canvas = document.createElement('canvas');
            canvas.width = els.video.videoWidth || 320;
            canvas.height = els.video.videoHeight || 240;
            const c = canvas.getContext('2d');
            // Un-mirror for the server so coordinates match raw pixels.
            c.translate(canvas.width, 0);
            c.scale(-1, 1);
            c.drawImage(els.video, 0, 0);
            canvas.toBlob((blob) => {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(blob);
                    updateFps();
                }
            }, 'image/jpeg', 0.7);
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
    function renderFrame(msg) {
        const w = els.video.videoWidth || 320;
        const h = els.video.videoHeight || 240;
        els.overlay.width = w;
        els.overlay.height = h;

        // Base debug frame sent by the server (skeleton already drawn).
        if (msg.debug_frame) {
            const img = new Image();
            img.onload = () => ctx.drawImage(img, 0, 0, w, h);
            img.src = 'data:image/jpeg;base64,' + msg.debug_frame;
        } else if (msg.keypoints) {
            drawSkeleton(msg.keypoints, w, h);
        }

        // Opponent overlay (drawn as a ghost).
        if (msg.opponent && msg.opponent.length) {
            drawOpponent(msg.opponent, w, h);
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
        }
    }

    function drawSkeleton(kps, w, h) {
        const pts = kps.map((k) => ({
            x: k.x, y: k.y, on: (k.score || 0) >= 0.3,
        }));

        ctx.strokeStyle = '#00ffc8';
        ctx.lineWidth = Math.max(2, w / 200);
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
            ctx.arc(p.x, p.y, Math.max(2, w / 300), 0, Math.PI * 2);
            ctx.fill();
        }
    }

    function drawOpponent(opp, w, h) {
        ctx.save();
        ctx.globalAlpha = 0.55;
        ctx.strokeStyle = '#ff285c';
        ctx.lineWidth = Math.max(2, w / 160);
        ctx.lineCap = 'round';
        for (const [a, b] of BONES) {
            const pa = opp[a], pb = opp[b];
            if (pa && pb) {
                ctx.beginPath();
                ctx.moveTo(pa.x * w, pa.y * h);
                ctx.lineTo(pb.x * w, pb.y * h);
                ctx.stroke();
            }
        }
        ctx.fillStyle = '#ff285c';
        for (const k of opp) {
            ctx.beginPath();
            ctx.arc(k.x * w, k.y * h, Math.max(3, w / 200), 0, Math.PI * 2);
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
        }
    });

    els.resetBtn.addEventListener('click', () => {
        if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'reset' }));
        }
    });

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
