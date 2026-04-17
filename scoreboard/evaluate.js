const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const SOLO_DIR = path.join(ROOT, "challenge", "solo");
const HIVE_DIR = path.join(ROOT, "challenge", "hive");
const PROBE_SCRIPT = path.join(__dirname, "probes.py");
const METRICS_SCRIPT = path.join(__dirname, "metrics.py");

function resolvePython() {
  if (process.env.PYTHON) return process.env.PYTHON;
  const venvPy = path.join(ROOT, ".venv", "bin", "python3");
  if (fs.existsSync(venvPy)) return venvPy;
  return "python3";
}

function runBehavioralProbes(dir) {
  if (!fs.existsSync(PROBE_SCRIPT)) return null;
  const python = resolvePython();
  const mode = process.env.DEMO_MODE || "full";
  const expectedTotal = mode === "fast" ? 6 : 8;
  const res = spawnSync(python, [PROBE_SCRIPT, dir], {
    encoding: "utf-8",
    timeout: 30000,
    env: { ...process.env, DEMO_MODE: mode },
  });
  if (res.error) {
    return {
      error: `probe spawn failed: ${res.error.message}`,
      probes: [],
      passed: 0,
      total: expectedTotal,
    };
  }
  try {
    return JSON.parse(res.stdout);
  } catch {
    return {
      error: `probe output not JSON: ${(res.stderr || res.stdout || "").slice(0, 200)}`,
      probes: [],
      passed: 0,
      total: expectedTotal,
    };
  }
}

function runMetrics(dir, outPath) {
  if (!fs.existsSync(METRICS_SCRIPT)) return null;
  const python = resolvePython();
  const res = spawnSync(python, [METRICS_SCRIPT, dir, outPath], {
    encoding: "utf-8",
    timeout: 60000,
  });
  if (res.error) {
    return { error: `metrics spawn failed: ${res.error.message}` };
  }
  try {
    return JSON.parse(fs.readFileSync(outPath, "utf-8"));
  } catch {
    try {
      return JSON.parse(res.stdout);
    } catch {
      return {
        error: `metrics output not JSON: ${(res.stderr || res.stdout || "").slice(0, 200)}`,
      };
    }
  }
}

function readUsage(side) {
  const p = path.join(__dirname, `${side}.usage.json`);
  if (!fs.existsSync(p)) return null;
  try {
    return JSON.parse(fs.readFileSync(p, "utf-8"));
  } catch {
    return null;
  }
}

