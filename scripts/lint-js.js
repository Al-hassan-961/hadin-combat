#!/usr/bin/env node
/*
 * HADIN-COMBAT – scripts/lint-js.js
 * Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
 * All rights reserved.
 *
 * Dependency-free JavaScript linter used by CI. Checks that each frontend
 * file parses and that the HADIN-COMBAT copyright header is present.
 */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..');
const targets = ['website/js/app.js', 'website/js/dashboard.js',
    'website/js/settings.js'];

const HEADER = 'HADIN-COMBAT';
let failed = false;

function lint(file) {
    const abs = path.join(root, file);
    if (!fs.existsSync(abs)) {
        console.error(`✗ missing file: ${file}`);
        failed = true;
        return;
    }
    const src = fs.readFileSync(abs, 'utf8');

    if (!src.includes(HEADER)) {
        console.error(`✗ ${file}: missing HADIN-COMBAT copyright header`);
        failed = true;
    }

    try {
        // Wrap in a function scope to avoid executing DOM code at parse time.
        new vm.Script(`(function(){\n${src}\n})`, { filename: file });
        console.log(`✓ ${file} parses OK`);
    } catch (e) {
        console.error(`✗ ${file}: syntax error — ${e.message}`);
        failed = true;
    }
}

targets.forEach(lint);

if (failed) {
    console.error('\nLint failed.');
    process.exit(1);
}
console.log('\nAll frontend files OK.');
