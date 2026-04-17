#!/usr/bin/env node
/**
 * Claude Flow Agent Router — Senior-Grade with Complexity Scoring
 *
 * Routes tasks to optimal agents based on multi-signal complexity analysis.
 * Computes a 0-1 complexity score used for 3-tier model routing (ADR-026).
 */

const fs = require('fs');
const path = require('path');

const AGENT_CAPABILITIES = {
  coder: ['code-generation', 'refactoring', 'debugging', 'implementation'],
  tester: ['unit-testing', 'integration-testing', 'coverage', 'test-generation'],
  reviewer: ['code-review', 'security-audit', 'quality-check', 'best-practices'],
  researcher: ['web-search', 'documentation', 'analysis', 'summarization'],
  architect: ['system-design', 'architecture', 'patterns', 'scalability'],
  'backend-dev': ['api', 'database', 'server', 'authentication'],
  'frontend-dev': ['ui', 'react', 'css', 'components'],
  devops: ['ci-cd', 'docker', 'deployment', 'infrastructure'],
};

const TASK_PATTERNS = {
  'implement|create|build|add|write code': 'coder',
  'test|spec|coverage|unit test|integration': 'tester',
  'review|audit|check|validate|security': 'reviewer',
  'research|find|search|documentation|explore': 'researcher',
  'design|architect|structure|plan': 'architect',
  'api|endpoint|server|backend|database': 'backend-dev',
  'ui|frontend|component|react|css|style': 'frontend-dev',
  'deploy|docker|ci|cd|pipeline|infrastructure': 'devops',
};

// Complexity signals — each adds to the 0-1 score
const COMPLEXITY_SIGNALS = {
  // High complexity indicators (architecture-level thinking)
  high: {
    weight: 0.25,
    patterns: [
      /\b(refactor|migrate|redesign|overhaul|rewrite)\b/i,
      /\b(security|vulnerabilit|cve|injection|auth(?:entication|orization))\b/i,
      /\b(architect|system.design|scalab|distribut|microservice)\b/i,
      /\b(multi.?file|cross.?cutting|breaking.?change)\b/i,
      /\b(concurren|race.condition|deadlock|thread.safe)\b/i,
      /\b(crypto|encrypt|cert|tls|ssl|oauth|jwt)\b/i,
      /\b(performance|optimi[sz]|bottleneck|profil|benchmark)\b/i,
    ],
  },
  // Medium complexity indicators (thoughtful implementation)
  medium: {
    weight: 0.12,
    patterns: [
      /\b(debug|fix|bug|error|issue|regression)\b/i,
      /\b(database|query|index|migration|schema)\b/i,
      /\b(test|coverage|mock|stub|integration)\b/i,
      /\b(config|setup|install|environment)\b/i,
      /\b(multiple|several|across|all\s+files)\b/i,
      /\b(api|rest|graphql|webhook|endpoint)\b/i,
    ],
  },
  // Low complexity indicators (routine work)
  low: {
    weight: -0.08,
    patterns: [
      /\b(rename|typo|comment|format|lint|style)\b/i,
      /\b(add\s+import|update\s+version|bump)\b/i,
      /\b(read|show|list|print|log|display)\b/i,
      /\b(simple|quick|small|minor|trivial)\b/i,
    ],
  },
};

// Scope signals — how many things are affected
const SCOPE_SIGNALS = {
  multiFile: { pattern: /\b(files|across|everywhere|all|every|project.wide|codebase)\b/i, weight: 0.10 },
  singleFile: { pattern: /\b(this\s+file|here|line\s+\d+|function\s+\w+)\b/i, weight: -0.05 },
};

