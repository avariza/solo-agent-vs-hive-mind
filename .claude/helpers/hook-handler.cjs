#!/usr/bin/env node
/**
 * Claude Flow Hook Handler (Cross-Platform)
 * Dispatches hook events to the appropriate helper modules.
 *
 * Usage: node hook-handler.cjs <command> [args...]
 *
 * Commands:
 *   route          - Route a task to optimal agent (reads PROMPT from env/stdin)
 *   pre-bash       - Validate command safety before execution
 *   post-edit      - Record edit outcome for learning
 *   session-restore - Restore previous session state
 *   session-end    - End session and persist state
 */

const path = require('path');
const fs = require('fs');

const helpersDir = __dirname;

// Safe require with stdout suppression - the helper modules have CLI
// sections that run unconditionally on require(), so we mute console
// during the require to prevent noisy output.
function safeRequire(modulePath) {
  try {
    if (fs.existsSync(modulePath)) {
      const origLog = console.log;
      const origError = console.error;
      console.log = () => {};
      console.error = () => {};
      try {
        const mod = require(modulePath);
        return mod;
      } finally {
        console.log = origLog;
        console.error = origError;
      }
    }
  } catch (e) {
    // silently fail
  }
  return null;
}

const router = safeRequire(path.join(helpersDir, 'router.js'));
const session = safeRequire(path.join(helpersDir, 'session.js'));
const memory = safeRequire(path.join(helpersDir, 'memory.js'));
const intelligence = safeRequire(path.join(helpersDir, 'intelligence.cjs'));

// ── Intelligence timeout protection (fixes #1530, #1531) ───────────────────
const INTELLIGENCE_TIMEOUT_MS = 1500;
function runWithTimeout(fn, label) {
  // For synchronous blocking calls, we use a global safety timer.
  // The readJSON file-size guard prevents loading huge files, but this
  // is an additional safety net.
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      process.stderr.write("[WARN] " + label + " timed out after " + INTELLIGENCE_TIMEOUT_MS + "ms, skipping\n");
      resolve(null);
    }, INTELLIGENCE_TIMEOUT_MS);
    try {
      const result = fn();
      clearTimeout(timer);
      resolve(result);
    } catch (e) {
      clearTimeout(timer);
      resolve(null);
    }
  });
}


// Get the command from argv
const [,, command, ...args] = process.argv;

// Read stdin with timeout — Claude Code sends hook data as JSON via stdin.
// Timeout prevents hanging when stdin is not properly closed (common on Windows).
async function readStdin() {
  if (process.stdin.isTTY) return '';
  return new Promise((resolve) => {
    let data = '';
    const timer = setTimeout(() => {
      process.stdin.removeAllListeners();
      process.stdin.pause();
      resolve(data);
    }, 500);
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => { data += chunk; });
    process.stdin.on('end', () => { clearTimeout(timer); resolve(data); });
    process.stdin.on('error', () => { clearTimeout(timer); resolve(data); });
    process.stdin.resume();
  });
}