function evaluateSide(dir, label, side) {
  const result = {
    label,
    has_implementation: false,
    has_tests: false,
    lines_impl: 0,
    lines_test: 0,
    tests_total: 0,
    tests_passed: 0,
    tests_failed: 0,
    coverage_percent: 0,
    edge_cases: {
      count: 0,
      total: (process.env.DEMO_MODE || "full") === "fast" ? 6 : 8,
      details: [],
    },
    score: 0,
  };

  const implPath = path.join(dir, "src", "rate_limiter.py");
  const testPath = path.join(dir, "src", "test_rate_limiter.py");
  const coveragePath = path.join(dir, "coverage.json");
  const testResultsPath = path.join(dir, "test_results.json");

  if (fs.existsSync(implPath)) {
    result.has_implementation = true;
    result.lines_impl = fs.readFileSync(implPath, "utf-8").split("\n").length;
  }

  if (fs.existsSync(testPath)) {
    result.has_tests = true;
    const testContent = fs.readFileSync(testPath, "utf-8");
    result.lines_test = testContent.split("\n").length;
  }

  const metricsPath = path.join(dir, "metrics.json");
  if (result.has_implementation) {
    result.metrics = runMetrics(dir, metricsPath);
  }

  result.usage = readUsage(side);

  if (result.has_implementation) {
    const probeResults = runBehavioralProbes(dir);
    if (probeResults) {
      const fallbackTotal =
        (process.env.DEMO_MODE || "full") === "fast" ? 6 : 8;
      result.edge_cases.method = "behavioral_probe";
      result.edge_cases.total = probeResults.total || fallbackTotal;
      result.edge_cases.count = probeResults.passed || 0;
      result.edge_cases.details = (probeResults.probes || []).map((p) => ({
        name: p.name,
        passed: p.passed,
        errors: p.errors || [],
      }));
      if (probeResults.error) {
        result.edge_cases.probe_error = probeResults.error;
      }
    }
  }

  if (fs.existsSync(testResultsPath)) {
    try {
      const tr = JSON.parse(fs.readFileSync(testResultsPath, "utf-8"));
      result.tests_total = tr.summary?.total || 0;
      result.tests_passed = tr.summary?.passed || 0;
      result.tests_failed = tr.summary?.failed || 0;
    } catch {}
  }

  if (fs.existsSync(coveragePath)) {
    try {
      const cov = JSON.parse(fs.readFileSync(coveragePath, "utf-8"));
      if (cov.totals && cov.totals.percent_covered !== undefined) {
        result.coverage_percent = Math.round(cov.totals.percent_covered * 100) / 100;
      } else {
        let totalStmts = 0;
        let coveredStmts = 0;
        for (const [file, data] of Object.entries(cov)) {
          if (file === "meta" || file === "totals") continue;
          if (data.summary) {
            totalStmts += data.summary.num_statements || 0;
            coveredStmts += data.summary.covered_lines || 0;
          }
        }
        if (totalStmts > 0) {
          result.coverage_percent = Math.round((coveredStmts / totalStmts) * 10000) / 100;
        }
      }
    } catch {}
  }

  const testPassRate = result.tests_total > 0 ? result.tests_passed / result.tests_total : 0;
  const edgeRatio = result.edge_cases.total > 0
    ? result.edge_cases.count / result.edge_cases.total
    : 0;
  const correctness = Math.min(testPassRate, edgeRatio);

  // Conciseness: reward fewer lines of code, but only when the code is
  // actually correct (gated by min(testPassRate, edgeRatio) so a 3-line
  // broken impl can't game it). Impl lines weigh more than test lines.
  const clamp01 = (x) => Math.max(0, Math.min(1, x));
  const implFactor = clamp01((200 - result.lines_impl) / 150); // ≤50 full, ≥200 zero
  const testFactor = clamp01((400 - result.lines_test) / 300); // ≤100 full, ≥400 zero
  const concisenessRaw = implFactor * 0.7 + testFactor * 0.3;
  const concisenessPoints = concisenessRaw * correctness * 10;

  result.conciseness = {
    impl_factor: Math.round(implFactor * 1000) / 1000,
    test_factor: Math.round(testFactor * 1000) / 1000,
    raw: Math.round(concisenessRaw * 1000) / 1000,
    correctness_gate: Math.round(correctness * 1000) / 1000,
    points: Math.round(concisenessPoints * 100) / 100,
    max_points: 10,
  };

  // Complexity: up to 5 pts based on max cyclomatic complexity across
  // all functions/methods in the impl. Lower is better.
  //   ≤5  → 5 pts     (clean, small branches)
  //   ≤10 → 3 pts     (acceptable)
  //   ≤15 → 1 pt      (getting hairy)
  //   >15 → 0 pts     (senior devs would reject in review)
  const maxCC = result.metrics?.complexity?.max_cc;
  let complexityPoints = 0;
  if (typeof maxCC === "number" && maxCC > 0) {
    if (maxCC <= 5) complexityPoints = 5;
    else if (maxCC <= 10) complexityPoints = 3;
    else if (maxCC <= 15) complexityPoints = 1;
    else complexityPoints = 0;
  }
  result.complexity_score = {
    max_cc: maxCC ?? null,
    avg_cc: result.metrics?.complexity?.avg_cc ?? null,
    points: complexityPoints,
    max_points: 5,
  };

  // Throughput: up to 5 pts, log-scaled. Gated by correctness so a broken
  // impl that happens to be fast doesn't score.
  //   50k ops/s  → 0 pts
  //   158k ops/s → 2.5 pts
  //   500k ops/s → 5 pts (cap)
  const ops = result.metrics?.throughput?.ops_per_sec;
  let throughputPoints = 0;
  if (typeof ops === "number" && ops > 0) {
    const raw = 5 * Math.log10(ops / 50000);
    throughputPoints = Math.max(0, Math.min(5, raw)) * correctness;
  }
  result.throughput_score = {
    ops_per_sec: ops ?? null,
    p99_latency_us: result.metrics?.throughput?.p99_latency_us ?? null,
    points: Math.round(throughputPoints * 100) / 100,
    max_points: 5,
  };

  // Final scoring (sums to 100 max):
  //   implementation exists ......  10
  //   tests exist ................  10
  //   test pass rate ............. ×30
  //   coverage ................... ×0.1  (max 10, was 20 — radon/throughput replace half)
  //   coverage ≥ 80% bonus .......   5
  //   edge cases (probes) ........ ×15
  //   conciseness (gated) ........  10
  //   complexity (radon) .........   5
  //   throughput (gated) .........   5
  const rawScore =
    (result.has_implementation ? 10 : 0) +
    (result.has_tests ? 10 : 0) +
    testPassRate * 30 +
    Math.min(result.coverage_percent, 100) * 0.1 +
    edgeRatio * 15 +
    (result.coverage_percent >= 80 ? 5 : 0) +
    concisenessPoints +
    complexityPoints +
    throughputPoints;

  // Round to 1 decimal so sub-integer differentiators (conciseness,
  // throughput) remain visible when both sides are otherwise perfect.
  result.score = Math.round(rawScore * 10) / 10;

  return result;
}