function computeComplexity(task) {
  let score = 0.25; // baseline: slightly above trivial
  const matched = [];

  const taskLower = (typeof task === 'string' ? task : '').toLowerCase();
  if (!taskLower) return { score: 0.25, tier: 2, matched: [] };

  // Signal 1: Pattern-based complexity
  for (const [level, config] of Object.entries(COMPLEXITY_SIGNALS)) {
    for (const pattern of config.patterns) {
      if (pattern.test(taskLower)) {
        score += config.weight;
        matched.push(`${level}:${pattern.source.slice(0, 30)}`);
      }
    }
  }

  // Signal 2: Scope detection
  for (const [name, config] of Object.entries(SCOPE_SIGNALS)) {
    if (config.pattern.test(taskLower)) {
      score += config.weight;
      matched.push(`scope:${name}`);
    }
  }

  // Signal 3: Task length as proxy (longer descriptions = more complex)
  const wordCount = taskLower.split(/\s+/).length;
  if (wordCount > 50) {
    score += 0.08;
    matched.push(`words:${wordCount}`);
  } else if (wordCount < 8) {
    score -= 0.05;
    matched.push(`brief:${wordCount}`);
  }

  // Signal 4: Negation / constraints increase complexity
  const constraintCount = (taskLower.match(/\b(must|should|never|always|ensure|require|without|don't|cannot)\b/gi) || []).length;
  if (constraintCount >= 3) {
    score += 0.08;
    matched.push(`constraints:${constraintCount}`);
  }

  // Signal 5: Historical intelligence — boost if similar patterns failed before
  try {
    const rankedPath = path.join(process.cwd(), '.claude-flow', 'data', 'ranked-context.json');
    if (fs.existsSync(rankedPath)) {
      const stat = fs.statSync(rankedPath);
      if (stat.size < 5 * 1024 * 1024) {
        const ranked = JSON.parse(fs.readFileSync(rankedPath, 'utf-8'));
        if (ranked && ranked.entries) {
          const lowConfidence = ranked.entries.filter(e =>
            (e.confidence || 0.5) < 0.4 && e.accessCount > 2
          );
          if (lowConfidence.length > 5) {
            score += 0.05;
            matched.push('historical-failures');
          }
        }
      }
    }
  } catch (e) { /* non-fatal — intelligence is optional */ }

  score = Math.max(0, Math.min(1, score));

  // Map to tier: <0.15 = tier1 (WASM), <0.30 = tier2 (Haiku), >=0.30 = tier3 (Opus)
  const tier = score < 0.15 ? 1 : score < 0.30 ? 2 : 3;

  return { score, tier, matched };
}

function routeTask(task) {
  const taskLower = (typeof task === 'string' ? task : '').toLowerCase();
  const complexity = computeComplexity(task);

  // Determine agent from patterns
  let agent = 'coder';
  let patternMatch = null;
  for (const [pattern, agentName] of Object.entries(TASK_PATTERNS)) {
    const regex = new RegExp(pattern, 'i');
    if (regex.test(taskLower)) {
      agent = agentName;
      patternMatch = pattern;
      break;
    }
  }

  // Confidence is derived from complexity + pattern match quality
  // Higher complexity = lower confidence (harder to be sure of routing)
  // Pattern match = confidence boost
  let confidence = patternMatch ? 0.7 : 0.4;
  confidence += (1 - complexity.score) * 0.2; // simpler tasks = more confident routing
  confidence = Math.max(0.3, Math.min(0.95, confidence));

  const reason = patternMatch
    ? `Pattern: ${patternMatch} | complexity: ${complexity.score.toFixed(2)} (tier ${complexity.tier})`
    : `Default coder | complexity: ${complexity.score.toFixed(2)} (tier ${complexity.tier})`;

  return {
    agent,
    confidence: +confidence.toFixed(3),
    complexity: +complexity.score.toFixed(3),
    tier: complexity.tier,
    signals: complexity.matched,
    reason,
  };
}

// CLI
const task = process.argv.slice(2).join(' ');

if (task) {
  const result = routeTask(task);
  console.log(JSON.stringify(result, null, 2));
} else if (require.main === module) {
  console.log('Usage: router.js <task description>');
  console.log('\nAvailable agents:', Object.keys(AGENT_CAPABILITIES).join(', '));
}

module.exports = { routeTask, computeComplexity, AGENT_CAPABILITIES, TASK_PATTERNS };