async function main() {
  // Global safety timeout: hooks must NEVER hang (#1530, #1531)
  const safetyTimer = setTimeout(() => {
    process.stderr.write("[WARN] Hook handler global timeout (3s), forcing exit\n");
    process.exit(0);
  }, 3000);
  safetyTimer.unref(); // don't keep process alive just for this timer

  let stdinData = '';
  try { stdinData = await readStdin(); } catch (e) { /* ignore stdin errors */ }

  let hookInput = {};
  if (stdinData.trim()) {
    try { hookInput = JSON.parse(stdinData); } catch (e) { /* ignore parse errors */ }
  }

  // Normalize snake_case/camelCase: Claude Code sends tool_input/tool_name (snake_case)
  const toolInput = hookInput.toolInput || hookInput.tool_input || {};
  const toolName = hookInput.toolName || hookInput.tool_name || '';

  // Merge stdin data into prompt resolution: prefer stdin fields, then env, then argv
  const prompt = hookInput.prompt || hookInput.command || toolInput
    || process.env.PROMPT || process.env.TOOL_INPUT_command || args.join(' ') || '';

const handlers = {
  'route': () => {
    if (intelligence && intelligence.getContext) {
      try {
        const ctx = intelligence.getContext(prompt);
        if (ctx) console.log(ctx);
      } catch (e) { /* non-fatal */ }
    }
    if (router && router.routeTask) {
      const result = router.routeTask(prompt);
      const tierLabel = { 1: 'T1:WASM', 2: 'T2:Haiku', 3: 'T3:Opus' }[result.tier] || 'T3:Opus';
      const output = [
        `[INFO] Routing task: ${(typeof prompt === 'string' ? prompt : '').substring(0, 80) || '(no prompt)'}`,
        '',
        '+------------------- Primary Recommendation -------------------+',
        `| Agent: ${result.agent.padEnd(53)}|`,
        `| Confidence: ${(result.confidence * 100).toFixed(1)}%${' '.repeat(44)}|`,
        `| Complexity: ${(result.complexity * 100).toFixed(0)}% -> ${tierLabel.padEnd(42)}|`,
        `| Signals: ${(result.signals || []).slice(0, 3).join(', ').substring(0, 51).padEnd(51)}|`,
        `| Reason: ${(result.reason || '').substring(0, 53).padEnd(53)}|`,
        '+--------------------------------------------------------------+',
      ];
      console.log(output.join('\n'));
    } else {
      console.log('[INFO] Router not available, using default routing');
    }
  },

  'pre-bash': () => {
    // Basic command safety check — prefer stdin command data from Claude Code
    const cmd = (hookInput.command || prompt).toLowerCase();
    const dangerous = ['rm -rf /', 'format c:', 'del /s /q c:\\', ':(){:|:&};:'];
    for (const d of dangerous) {
      if (cmd.includes(d)) {
        console.error(`[BLOCKED] Dangerous command detected: ${d}`);
        process.exit(1);
      }
    }
    console.log('[OK] Command validated');
  },

  'post-edit': () => {
    if (session && session.metric) {
      try { session.metric('edits'); } catch (e) { /* no active session */ }
    }
    const file = hookInput.file_path || toolInput.file_path
      || process.env.TOOL_INPUT_file_path || args[0] || '';

    if (intelligence && intelligence.recordEdit) {
      try { intelligence.recordEdit(file); } catch (e) { /* non-fatal */ }
    }

    // Evaluate edit quality: check for red flags in the changed file
    let editQuality = 1.0;
    const warnings = [];
    if (file && fs.existsSync(file)) {
      try {
        const stat = fs.statSync(file);
        if (stat.size > 50 * 1024) {
          editQuality -= 0.1;
          warnings.push('large-file');
        }
        const content = fs.readFileSync(file, 'utf-8');
        const lines = content.split('\n');
        if (lines.length > 500) {
          editQuality -= 0.1;
          warnings.push('over-500-lines');
        }
        // Detect secrets / hardcoded credentials
        if (/(?:api[_-]?key|secret|password|token)\s*[:=]\s*['"][^'"]{8,}/i.test(content)) {
          editQuality -= 0.3;
          warnings.push('possible-secret');
        }
        // Detect console.log spam (>5 in a single file is suspicious)
        const logCount = (content.match(/console\.(log|debug)\(/g) || []).length;
        if (logCount > 5) {
          editQuality -= 0.05;
          warnings.push(`console-spam(${logCount})`);
        }
      } catch (e) { /* stat/read failed, skip quality check */ }
    }

    editQuality = Math.max(0, Math.min(1, editQuality));
    if (intelligence && intelligence.feedbackWeighted) {
      try { intelligence.feedbackWeighted(editQuality); } catch (e) { /* non-fatal */ }
    }

    if (warnings.length > 0) {
      console.log(`[REVIEW] Edit quality: ${(editQuality * 100).toFixed(0)}% — warnings: ${warnings.join(', ')}`);
    } else {
      console.log('[OK] Edit recorded');
    }
  },

  'session-restore': async () => {
    if (session) {
      // Try restore first, fall back to start
      const existing = session.restore && session.restore();
      if (!existing) {
        session.start && session.start();
      }
    } else {
      // Minimal session restore output
      const sessionId = `session-${Date.now()}`;
      console.log(`[INFO] Restoring session: %SESSION_ID%`);
      console.log('');
      console.log(`[OK] Session restored from %SESSION_ID%`);
      console.log(`New session ID: ${sessionId}`);
      console.log('');
      console.log('Restored State');
      console.log('+----------------+-------+');
      console.log('| Item           | Count |');
      console.log('+----------------+-------+');
      console.log('| Tasks          |     0 |');
      console.log('| Agents         |     0 |');
      console.log('| Memory Entries |     0 |');
      console.log('+----------------+-------+');
    }
    // Initialize intelligence graph after session restore (with timeout — #1530)
    if (intelligence && intelligence.init) {
      const initResult = await runWithTimeout(() => intelligence.init(), 'intelligence.init()');
      if (initResult && initResult.nodes > 0) {
        console.log(`[INTELLIGENCE] Loaded ${initResult.nodes} patterns, ${initResult.edges} edges`);
      }
    }
  },

  'session-end': async () => {
    // Consolidate intelligence before ending session (with timeout — #1530)
    if (intelligence && intelligence.consolidate) {
      const consResult = await runWithTimeout(() => intelligence.consolidate(), 'intelligence.consolidate()');
      if (consResult && consResult.entries > 0) {
        console.log(`[INTELLIGENCE] Consolidated: ${consResult.entries} entries, ${consResult.edges} edges${consResult.newEntries > 0 ? `, ${consResult.newEntries} new` : ''}, PageRank recomputed`);
      }
    }
    if (session && session.end) {
      session.end();
    } else {
      console.log('[OK] Session ended');
    }
  },

  'pre-task': () => {
    if (session && session.metric) {
      try { session.metric('tasks'); } catch (e) { /* no active session */ }
    }
    if (router && router.routeTask && prompt) {
      const result = router.routeTask(typeof prompt === 'string' ? prompt : '');
      const tierLabel = { 1: 'T1:WASM', 2: 'T2:Haiku', 3: 'T3:Opus' }[result.tier] || 'T3:Opus';
      console.log(`[INFO] Task routed to: ${result.agent} (confidence: ${(result.confidence * 100).toFixed(0)}%, complexity: ${(result.complexity * 100).toFixed(0)}% ${tierLabel})`);
    } else {
      console.log('[OK] Task started');
    }
  },

  'post-task': () => {
    // Evaluate actual task quality instead of hardcoded success
    let quality = 0.7; // neutral baseline
    const signals = [];

    // Signal 1: Check pending insights for recent edit failures
    const pendingPath = path.join(process.cwd(), '.claude-flow', 'data', 'pending-insights.jsonl');
    if (fs.existsSync(pendingPath)) {
      try {
        const lines = fs.readFileSync(pendingPath, 'utf-8').trim().split('\n').filter(Boolean);
        const recentEdits = lines.filter(l => {
          try { const e = JSON.parse(l); return Date.now() - e.timestamp < 60000; } catch { return false; }
        });
        if (recentEdits.length > 0) {
          quality += 0.1; // productive — edits were made
          signals.push(`edits:${recentEdits.length}`);
        } else {
          quality -= 0.05; // no edits during task = possibly unproductive
          signals.push('no-recent-edits');
        }
      } catch (e) { /* non-fatal */ }
    }

    // Signal 2: Check if recently edited files have lint/syntax issues
    const sessionFile = path.join(process.cwd(), '.claude-flow', 'sessions', 'current.json');
    if (fs.existsSync(sessionFile)) {
      try {
        const sess = JSON.parse(fs.readFileSync(sessionFile, 'utf-8'));
        const lastEdited = (sess.context && sess.context.lastEditedFiles) || [];
        let badFiles = 0;
        for (const f of lastEdited.slice(-3)) {
          if (f && fs.existsSync(f)) {
            const content = fs.readFileSync(f, 'utf-8');
            if (/(?:api[_-]?key|secret|password|token)\s*[:=]\s*['"][^'"]{8,}/i.test(content)) {
              badFiles++;
              signals.push(`secret-in:${path.basename(f)}`);
            }
            if (content.split('\n').length > 500) {
              signals.push(`large:${path.basename(f)}`);
            }
          }
        }
        if (badFiles > 0) quality -= 0.2 * badFiles;
      } catch (e) { /* non-fatal */ }
    }

    // Signal 3: Task took abnormally long (if start time is recorded)
    const taskStartStr = process.env.TASK_START_TIME;
    if (taskStartStr) {
      const elapsed = Date.now() - parseInt(taskStartStr, 10);
      if (elapsed > 120000) {
        quality -= 0.05;
        signals.push(`slow:${Math.round(elapsed / 1000)}s`);
      }
    }

    quality = Math.max(0, Math.min(1, quality));
    const success = quality >= 0.5;

    if (intelligence && intelligence.feedbackWeighted) {
      try { intelligence.feedbackWeighted(quality); } catch (e) { /* non-fatal */ }
    } else if (intelligence && intelligence.feedback) {
      try { intelligence.feedback(success); } catch (e) { /* non-fatal */ }
    }

    if (signals.length > 0) {
      console.log(`[REVIEW] Task quality: ${(quality * 100).toFixed(0)}% [${signals.join(', ')}] — ${success ? 'PASS' : 'WARN'}`);
    } else {
      console.log(`[OK] Task completed (quality: ${(quality * 100).toFixed(0)}%)`);
    }
  },

  'stats': () => {
    if (intelligence && intelligence.stats) {
      intelligence.stats(args.includes('--json'));
    } else {
      console.log('[WARN] Intelligence module not available. Run session-restore first.');
    }
  },
};

  // Execute the handler
  if (command && handlers[command]) {
    try {
      await Promise.resolve(handlers[command]());
    } catch (e) {
      // Hooks should never crash Claude Code - fail silently
      console.log(`[WARN] Hook ${command} encountered an error: ${e.message}`);
    }
  } else if (command) {
    // Unknown command - pass through without error
    console.log(`[OK] Hook: ${command}`);
  } else {
    console.log('Usage: hook-handler.cjs <route|pre-bash|post-edit|session-restore|session-end|pre-task|post-task|stats>');
  }
}

// Hooks must ALWAYS exit 0 — Claude Code treats non-zero as "hook error"
// and skips all subsequent hooks for the event.
process.exitCode = 0;
main().catch((e) => {
  try { console.log(`[WARN] Hook handler error: ${e.message}`); } catch (_) {}
}).finally(() => {
  process.exit(0);
});