const timingPath = path.join(__dirname, "timing.json");
let timing = { solo_seconds: 0, hive_seconds: 0 };
if (fs.existsSync(timingPath)) {
  try {
    timing = JSON.parse(fs.readFileSync(timingPath, "utf-8"));
  } catch {}
}

const solo = evaluateSide(SOLO_DIR, "Solo Agent", "solo");
const hive = evaluateSide(HIVE_DIR, "Hive Mind", "hive");

solo.duration_seconds = timing.solo_seconds;
hive.duration_seconds = timing.hive_seconds;

const results = { solo, hive, timestamp: new Date().toISOString() };

fs.writeFileSync(
  path.join(__dirname, "results.json"),
  JSON.stringify(results, null, 2)
);

console.log("");
console.log("╔═══════════════════════════════════════════════════════════════╗");
console.log("║                     FINAL RESULTS                           ║");
console.log("╠═══════════════════╦═══════════════════╦═════════════════════╣");
console.log("║     Metric        ║   🧑 Solo Agent   ║   🐝 Hive Mind     ║");
console.log("╠═══════════════════╬═══════════════════╬═════════════════════╣");

function pad(s, len) {
  s = String(s);
  return s + " ".repeat(Math.max(0, len - s.length));
}

function fmtOps(n) {
  if (typeof n !== "number" || n <= 0) return "--";
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M/s`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k/s`;
  return `${n.toFixed(0)}/s`;
}

function fmtTokens(u) {
  if (!u) return "--";
  const inT = u.input_tokens || 0;
  const outT = u.output_tokens || 0;
  return `${inT + outT} (${inT}+${outT})`;
}

function fmtCost(u) {
  if (!u || typeof u.total_cost_usd !== "number") return "--";
  return `$${u.total_cost_usd.toFixed(4)}`;
}

function shortModel(u) {
  if (!u || !u.model) return "--";
  return u.model.replace(/^claude-/, "").slice(0, 18);
}

const rows = [
  ["Time", `${solo.duration_seconds}s`, `${hive.duration_seconds}s`],
  ["Model", shortModel(solo.usage), shortModel(hive.usage)],
  ["Tokens (in+out)", fmtTokens(solo.usage), fmtTokens(hive.usage)],
  ["Cost", fmtCost(solo.usage), fmtCost(hive.usage)],
  ["Implementation", solo.has_implementation ? "Yes" : "No", hive.has_implementation ? "Yes" : "No"],
  ["Tests", solo.has_tests ? "Yes" : "No", hive.has_tests ? "Yes" : "No"],
  ["Tests Passing", `${solo.tests_passed}/${solo.tests_total}`, `${hive.tests_passed}/${hive.tests_total}`],
  ["Coverage", `${solo.coverage_percent}%`, `${hive.coverage_percent}%`],
  ["Edge Cases", `${solo.edge_cases.count}/${solo.edge_cases.total}`, `${hive.edge_cases.count}/${hive.edge_cases.total}`],
  ["Code Lines", `${solo.lines_impl}`, `${hive.lines_impl}`],
  ["Test Lines", `${solo.lines_test}`, `${hive.lines_test}`],
  [
    "Max Complexity",
    solo.complexity_score.max_cc !== null ? `${solo.complexity_score.max_cc} (CC)` : "--",
    hive.complexity_score.max_cc !== null ? `${hive.complexity_score.max_cc} (CC)` : "--",
  ],
  [
    "Throughput",
    fmtOps(solo.throughput_score.ops_per_sec),
    fmtOps(hive.throughput_score.ops_per_sec),
  ],
  [
    "Conciseness",
    `${solo.conciseness.points.toFixed(1)}/10`,
    `${hive.conciseness.points.toFixed(1)}/10`,
  ],
  ["SCORE", `${solo.score}/100`, `${hive.score}/100`],
];

for (const [metric, soloVal, hiveVal] of rows) {
  const m = pad(metric, 17);
  const s = pad(soloVal, 17);
  const h = pad(hiveVal, 19);
  console.log(`║ ${m}║ ${s}║ ${h}║`);
}

console.log("╚═══════════════════╩═══════════════════╩═════════════════════╝");
console.log("");

if (solo.score > hive.score) {
  console.log("🧑 Solo Agent wins!");
} else if (hive.score > solo.score) {
  console.log("🐝 Hive Mind wins!");
} else {
  console.log("🤝 It's a tie!");
}

console.log("");
console.log(`Results saved to: scoreboard/results.json`);
