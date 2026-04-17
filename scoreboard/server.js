const http = require("http");
const fs = require("fs");
const path = require("path");

const PORT = 3000;
const ROOT = path.resolve(__dirname, "..");
const SOLO_DIR = path.join(ROOT, "challenge", "solo");
const HIVE_DIR = path.join(ROOT, "challenge", "hive");
const POLL_MS = 800;

let clients = [];
let state = {
  solo: { status: "waiting", files: [], lines: 0, log_lines: 0 },
  hive: { status: "waiting", files: [], lines: 0, log_lines: 0 },
  start_time: null,
  elapsed: 0,
  results: null,
};

function countLines(filePath) {
  try {
    return fs.readFileSync(filePath, "utf-8").split("\n").length;
  } catch {
    return 0;
  }
}

function countLogLines(side) {
  const logPath = path.join(__dirname, `${side}.log`);
  try {
    return fs.readFileSync(logPath, "utf-8").split("\n").length;
  } catch {
    return 0;
  }
}

function scanSide(dir, side) {
  const srcDir = path.join(dir, "src");
  const files = [];
  let totalLines = 0;

  try {
    const entries = fs.readdirSync(srcDir);
    for (const entry of entries) {
      if (entry.endsWith(".py") && entry !== "__init__.py") {
        const full = path.join(srcDir, entry);
        const lines = countLines(full);
        files.push({ name: entry, lines });
        totalLines += lines;
      }
    }
  } catch {}

  const hasImpl = files.some((f) => f.name === "rate_limiter.py");
  const hasTest = files.some((f) => f.name === "test_rate_limiter.py");
  const logLines = countLogLines(side);

  let status = "waiting";
  if (logLines > 0) status = "running";
  if (hasImpl && !hasTest) status = "coding";
  if (hasImpl && hasTest) status = "testing";

  const coverageFile = path.join(dir, "coverage.json");
  if (fs.existsSync(coverageFile)) status = "done";

  return { status, files, lines: totalLines, log_lines: logLines };
}

function updateState() {
  const startFile = path.join(__dirname, "start_time.txt");
  if (fs.existsSync(startFile)) {
    state.start_time = parseInt(fs.readFileSync(startFile, "utf-8").trim());
    state.elapsed = Math.floor(Date.now() / 1000) - state.start_time;
  }

  state.solo = scanSide(SOLO_DIR, "solo");
  state.hive = scanSide(HIVE_DIR, "hive");

  const resultsFile = path.join(__dirname, "results.json");
  if (fs.existsSync(resultsFile)) {
    try {
      state.results = JSON.parse(fs.readFileSync(resultsFile, "utf-8"));
      if (state.results.solo) state.solo.status = "done";
      if (state.results.hive) state.hive.status = "done";
    } catch {}
  }

  const timingFile = path.join(__dirname, "timing.json");
  if (fs.existsSync(timingFile)) {
    try {
      const timing = JSON.parse(fs.readFileSync(timingFile, "utf-8"));
      state.solo.duration = timing.solo_seconds;
      state.hive.duration = timing.hive_seconds;
    } catch {}
  }

  broadcast();
}

function broadcast() {
  const data = `data: ${JSON.stringify(state)}\n\n`;
  clients = clients.filter((res) => {
    try {
      res.write(data);
      return true;
    } catch {
      return false;
    }
  });
}

setInterval(updateState, POLL_MS);

const server = http.createServer((req, res) => {
  if (req.url === "/events") {
    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
      "Access-Control-Allow-Origin": "*",
    });
    clients.push(res);
    req.on("close", () => {
      clients = clients.filter((c) => c !== res);
    });
    updateState();
    return;
  }

  if (req.url === "/api/state") {
    res.writeHead(200, {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    });
    res.end(JSON.stringify(state));
    return;
  }

  if (req.url === "/api/logs/solo" || req.url === "/api/logs/hive") {
    const side = req.url.endsWith("solo") ? "solo" : "hive";
    const logPath = path.join(__dirname, `${side}.log`);
    let content = "";
    try { content = fs.readFileSync(logPath, "utf-8"); } catch {}
    res.writeHead(200, {
      "Content-Type": "text/plain",
      "Access-Control-Allow-Origin": "*",
    });
    res.end(content);
    return;
  }

  if (req.url === "/" || req.url === "/index.html") {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(fs.readFileSync(path.join(__dirname, "index.html"), "utf-8"));
    return;
  }

  res.writeHead(404);
  res.end("Not found");
});

server.listen(PORT, () => {
  console.log(`Scoreboard running at http://localhost:${PORT}`);
  console.log(`Polling every ${POLL_MS}ms...`);
});
