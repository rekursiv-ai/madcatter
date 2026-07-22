# Security Policy

## Why this file exists

madcatter renders untrusted Markdown (and embedded HTML, LaTeX math, and
emoji shortcodes) to the terminal, and can optionally fetch remote URLs to
validate links. Some of these paths can hang on adversarial input, emit
unexpected terminal control sequences, or reach out to attacker-chosen hosts.
Security reports need a private path so exploit details are not published
before review.

## Reporting a vulnerability

Please report suspected security vulnerabilities privately by emailing hello@rekursiv.ai.

Include:

- Affected version or commit.
- Steps to reproduce.
- Expected impact.
- Any suggested mitigation.

Please do not open public issues for vulnerabilities until we have investigated and coordinated disclosure.

## Scope

Security reports are especially useful for:

- Denial of service from untrusted Markdown, HTML, or LaTeX input, including
  catastrophic backtracking (ReDoS) in the math, emoji, or section parsers.
- Terminal escape-sequence or control-character injection from rendered
  content that could alter the user's terminal state.
- Server-side request forgery (SSRF) or unsafe URL handling in the link
  checker (`--check-links`) and other network-facing paths.
- HTML-export sinks that could emit unsafe markup for downstream consumers.
- Dependency or packaging issues that affect installed users.
- Supply-chain concerns in the published wheel or its dependency set.
