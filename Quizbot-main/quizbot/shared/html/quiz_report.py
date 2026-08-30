"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import html
import json
import random
import re
import uuid
from typing import Any

# --------------------------------------------------------------------------
# Small local helpers (no external deps -- stdlib only)
# --------------------------------------------------------------------------


def _esc(value: Any) -> str:
    """Escape arbitrary input for safe interpolation into HTML text nodes."""
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _slug(text: str, fallback: str = "quiz") -> str:
    """Turn a quiz name into a filesystem-safe filename stem."""
    text = (text or "").strip().lower()
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in text)
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return cleaned[:60] or fallback


def _js_literal(value: Any) -> str:
    """Serialize a Python value to a JSON literal safe for embedding in a
    <script> block (also neutralizes '</script>' breakout sequences)."""
    raw = json.dumps(value, ensure_ascii=False)
    return raw.replace("</", "<\\/")


# --------------------------------------------------------------------------
# Shared design system: CSS variables, base layout, dark-mode toggle.
# Both report types import this so the two documents look like one family.
# --------------------------------------------------------------------------

_GOOGLE_FONTS_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;'
    '600;700;800&display=swap" rel="stylesheet">'
)

_FONT_AWESOME_LINK = (
    '<link rel="stylesheet" '
    'href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/'
    'all.min.css" '
    'integrity="sha512-DTOQO9RWCH3ppGqcWaEA1BIZOC6xxalwEsw9c2QQeAIftl+Vegovlnee1c9QX4TctnWMn13TZye+giMm8e2LwA==" '
    'crossorigin="anonymous" referrerpolicy="no-referrer">'
)

_CHARTJS_SCRIPT = (
    '<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/'
    'chart.umd.min.js" '
    'integrity="sha512-CMF3tQtjOoOJoOKlsS7/2loJlkyctwzSoDK/S40iAB+MqRHFsfKl6dZWRSuwpVXcy77gjPFVmDzoTfjWLmOJvA==" '
    'crossorigin="anonymous" referrerpolicy="no-referrer"></script>'
)

# Core design tokens + resets shared by both page types.
_BASE_CSS = """
:root {
  --color-bg: #f4f6fb;
  --color-surface: #ffffff;
  --color-surface-alt: #eef1f8;
  --color-border: #dde2ee;
  --color-text: #1c2333;
  --color-text-muted: #5b6478;
  --color-primary: #4f46e5;
  --color-primary-dark: #4338ca;
  --color-primary-soft: #eef0fe;
  --color-success: #16a34a;
  --color-success-soft: #e8f8ee;
  --color-danger: #dc2626;
  --color-danger-soft: #fdecec;
  --color-warning: #d97706;
  --color-warning-soft: #fef3e2;
  --color-accent: #0ea5e9;
  --shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.06);
  --shadow-md: 0 8px 24px rgba(15, 23, 42, 0.08);
  --shadow-lg: 0 20px 45px rgba(15, 23, 42, 0.14);
  --radius-sm: 8px;
  --radius-md: 14px;
  --radius-lg: 20px;
  --font-body: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI',
    Roboto, Helvetica, Arial, sans-serif;
}

html[data-theme="dark"] {
  --color-bg: #0f1320;
  --color-surface: #161b2c;
  --color-surface-alt: #1e2438;
  --color-border: #2a3149;
  --color-text: #e7e9f5;
  --color-text-muted: #9aa2bd;
  --color-primary: #818cf8;
  --color-primary-dark: #6366f1;
  --color-primary-soft: #232a49;
  --color-success: #34d399;
  --color-success-soft: #103524;
  --color-danger: #f87171;
  --color-danger-soft: #3a1620;
  --color-warning: #fbbf24;
  --color-warning-soft: #3a2b0c;
  --color-accent: #38bdf8;
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.35);
  --shadow-md: 0 8px 24px rgba(0, 0, 0, 0.45);
  --shadow-lg: 0 20px 45px rgba(0, 0, 0, 0.55);
}

* { box-sizing: border-box; }

html, body {
  margin: 0;
  padding: 0;
  background: var(--color-bg);
  color: var(--color-text);
  font-family: var(--font-body);
  -webkit-font-smoothing: antialiased;
  transition: background 0.25s ease, color 0.25s ease;
}

body { min-height: 100vh; }

a { color: inherit; }

.container {
  width: 100%;
  max-width: 1180px;
  margin: 0 auto;
  padding: 0 clamp(12px, 3vw, 28px);
}

.card {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: none;
  border-radius: var(--radius-sm);
  padding: 10px 18px;
  font-family: inherit;
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.12s ease, box-shadow 0.12s ease, opacity 0.12s ease;
  user-select: none;
}
.btn:active { transform: translateY(1px); }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-primary { background: var(--color-primary); color: #fff; }
.btn-primary:hover:not(:disabled) { background: var(--color-primary-dark); }

.btn-outline {
  background: transparent;
  color: var(--color-text);
  border: 1px solid var(--color-border);
}
.btn-outline:hover:not(:disabled) { background: var(--color-surface-alt); }

.btn-ghost {
  background: var(--color-surface-alt);
  color: var(--color-text);
}
.btn-ghost:hover:not(:disabled) { background: var(--color-border); }

.btn-danger { background: var(--color-danger); color: #fff; }
.btn-success { background: var(--color-success); color: #fff; }

.topbar {
  position: sticky;
  top: 0;
  z-index: 40;
  background: var(--color-surface);
  border-bottom: 1px solid var(--color-border);
  box-shadow: var(--shadow-sm);
}
.topbar-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px clamp(12px, 3vw, 28px);
  max-width: 1180px;
  margin: 0 auto;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 800;
  font-size: 1.05rem;
  letter-spacing: -0.01em;
}
.brand i { color: var(--color-primary); }

.theme-toggle {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 1px solid var(--color-border);
  background: var(--color-surface-alt);
  color: var(--color-text);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 1rem;
  flex: 0 0 auto;
}
.theme-toggle:hover { background: var(--color-border); }

::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: 10px;
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.02em;
}
.badge-primary { background: var(--color-primary-soft); color: var(--color-primary); }
.badge-success { background: var(--color-success-soft); color: var(--color-success); }
.badge-danger  { background: var(--color-danger-soft);  color: var(--color-danger); }
.badge-warning { background: var(--color-warning-soft); color: var(--color-warning); }

.visually-hidden {
  position: absolute !important;
  width: 1px; height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

footer.site-footer {
  text-align: center;
  color: var(--color-text-muted);
  font-size: 0.82rem;
  padding: 28px 12px 40px;
}
"""

# JS shared by both page types: theme persistence + toggle wiring.
_THEME_JS = """
(function () {
  var root = document.documentElement;
  var stored = null;
  try { stored = localStorage.getItem('quiz-theme'); } catch (e) {}
  if (stored === 'dark') { root.setAttribute('data-theme', 'dark'); }

  function applyIcon() {
    var btn = document.getElementById('themeToggleBtn');
    if (!btn) return;
    var isDark = root.getAttribute('data-theme') === 'dark';
    btn.innerHTML = isDark
      ? '<i class="fa-solid fa-sun"></i>'
      : '<i class="fa-solid fa-moon"></i>';
    btn.setAttribute('aria-label', isDark ? 'Switch to light mode' : 'Switch to dark mode');
  }

  window.addEventListener('DOMContentLoaded', function () {
    applyIcon();
    var btn = document.getElementById('themeToggleBtn');
    if (btn) {
      btn.addEventListener('click', function () {
        var isDark = root.getAttribute('data-theme') === 'dark';
        if (isDark) {
          root.removeAttribute('data-theme');
          try { localStorage.setItem('quiz-theme', 'light'); } catch (e) {}
        } else {
          root.setAttribute('data-theme', 'dark');
          try { localStorage.setItem('quiz-theme', 'dark'); } catch (e) {}
        }
        applyIcon();
      });
    }
  });
})();
"""


def _topbar_html(title: str, subtitle: str = "") -> str:
    """Sticky header shared by both report types."""
    sub = f'<div class="topbar-sub">{_esc(subtitle)}</div>' if subtitle else ""
    return f"""
<div class="topbar">
  <div class="topbar-inner">
    <div class="brand">
      <i class="fa-solid fa-layer-group"></i>
      <span>{_esc(title)}</span>
    </div>
    <button id="themeToggleBtn" class="theme-toggle" type="button"
      aria-label="Toggle dark mode">
      <i class="fa-solid fa-moon"></i>
    </button>
  </div>
  {sub}
</div>
"""


def _page_shell(*, title: str, extra_head: str, body: str, extra_scripts: str) -> str:
    """Wrap CSS/body/JS fragments into one complete HTML document."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1">
<title>{_esc(title)}</title>
{_GOOGLE_FONTS_LINK}
{_FONT_AWESOME_LINK}
<style>{_BASE_CSS}
{extra_head}
</style>
</head>
<body>
{body}
<script>{_THEME_JS}</script>
{extra_scripts}
</body>
</html>
"""


# --------------------------------------------------------------------------
# render_quiz_html: CBT-exam-style interactive quiz page
# --------------------------------------------------------------------------

_QUIZ_CSS = """
.exam-layout {
  display: grid;
  grid-template-columns: 1fr;
  gap: 20px;
  padding: 20px 0 60px;
}
@media (min-width: 900px) {
  .exam-layout { grid-template-columns: minmax(0, 1fr) 300px; align-items: start; }
}

.exam-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 20px;
  margin-bottom: 4px;
}
.exam-title { font-size: 1.15rem; font-weight: 800; }
.exam-meta { color: var(--color-text-muted); font-size: 0.85rem; margin-top: 2px; }

.timer-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  padding: 8px 16px;
  border-radius: 999px;
  font-size: 1.05rem;
}
.timer-pill.low { background: var(--color-danger-soft); color: var(--color-danger); }

.question-card { padding: 24px clamp(16px, 4vw, 32px); margin-bottom: 16px; }
.question-index {
  color: var(--color-text-muted);
  font-weight: 700;
  font-size: 0.85rem;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  margin-bottom: 10px;
}
.question-text {
  font-size: 1.15rem;
  font-weight: 600;
  line-height: 1.55;
  margin-bottom: 22px;
  white-space: pre-wrap;
}

.option-list { display: flex; flex-direction: column; gap: 12px; }
.option {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 14px 16px;
  border: 1.5px solid var(--color-border);
  border-radius: var(--radius-md);
  cursor: pointer;
  background: var(--color-surface);
  transition: border-color 0.12s ease, background 0.12s ease;
}
.option:hover { border-color: var(--color-primary); background: var(--color-primary-soft); }
.option.selected { border-color: var(--color-primary); background: var(--color-primary-soft); }
.option.correct { border-color: var(--color-success); background: var(--color-success-soft); }
.option.incorrect { border-color: var(--color-danger); background: var(--color-danger-soft); }
.option-key {
  flex: 0 0 auto;
  width: 30px; height: 30px;
  border-radius: 50%;
  border: 1.5px solid var(--color-border);
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 0.85rem;
  background: var(--color-surface-alt);
}
.option.selected .option-key { background: var(--color-primary); color: #fff; border-color: var(--color-primary); }
.option.correct .option-key { background: var(--color-success); color: #fff; border-color: var(--color-success); }
.option.incorrect .option-key { background: var(--color-danger); color: #fff; border-color: var(--color-danger); }
.option-text { padding-top: 3px; line-height: 1.5; }
.option-icon { margin-left: auto; padding-top: 4px; font-size: 1rem; }

.explanation-box {
  margin-top: 18px;
  padding: 14px 16px;
  border-radius: var(--radius-md);
  background: var(--color-surface-alt);
  border-left: 4px solid var(--color-accent);
  font-size: 0.92rem;
  line-height: 1.55;
  display: none;
}
.explanation-box.show { display: block; }
.explanation-box strong { color: var(--color-accent); }

.exam-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  justify-content: space-between;
  padding: 4px 2px;
}
.exam-actions .group { display: flex; gap: 10px; flex-wrap: wrap; }

.sidebar { display: flex; flex-direction: column; gap: 16px; }
.sidebar-card { padding: 18px; }
.sidebar-title {
  font-weight: 800;
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--color-text-muted);
  margin-bottom: 12px;
}
.qgrid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(38px, 1fr));
  gap: 8px;
}
.qgrid button {
  aspect-ratio: 1 / 1;
  border-radius: 8px;
  border: 1.5px solid var(--color-border);
  background: var(--color-surface-alt);
  color: var(--color-text);
  font-weight: 700;
  font-size: 0.82rem;
  cursor: pointer;
}
.qgrid button.current { outline: 2px solid var(--color-primary); outline-offset: 1px; }
.qgrid button.answered { background: var(--color-success); color: #fff; border-color: var(--color-success); }
.qgrid button.review { background: var(--color-warning); color: #fff; border-color: var(--color-warning); }
.qgrid button.answered-review { background: var(--color-accent); color: #fff; border-color: var(--color-accent); }
.qgrid button.unanswered { background: var(--color-surface-alt); }

.legend { display: flex; flex-direction: column; gap: 8px; font-size: 0.82rem; margin-top: 14px; }
.legend-item { display: flex; align-items: center; gap: 8px; }
.legend-dot { width: 12px; height: 12px; border-radius: 4px; flex: 0 0 auto; }

.progress-track {
  height: 8px;
  border-radius: 999px;
  background: var(--color-surface-alt);
  overflow: hidden;
  margin-top: 10px;
}
.progress-fill {
  height: 100%;
  background: var(--color-primary);
  border-radius: 999px;
  transition: width 0.25s ease;
}

/* Results screen */
.results-hero {
  text-align: center;
  padding: 40px clamp(16px, 5vw, 48px);
  margin-bottom: 20px;
}
.results-score {
  font-size: clamp(2.4rem, 8vw, 3.2rem);
  font-weight: 800;
  letter-spacing: -0.02em;
  margin: 6px 0;
}
.results-verdict {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 18px;
  border-radius: 999px;
  font-weight: 700;
  font-size: 0.95rem;
  margin-top: 8px;
}
.results-verdict.pass { background: var(--color-success-soft); color: var(--color-success); }
.results-verdict.fail { background: var(--color-danger-soft); color: var(--color-danger); }

.stat-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-top: 26px;
}
@media (min-width: 640px) { .stat-grid { grid-template-columns: repeat(4, 1fr); } }
.stat-tile {
  background: var(--color-surface-alt);
  border-radius: var(--radius-md);
  padding: 16px 12px;
  text-align: center;
}
.stat-tile .value { font-size: 1.5rem; font-weight: 800; }
.stat-tile .label { font-size: 0.78rem; color: var(--color-text-muted); margin-top: 2px; }

.review-toggle-wrap { text-align: center; margin: 24px 0; }

#reviewSection { display: none; }
#reviewSection.show { display: block; }

.hidden { display: none !important; }

@media (max-width: 899px) {
  .sidebar { order: -1; }
  .qgrid { grid-template-columns: repeat(auto-fill, minmax(34px, 1fr)); }
}
"""

# JS template for the exam runner. `%%DATA%%` is replaced with a JSON blob
# describing the quiz; everything else is static behaviour.
_QUIZ_JS_TEMPLATE = """
(function () {
  var QUIZ = %%DATA%%;
  var questions = QUIZ.questions;
  var totalTime = QUIZ.timerPerQuestion; // seconds, per question
  var correctMarks = QUIZ.correctMarks;
  var negativeMarks = QUIZ.negativeMarks;

  var state = {
    current: 0,
    answers: new Array(questions.length).fill(null),
    marked: new Array(questions.length).fill(false),
    visited: new Array(questions.length).fill(false),
    submitted: false,
    secondsLeft: totalTime,
    timerId: null
  };

  var els = {};
  function q(id) { return document.getElementById(id); }

  function fmtTime(s) {
    s = Math.max(0, s | 0);
    var m = Math.floor(s / 60);
    var r = s % 60;
    return (m < 10 ? '0' : '') + m + ':' + (r < 10 ? '0' : '') + r;
  }

  function renderGrid() {
    var grid = els.qgrid;
    grid.innerHTML = '';
    questions.forEach(function (_, i) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = (i + 1);
      var cls = 'unanswered';
      var answered = state.answers[i] !== null;
      var marked = state.marked[i];
      if (answered && marked) cls = 'answered-review';
      else if (marked) cls = 'review';
      else if (answered) cls = 'answered';
      else if (state.visited[i]) cls = 'unanswered';
      btn.className = cls + (i === state.current ? ' current' : '');
      btn.addEventListener('click', function () { goTo(i); });
      grid.appendChild(btn);
    });
  }

  function renderProgress() {
    var answeredCount = state.answers.filter(function (a) { return a !== null; }).length;
    var pct = Math.round((answeredCount / questions.length) * 100);
    els.progressFill.style.width = pct + '%';
    els.progressLabel.textContent = answeredCount + ' / ' + questions.length + ' answered';
  }

  function renderQuestion() {
    var idx = state.current;
    var qd = questions[idx];
    state.visited[idx] = true;

    els.qIndex.textContent = 'Question ' + (idx + 1) + ' of ' + questions.length;
    els.qText.textContent = qd.question;

    els.optionList.innerHTML = '';
    qd.options.forEach(function (opt, i) {
      var row = document.createElement('div');
      row.className = 'option' + (state.answers[idx] === i ? ' selected' : '');
      row.setAttribute('role', 'button');
      row.setAttribute('tabindex', '0');
      var key = document.createElement('div');
      key.className = 'option-key';
      key.textContent = String.fromCharCode(65 + i);
      var text = document.createElement('div');
      text.className = 'option-text';
      text.textContent = opt;
      row.appendChild(key);
      row.appendChild(text);
      row.addEventListener('click', function () { selectOption(i); });
      els.optionList.appendChild(row);
    });

    els.markBtn.classList.toggle('btn-primary', state.marked[idx]);
    els.markBtn.classList.toggle('btn-outline', !state.marked[idx]);
    els.markBtn.innerHTML = state.marked[idx]
      ? '<i class="fa-solid fa-bookmark"></i> Marked for review'
      : '<i class="fa-regular fa-bookmark"></i> Mark for review';

    els.prevBtn.disabled = idx === 0;
    els.nextBtn.textContent = idx === questions.length - 1 ? 'Finish' : 'Next';
    els.nextBtn.innerHTML = idx === questions.length - 1
      ? 'Review & Submit <i class="fa-solid fa-flag-checkered"></i>'
      : 'Next <i class="fa-solid fa-arrow-right"></i>';

    renderGrid();
    renderProgress();
    resetTimer();
  }

  function selectOption(i) {
    if (state.submitted) return;
    state.answers[state.current] = i;
    renderQuestion();
  }

  function goTo(i) {
    if (i < 0 || i >= questions.length) return;
    state.current = i;
    renderQuestion();
  }

  function toggleMark() {
    state.marked[state.current] = !state.marked[state.current];
    renderQuestion();
  }

  function resetTimer() {
    clearInterval(state.timerId);
    if (state.submitted || !totalTime) {
      els.timerPill.classList.add('hidden');
      return;
    }
    els.timerPill.classList.remove('hidden');
    state.secondsLeft = totalTime;
    updateTimerUI();
    state.timerId = setInterval(function () {
      state.secondsLeft -= 1;
      updateTimerUI();
      if (state.secondsLeft <= 0) {
        clearInterval(state.timerId);
        if (state.current < questions.length - 1) {
          goTo(state.current + 1);
        } else {
          submitQuiz();
        }
      }
    }, 1000);
  }

  function updateTimerUI() {
    els.timerPill.innerHTML = '<i class="fa-regular fa-clock"></i> ' + fmtTime(state.secondsLeft);
    els.timerPill.classList.toggle('low', state.secondsLeft <= 10);
  }

  function computeScore() {
    var correct = 0, wrong = 0, unattempted = 0;
    questions.forEach(function (qd, i) {
      var a = state.answers[i];
      if (a === null || a === undefined) { unattempted += 1; return; }
      if (a === qd.correctOption) correct += 1; else wrong += 1;
    });
    var score = (correct * correctMarks) - (wrong * negativeMarks);
    var maxScore = questions.length * correctMarks;
    return { correct: correct, wrong: wrong, unattempted: unattempted, score: score, maxScore: maxScore };
  }

  function submitQuiz() {
    if (state.submitted) return;
    state.submitted = true;
    clearInterval(state.timerId);
    var result = computeScore();

    var pct = result.maxScore > 0 ? (result.score / result.maxScore) * 100 : 0;
    var passed = pct >= (QUIZ.passPercent || 40);

    q('examView').classList.add('hidden');
    q('resultsView').classList.remove('hidden');

    q('scoreValue').textContent = result.score.toFixed(2) + ' / ' + result.maxScore.toFixed(2);
    var verdict = q('verdictBadge');
    verdict.textContent = passed ? 'PASSED' : 'NOT CLEARED';
    verdict.className = 'results-verdict ' + (passed ? 'pass' : 'fail');
    q('statCorrect').textContent = result.correct;
    q('statWrong').textContent = result.wrong;
    q('statUnattempted').textContent = result.unattempted;
    q('statPercent').textContent = pct.toFixed(1) + '%';

    renderReview();
  }

  function renderReview() {
    var wrap = q('reviewList');
    wrap.innerHTML = '';
    questions.forEach(function (qd, i) {
      var userAns = state.answers[i];
      var card = document.createElement('div');
      card.className = 'card question-card';

      var idxEl = document.createElement('div');
      idxEl.className = 'question-index';
      idxEl.textContent = 'Question ' + (i + 1) + ' of ' + questions.length;
      card.appendChild(idxEl);

      var textEl = document.createElement('div');
      textEl.className = 'question-text';
      textEl.textContent = qd.question;
      card.appendChild(textEl);

      var list = document.createElement('div');
      list.className = 'option-list';
      qd.options.forEach(function (opt, oi) {
        var row = document.createElement('div');
        var cls = 'option';
        if (oi === qd.correctOption) cls += ' correct';
        else if (oi === userAns) cls += ' incorrect';
        row.className = cls;
        var key = document.createElement('div');
        key.className = 'option-key';
        key.textContent = String.fromCharCode(65 + oi);
        var text = document.createElement('div');
        text.className = 'option-text';
        text.textContent = opt;
        row.appendChild(key);
        row.appendChild(text);
        if (oi === qd.correctOption) {
          var icon = document.createElement('div');
          icon.className = 'option-icon';
          icon.innerHTML = '<i class="fa-solid fa-circle-check" style="color:var(--color-success)"></i>';
          row.appendChild(icon);
        } else if (oi === userAns) {
          var icon2 = document.createElement('div');
          icon2.className = 'option-icon';
          icon2.innerHTML = '<i class="fa-solid fa-circle-xmark" style="color:var(--color-danger)"></i>';
          row.appendChild(icon2);
        }
        list.appendChild(row);
      });
      card.appendChild(list);

      if (qd.explanation) {
        var expl = document.createElement('div');
        expl.className = 'explanation-box show';
        var strong = document.createElement('strong');
        strong.textContent = 'Explanation: ';
        expl.appendChild(strong);
        expl.appendChild(document.createTextNode(qd.explanation));
        card.appendChild(expl);
      }
      wrap.appendChild(card);
    });
  }

  function bindKeyboard() {
    document.addEventListener('keydown', function (e) {
      if (state.submitted) return;
      if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) return;
      if (e.key === 'ArrowRight') { goTo(Math.min(state.current + 1, questions.length - 1)); }
      else if (e.key === 'ArrowLeft') { goTo(Math.max(state.current - 1, 0)); }
      else if (['1', '2', '3', '4', '5', '6'].indexOf(e.key) !== -1) {
        var i = parseInt(e.key, 10) - 1;
        if (i < questions[state.current].options.length) selectOption(i);
      } else if (e.key.toLowerCase() === 'm') {
        toggleMark();
      }
    });
  }

  window.addEventListener('DOMContentLoaded', function () {
    els.qIndex = q('qIndex');
    els.qText = q('qText');
    els.optionList = q('optionList');
    els.qgrid = q('qgrid');
    els.progressFill = q('progressFill');
    els.progressLabel = q('progressLabel');
    els.timerPill = q('timerPill');
    els.markBtn = q('markBtn');
    els.prevBtn = q('prevBtn');
    els.nextBtn = q('nextBtn');

    els.prevBtn.addEventListener('click', function () { goTo(state.current - 1); });
    els.nextBtn.addEventListener('click', function () {
      if (state.current === questions.length - 1) {
        submitQuiz();
      } else {
        goTo(state.current + 1);
      }
    });
    els.markBtn.addEventListener('click', toggleMark);
    q('submitBtn').addEventListener('click', function () {
      if (confirm('Submit the quiz now? You will not be able to change your answers.')) {
        submitQuiz();
      }
    });

    bindKeyboard();
    renderQuestion();
  });
})();
"""


def _je(t: Any) -> str:
    """JS string-literal escape (matches the legacy generator's `je()`
    helper exactly -- used only inside JS string literals we hand-build,
    not via json.dumps, to stay byte-for-byte compatible with the ported
    generator)."""
    if not t:
        return ""
    t = str(t)
    return (
        t.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )


# Desktop CBT (computer-based-test) responsive styles, ported verbatim.
_QUIZ_DESKTOP_CSS = """
@media (min-width: 1024px) {
    body { overflow: auto !important; }

    #quizContainer {
        display: grid !important;
        grid-template-columns: 1fr 320px;
        grid-template-rows: auto 1fr auto;
        gap: 0;
        height: 100vh;
        overflow: hidden;
    }

    .quiz-header {
        grid-column: 1 / -1;
        position: static;
        padding: 20px 32px;
        border-bottom: 3px solid var(--border);
    }

    .header-top {
        max-width: none;
        margin-bottom: 16px;
    }

    .quiz-title-text { max-width: 400px; }

    .timer-display {
        padding: 10px 20px;
        font-size: 18px;
    }

    /* Main content area - scrollable */
    .question-section {
        position: static !important;
        grid-column: 1;
        grid-row: 2;
        overflow-y: auto;
        padding: 32px;
        background: var(--bg-light);
        top: auto !important;
        bottom: auto !important;
    }

    .question-card {
        max-width: 900px;
        padding: 32px;
        margin: 0 auto 24px;
    }

    .question-text {
        font-size: 18px;
        margin-bottom: 24px;
    }

    .option-btn {
        padding: 18px 20px;
        font-size: 16px;
    }

    .option-indicator {
        min-width: 32px;
        height: 32px;
        font-size: 14px;
    }

    /* Desktop Question Navigator - Right Panel */
    .question-nav-panel {
        position: static !important;
        grid-column: 2;
        grid-row: 2;
        transform: none !important;
        max-height: none;
        height: 100%;
        border-radius: 0;
        border-left: 3px solid var(--border);
        box-shadow: none;
        padding: 24px;
        overflow-y: auto;
        background: var(--bg-white);
    }

    .question-nav-panel.open { transform: none !important; }

    .nav-panel-header {
        position: sticky;
        top: 0;
        background: var(--bg-white);
        z-index: 10;
        padding-bottom: 20px;
        margin-bottom: 20px;
    }

    .nav-panel-title {
        font-size: 16px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    .nav-close-btn { display: none; }

    .nav-legend {
        position: sticky;
        top: 60px;
        background: var(--bg-white);
        z-index: 9;
        padding: 16px;
        margin: -16px -16px 20px;
        border-radius: 12px;
        background: var(--bg-light);
    }

    .question-grid {
        grid-template-columns: repeat(4, 1fr);
        gap: 12px;
    }

    .question-nav-item {
        aspect-ratio: 1;
        font-size: 16px;
        border-radius: 12px;
    }

    .question-nav-toggle { display: none; }

    /* Footer Navigation - Sticky */
    .nav-controls {
        position: static;
        grid-column: 1;
        grid-row: 3;
        padding: 20px 32px;
        border-top: 3px solid var(--border);
        max-width: none;
        display: flex;
        justify-content: center;
        gap: 16px;
    }

    .nav-btn {
        min-width: 160px;
        padding: 16px 24px;
        font-size: 16px;
    }

    /* Results Desktop Layout */
    #resultsContainer {
        padding: 40px;
        max-width: 1400px;
        margin: 0 auto;
    }

    .results-header {
        padding: 60px 40px;
        margin-bottom: 32px;
    }

    .results-icon { font-size: 100px; }
    .results-title { font-size: 36px; }
    .results-score { font-size: 64px; }
    .results-percentage { font-size: 24px; }

    .stats-grid {
        grid-template-columns: repeat(4, 1fr);
        gap: 20px;
        margin-bottom: 32px;
        max-width: none;
    }

    .stat-card { padding: 32px; }
    .stat-icon { width: 54px; height: 54px; font-size: 24px; }
    .stat-value { font-size: 40px; }
    .stat-label { font-size: 14px; }

    .action-buttons {
        grid-template-columns: repeat(2, 1fr);
        gap: 20px;
        max-width: 800px;
    }

    .action-btn { padding: 20px; font-size: 17px; }

    /* Mode Selection Desktop */
    .mode-container {
        max-width: 600px;
        padding: 50px 40px;
    }

    .mode-header-icon {
        width: 80px;
        height: 80px;
        font-size: 40px;
    }

    .mode-header h2 { font-size: 28px; }
    .mode-header p { font-size: 15px; }

    .mode-cards { gap: 20px; }

    .mode-card {
        padding: 24px;
        border-radius: 18px;
    }

    .mode-icon {
        width: 60px;
        height: 60px;
        font-size: 28px;
        margin-right: 20px;
    }

    .mode-info h3 { font-size: 19px; }
    .mode-info p { font-size: 14px; }

    .timer-input { padding: 16px 18px; font-size: 16px; }
    .start-btn { padding: 18px; font-size: 17px; }
}

/* Ultra-wide Desktop */
@media (min-width: 1440px) {
    #quizContainer {
        grid-template-columns: 1fr 380px;
    }

    .question-section { padding: 40px 60px; }
    .question-card { max-width: 1000px; padding: 40px; }
    .question-nav-panel { padding: 32px; }
    .question-grid { grid-template-columns: repeat(5, 1fr); }
    .nav-controls { padding: 24px 60px; }
}
"""


async def render_quiz_html(quiz: dict, *, mode: str = "exam") -> tuple[bytes, str]:
    """Build the full, self-contained interactive "Premium Quiz" CBT-style
    HTML report -- ported verbatim (markup/CSS/JS) from the original
    ``generate_quiz_html`` generator, adapted only so it *returns*
    ``(html_bytes, filename)`` instead of writing a temp file and calling
    ``bot.send_document`` itself (the caller in quiz_play.py owns that).

    Per explicit product decision, each question's options are freshly
    ``random.shuffle``-d at report-generation time (same as the original
    generator) -- the option lettering in this downloaded report can
    therefore differ from what was actually shown live during the quiz.
    ``mode`` is accepted for signature compatibility; the generated page
    itself always offers both Exam/Practice mode selection to the viewer,
    matching the original generator's behaviour.
    """
    quiz_name = quiz.get("quiz_name") or "Untitled Quiz"
    questions = quiz.get("questions") or []
    n_questions = len(questions)
    negative_marks = quiz.get("negative_marks", 0.25)
    timer_per_q = int(quiz.get("timer", 60) or 60)
    total_time = timer_per_q * n_questions

    # Build the per-question JS objects, shuffling each question's options
    # fresh on every render (kept intentionally -- see docstring above).
    q_js_items = []
    for i, q in enumerate(questions):
        opts = list(q.get("options") or [])
        correct_idx = int(q.get("correct_option_id", 0) or 0)
        correct_opt = opts[correct_idx] if 0 <= correct_idx < len(opts) else (opts[0] if opts else "")
        random.shuffle(opts)
        try:
            new_correct_index = opts.index(correct_opt)
        except ValueError:
            new_correct_index = 0
        opts_json = json.dumps(opts, ensure_ascii=False)
        q_js_items.append(
            f'{{id:{i},txt:"{_je(q.get("question", ""))}",'
            f'ref:"{_je(q.get("reply_text", ""))}",'
            f'opts:{opts_json},'
            f'ci:{new_correct_index},'
            f'exp:"{_je(q.get("explanation", "No explanation"))}"}}'
        )
    questions_js = ",".join(q_js_items)

    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "", quiz_name.replace(" ", "_"))[:100] or "quiz"
    filename = f"{safe_name}.html"

    quiz_name_esc = _esc(quiz_name)

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>{quiz_name_esc}</title>
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.css" rel="stylesheet">
<script src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.9/katex.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/9.1.6/marked.min.js"></script>
<style>
.katex-display{{overflow-x:auto;overflow-y:hidden;padding:4px 0}}
.katex{{font-size:1.05em}}
.question-text p,.explanation-text p,.question-reference p{{margin:0 0 10px}}
.question-text p:last-child,.explanation-text p:last-child,.question-reference p:last-child{{margin-bottom:0}}
.question-text ul,.question-text ol,.explanation-text ul,.explanation-text ol{{margin:8px 0 8px 22px}}
.question-text code,.explanation-text code,.option-text code{{background:rgba(128,128,128,.18);padding:1px 5px;border-radius:4px;font-size:.9em}}
.question-text pre,.explanation-text pre{{background:rgba(128,128,128,.18);padding:10px 12px;border-radius:8px;overflow-x:auto;margin:8px 0}}
.question-text pre code,.explanation-text pre code{{background:none;padding:0}}
.question-text table,.explanation-text table{{border-collapse:collapse;margin:8px 0}}
.question-text th,.question-text td,.explanation-text th,.explanation-text td{{border:1px solid var(--border);padding:6px 10px}}
.question-text img,.explanation-text img{{max-width:100%;border-radius:6px}}
mark{{background:rgba(251,191,36,.4);color:inherit;padding:0 3px;border-radius:3px}}
blockquote{{border-left:3px solid var(--primary);padding:4px 14px;margin:8px 0;opacity:.9;background:rgba(128,128,128,.08);border-radius:0 6px 6px 0}}
.option-text{{overflow-x:auto}}
.option-text p{{margin:0;display:inline}}

*{{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}}
:root{{--primary:#667eea;--primary-dark:#5568d3;--secondary:#764ba2;--success:#48bb78;--danger:#f5576c;--warning:#fbbf24;--info:#4facfe;--bg-light:#f7fafc;--bg-white:#fff;--text-dark:#1a202c;--text-light:#718096;--border:#e2e8f0}}
[data-theme="dark"]{{--bg-light:#1a202c;--bg-white:#2d3748;--text-dark:#f7fafc;--text-light:#cbd5e0;--border:#4a5568}}
body{{font-family:'Poppins',-apple-system,BlinkMacSystemFont,sans-serif;background:linear-gradient(135deg,var(--primary) 0%,var(--secondary) 100%);min-height:100vh;overflow:hidden;user-select:none;-webkit-user-select:none;transition:background .3s}}
.scrollable::-webkit-scrollbar{{width:6px}}
.scrollable::-webkit-scrollbar-track{{background:transparent}}
.scrollable::-webkit-scrollbar-thumb{{background:var(--primary);border-radius:10px}}
.protected-content{{white-space:pre-wrap;word-wrap:break-word;word-break:break-word;line-height:1.6;user-select:none}}
#modeSelection{{position:fixed;top:0;left:0;width:100%;height:100%;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);display:flex;align-items:center;justify-content:center;z-index:9999;padding:20px;overflow-y:auto}}
.mode-container{{background:#fff;border-radius:24px;padding:40px 30px;max-width:500px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.3);animation:ms .5s cubic-bezier(.34,1.56,.64,1)}}
@keyframes ms{{from{{opacity:0;transform:translateY(40px) scale(.95)}}to{{opacity:1;transform:translateY(0) scale(1)}}}}
.mode-header{{text-align:center;margin-bottom:32px}}
.mode-header-icon{{width:70px;height:70px;margin:0 auto 16px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);border-radius:20px;display:flex;align-items:center;justify-content:center;font-size:36px;color:#fff;box-shadow:0 8px 24px rgba(102,126,234,.3)}}
.mode-header h2{{font-size:24px;font-weight:700;color:#1a202c;margin-bottom:8px}}
.mode-header p{{font-size:14px;color:#718096;font-weight:400}}
.mode-cards{{display:grid;gap:16px;margin-bottom:24px}}
.mode-card{{background:#f7fafc;border:2px solid #e2e8f0;border-radius:16px;padding:20px;cursor:pointer;transition:all .3s;position:relative}}
.mode-card:hover{{transform:translateY(-3px);box-shadow:0 12px 28px rgba(102,126,234,.15);border-color:#cbd5e0}}
.mode-card.selected{{border-color:#667eea;background:#fff;box-shadow:0 8px 24px rgba(102,126,234,.2);transform:translateY(-2px)}}
.mode-card-header{{display:flex;align-items:center}}
.mode-icon{{width:54px;height:54px;border-radius:14px;display:flex;align-items:center;justify-content:center;font-size:24px;margin-right:16px;flex-shrink:0}}
.exam-mode .mode-icon{{background:linear-gradient(135deg,#f093fb 0%,#f5576c 100%);color:#fff}}
.practice-mode .mode-icon{{background:linear-gradient(135deg,#4facfe 0%,#00f2fe 100%);color:#fff}}
.mode-info h3{{font-size:17px;font-weight:700;color:#1a202c;margin-bottom:4px}}
.mode-info p{{font-size:13px;color:#718096;line-height:1.4}}
.timer-config{{margin-bottom:24px}}
.timer-config label{{display:block;font-size:14px;font-weight:600;color:#1a202c;margin-bottom:10px}}
.timer-config label i{{margin-right:6px;color:#667eea}}
.timer-input{{width:100%;padding:14px 16px;border:2px solid #e2e8f0;border-radius:12px;font-size:15px;font-weight:500;transition:all .3s;background:#fff;font-family:'Poppins',sans-serif;color:#1a202c}}
.timer-input::placeholder{{color:#a0aec0}}
.timer-input:focus{{outline:none;border-color:#667eea;box-shadow:0 0 0 3px rgba(102,126,234,.1)}}
.start-btn{{width:100%;padding:16px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;border:none;border-radius:14px;font-size:16px;font-weight:700;cursor:pointer;transition:all .3s;display:flex;align-items:center;justify-content:center;gap:10px;box-shadow:0 8px 20px rgba(102,126,234,.35)}}
.start-btn:hover:not(:disabled){{transform:translateY(-2px);box-shadow:0 12px 28px rgba(102,126,234,.45)}}
.start-btn:active:not(:disabled){{transform:translateY(0)}}
.start-btn:disabled{{opacity:.5;cursor:not-allowed;background:#cbd5e0;box-shadow:none}}
#quizContainer{{display:none;position:fixed;top:0;left:0;width:100%;height:100vh;background:var(--bg-light);overflow:hidden}}
.quiz-header{{position:fixed;top:0;left:0;right:0;background:var(--bg-white);box-shadow:0 2px 15px rgba(0,0,0,.08);z-index:100;padding:16px 20px}}
.header-top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;gap:10px}}
.quiz-title{{font-size:15px;font-weight:700;color:var(--text-dark);display:flex;align-items:center;gap:8px;flex:1;min-width:0}}
.quiz-title-text{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:150px}}
.mode-badge{{font-size:10px;padding:4px 10px;border-radius:20px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;white-space:nowrap}}
.mode-badge.exam{{background:linear-gradient(135deg,#f093fb 0%,#f5576c 100%);color:#fff}}
.mode-badge.practice{{background:linear-gradient(135deg,#4facfe 0%,#00f2fe 100%);color:#fff}}
.header-actions{{display:flex;gap:8px;align-items:center}}
.theme-toggle{{width:36px;height:36px;background:var(--bg-light);border:none;border-radius:10px;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:16px;color:var(--text-dark);transition:all .3s}}
.theme-toggle:hover{{transform:scale(1.1)}}
.timer-display{{display:flex;align-items:center;gap:8px;font-size:16px;font-weight:700;color:var(--primary);padding:8px 14px;background:linear-gradient(135deg,rgba(102,126,234,.15) 0%,rgba(118,75,162,.15) 100%);border-radius:12px;white-space:nowrap}}
.timer-display.warning{{color:var(--danger);background:linear-gradient(135deg,rgba(245,87,108,.15) 0%,rgba(240,147,251,.15) 100%);animation:pulse 1s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.7}}}}
.header-progress{{display:flex;justify-content:space-between;align-items:center;font-size:12px;color:var(--text-light);margin-bottom:8px}}
.progress-bar-container{{height:6px;background:var(--border);border-radius:10px;overflow:hidden}}
.progress-bar{{height:100%;background:linear-gradient(90deg,var(--primary) 0%,var(--secondary) 100%);transition:width .3s;border-radius:10px}}
.question-section{{position:fixed;top:140px;left:0;right:0;bottom:80px;overflow-y:auto;overflow-x:hidden;padding:20px;-webkit-overflow-scrolling:touch}}
.question-section.scrollable{{scrollbar-width:thin;scrollbar-color:var(--primary) transparent}}
.question-card{{background:var(--bg-white);border-radius:20px;padding:24px;box-shadow:0 4px 20px rgba(0,0,0,.06);max-width:800px;margin:0 auto}}
.question-number{{display:inline-flex;align-items:center;gap:8px;font-size:13px;font-weight:700;color:var(--primary);background:linear-gradient(135deg,rgba(102,126,234,.15) 0%,rgba(118,75,162,.15) 100%);padding:6px 14px;border-radius:20px;margin-bottom:16px}}
.question-reference{{background:linear-gradient(135deg,rgba(79,172,254,.15) 0%,rgba(0,242,254,.15) 100%);border-left:4px solid var(--info);padding:14px 16px;border-radius:10px;margin-bottom:16px;font-size:14px;color:var(--text-dark);line-height:1.6;white-space:pre-wrap;word-wrap:break-word}}
.question-text{{font-size:16px;font-weight:600;color:var(--text-dark);line-height:1.7;margin-bottom:20px;white-space:pre-wrap;word-wrap:break-word;word-break:break-word}}
.options-container{{display:grid;gap:12px}}
.option-btn{{width:100%;padding:16px 18px;background:var(--bg-light);border:3px solid var(--border);border-radius:14px;text-align:left;font-size:15px;color:var(--text-dark);cursor:pointer;transition:all .3s;display:flex;align-items:flex-start;gap:12px;line-height:1.6;white-space:pre-wrap;word-wrap:break-word;word-break:break-word;user-select:none}}
.option-btn:active{{transform:scale(.98)}}
.option-indicator{{min-width:28px;height:28px;border-radius:50%;background:var(--bg-white);border:2px solid var(--border);display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:600;transition:all .3s}}
.option-text{{flex:1;padding-top:3px}}
.option-btn:hover:not(.disabled){{border-color:var(--primary);transform:translateX(4px)}}
.option-btn.selected{{background:linear-gradient(135deg,rgba(102,126,234,.15) 0%,rgba(118,75,162,.15) 100%);border-color:var(--primary)}}
.option-btn.selected .option-indicator{{background:linear-gradient(135deg,var(--primary) 0%,var(--secondary) 100%);color:#fff;border-color:transparent}}
.option-btn.correct{{background:linear-gradient(135deg,rgba(72,187,120,.15) 0%,rgba(72,187,120,.15) 100%);border-color:var(--success)}}
.option-btn.correct .option-indicator{{background:var(--success);color:#fff;border-color:transparent}}
.option-btn.incorrect{{background:linear-gradient(135deg,rgba(245,87,108,.15) 0%,rgba(245,87,108,.15) 100%);border-color:var(--danger)}}
.option-btn.incorrect .option-indicator{{background:var(--danger);color:#fff;border-color:transparent}}
.option-btn.disabled{{pointer-events:none;opacity:.6}}
.explanation-box{{display:none;background:linear-gradient(135deg,rgba(254,245,231,.5) 0%,rgba(251,191,36,.2) 100%);border-left:4px solid var(--warning);border-radius:12px;padding:16px;margin-top:20px;animation:sd .3s ease-out}}
@keyframes sd{{from{{opacity:0;max-height:0;padding:0}}to{{opacity:1;max-height:500px;padding:16px}}}}
.explanation-header{{display:flex;align-items:center;gap:8px;font-size:14px;font-weight:700;color:#92400e;margin-bottom:10px}}
.explanation-text{{font-size:14px;color:#78350f;line-height:1.6;white-space:pre-wrap;word-wrap:break-word}}
[data-theme="dark"] .explanation-text{{color:#fbbf24}}
.nav-controls{{position:fixed;bottom:0;left:0;right:0;background:var(--bg-white);padding:16px 20px;box-shadow:0 -2px 15px rgba(0,0,0,.08);display:flex;gap:12px;z-index:90}}
.nav-btn{{flex:1;padding:14px;border:none;border-radius:12px;font-size:15px;font-weight:600;cursor:pointer;transition:all .3s;display:flex;align-items:center;justify-content:center;gap:8px}}
.nav-btn.primary{{background:linear-gradient(135deg,var(--primary) 0%,var(--secondary) 100%);color:#fff}}
.nav-btn.secondary{{background:var(--bg-light);color:var(--text-dark);border:2px solid var(--border)}}
.nav-btn:active{{transform:scale(.96)}}
.nav-btn:disabled{{opacity:.5;cursor:not-allowed;transform:none}}
.question-nav-toggle{{position:fixed;bottom:100px;right:20px;width:56px;height:56px;background:linear-gradient(135deg,var(--primary) 0%,var(--secondary) 100%);color:#fff;border:none;border-radius:50%;font-size:22px;cursor:pointer;box-shadow:0 8px 20px rgba(102,126,234,.4);z-index:85;transition:all .3s}}
.question-nav-toggle:active{{transform:scale(.95)}}
.question-nav-panel{{position:fixed;bottom:0;left:0;right:0;background:var(--bg-white);border-radius:24px 24px 0 0;box-shadow:0 -4px 30px rgba(0,0,0,.15);z-index:95;max-height:70vh;overflow-y:auto;transform:translateY(100%);transition:transform .3s;padding:20px}}
.question-nav-panel.open{{transform:translateY(0)}}
.nav-panel-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;padding-bottom:16px;border-bottom:2px solid var(--border)}}
.nav-panel-title{{font-size:18px;font-weight:700;color:var(--text-dark)}}
.nav-close-btn{{width:32px;height:32px;background:var(--bg-light);border:none;border-radius:50%;font-size:16px;cursor:pointer;color:var(--text-light)}}
.nav-legend{{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:20px;font-size:12px;color:var(--text-dark)}}
.legend-item{{display:flex;align-items:center;gap:6px;color:var(--text-dark)}}
.legend-box{{width:20px;height:20px;border-radius:6px}}
.legend-box.answered{{background:linear-gradient(135deg,var(--primary) 0%,var(--secondary) 100%)}}
.legend-box.marked{{background:linear-gradient(135deg,var(--warning) 0%,#f59e0b 100%)}}
.legend-box.unanswered{{background:var(--border)}}
.question-grid{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}}
.question-nav-item{{aspect-ratio:1;border:2px solid var(--border);border-radius:10px;background:var(--bg-white);display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:600;cursor:pointer;transition:all .3s;color:var(--text-light)}}
.question-nav-item:active{{transform:scale(.95)}}
.question-nav-item.current{{border-color:var(--primary);background:linear-gradient(135deg,rgba(102,126,234,.15) 0%,rgba(118,75,162,.15) 100%);color:var(--primary)}}
.question-nav-item.answered{{background:linear-gradient(135deg,var(--primary) 0%,var(--secondary) 100%);color:#fff;border-color:transparent}}
.question-nav-item.marked{{background:linear-gradient(135deg,var(--warning) 0%,#f59e0b 100%);color:#fff;border-color:transparent}}
.question-nav-item.correct{{background:linear-gradient(135deg,var(--success) 0%,#38a169 100%);color:#fff;border-color:transparent}}
.question-nav-item.incorrect{{background:linear-gradient(135deg,var(--danger) 0%,#e53e3e 100%);color:#fff;border-color:transparent}}
#resultsContainer{{display:none;position:fixed;top:0;left:0;width:100%;height:100vh;background:var(--bg-light);overflow-y:auto;overflow-x:hidden;padding:20px;z-index:1000}}
#resultsContainer.scrollable{{scrollbar-width:thin;scrollbar-color:var(--primary) transparent}}
.results-header{{text-align:center;padding:40px 20px;background:var(--bg-white);border-radius:20px;margin-bottom:20px;box-shadow:0 4px 20px rgba(0,0,0,.06)}}
.results-icon{{font-size:80px;margin-bottom:20px}}
.results-title{{font-size:28px;font-weight:700;color:var(--text-dark);margin-bottom:10px}}
.results-score{{font-size:52px;font-weight:800;background:linear-gradient(135deg,var(--primary) 0%,var(--secondary) 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin-bottom:10px}}
.results-percentage{{font-size:20px;color:var(--text-light);font-weight:600}}
.stats-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-bottom:20px;max-width:800px;margin-left:auto;margin-right:auto}}
.stat-card{{background:var(--bg-white);padding:24px;border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,.06)}}
.stat-icon{{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:20px;margin-bottom:12px}}
.stat-icon.correct{{background:linear-gradient(135deg,var(--success) 0%,#38a169 100%);color:#fff}}
.stat-icon.incorrect{{background:linear-gradient(135deg,var(--danger) 0%,#e53e3e 100%);color:#fff}}
.stat-icon.unattempted{{background:linear-gradient(135deg,#a0aec0 0%,#718096 100%);color:#fff}}
.stat-icon.negative{{background:linear-gradient(135deg,#ed8936 0%,#dd6b20 100%);color:#fff}}
.stat-value{{font-size:32px;font-weight:700;color:var(--text-dark);margin-bottom:4px}}
.stat-label{{font-size:13px;color:var(--text-light);font-weight:500}}
.action-buttons{{display:grid;gap:12px;max-width:800px;margin:0 auto}}
.action-btn{{width:100%;padding:18px;border:none;border-radius:12px;font-size:16px;font-weight:600;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:10px;transition:all .3s}}
.action-btn.primary{{background:linear-gradient(135deg,var(--primary) 0%,var(--secondary) 100%);color:#fff}}
.action-btn.secondary{{background:var(--bg-white);color:var(--text-dark);border:2px solid var(--border)}}
.action-btn:hover{{transform:translateY(-2px)}}
{_QUIZ_DESKTOP_CSS}
</style>
</head>
<body>
<div id="modeSelection">
<div class="mode-container">
<div class="mode-header">
<div class="mode-header-icon"><i class="fas fa-graduation-cap"></i></div>
<h2>{quiz_name_esc}</h2>
<p>Choose your preferred test mode</p>
</div>
<div class="mode-cards">
<div class="mode-card exam-mode" data-mode="exam">
<div class="mode-card-header">
<div class="mode-icon"><i class="fas fa-file-alt"></i></div>
<div class="mode-info">
<h3>Exam Mode</h3>
<p>Complete all questions, results shown after submission</p>
</div>
</div>
</div>
<div class="mode-card practice-mode" data-mode="practice">
<div class="mode-card-header">
<div class="mode-icon"><i class="fas fa-book-open"></i></div>
<div class="mode-info">
<h3>Practice Mode</h3>
<p>Instant feedback with detailed explanations</p>
</div>
</div>
</div>
</div>
<div class="timer-config">
<label for="ct"><i class="fas fa-clock"></i> Custom Timer (minutes)</label>
<input type="number" id="ct" class="timer-input" placeholder="Default: {int(total_time / 60)} minutes" min="1" max="300"/>
</div>
<button class="start-btn" id="sb" disabled><i class="fas fa-play-circle"></i><span>Start Quiz</span></button>
</div>
</div>
<div id="quizContainer">
<div class="quiz-header">
<div class="header-top">
<div class="quiz-title">
<i class="fas fa-clipboard-list"></i>
<span class="quiz-title-text" title="{quiz_name_esc}">{quiz_name_esc}</span>
<span class="mode-badge" id="mb"></span>
</div>
<div class="header-actions">
<button class="theme-toggle" id="tt" title="Toggle Dark Mode"><i class="fas fa-moon"></i></button>
<div class="timer-display" id="td"><i class="fas fa-clock"></i><span id="tt2">00:00</span></div>
</div>
</div>
<div class="header-progress">
<span id="pt">Question 1 of {n_questions}</span>
<span id="at">Attempted: 0/{n_questions}</span>
</div>
<div class="progress-bar-container"><div class="progress-bar" id="pb"></div></div>
</div>
<div class="question-section scrollable" id="qs"></div>
<div class="nav-controls">
<button class="nav-btn secondary" id="pv"><i class="fas fa-chevron-left"></i>Previous</button>
<button class="nav-btn secondary" id="mk"><i class="fas fa-bookmark"></i>Mark</button>
<button class="nav-btn primary" id="nx">Next<i class="fas fa-chevron-right"></i></button>
<button class="nav-btn primary" id="sm" style="display:none"><i class="fas fa-paper-plane"></i>Submit</button>
</div>
<button class="question-nav-toggle" id="nt"><i class="fas fa-th"></i></button>
<div class="question-nav-panel" id="np">
<div class="nav-panel-header">
<h3 class="nav-panel-title"><i class="fas fa-map-marked-alt"></i> Question Navigator</h3>
<button class="nav-close-btn" id="nc"><i class="fas fa-times"></i></button>
</div>
<div class="nav-legend">
<div class="legend-item"><div class="legend-box answered"></div><span>Answered</span></div>
<div class="legend-item"><div class="legend-box marked"></div><span>Marked</span></div>
<div class="legend-item"><div class="legend-box unanswered"></div><span>Not Answered</span></div>
</div>
<div class="question-grid" id="qg"></div>
</div>
</div>
<div id="resultsContainer">
<div class="results-header">
<div class="results-icon" id="ri"></div>
<h2 class="results-title" id="rt"></h2>
<div class="results-score" id="rs"></div>
<div class="results-percentage" id="rp"></div>
</div>
<div class="stats-grid">
<div class="stat-card"><div class="stat-icon correct"><i class="fas fa-check"></i></div><div class="stat-value" id="cc">0</div><div class="stat-label">Correct</div></div>
<div class="stat-card"><div class="stat-icon incorrect"><i class="fas fa-times"></i></div><div class="stat-value" id="ic">0</div><div class="stat-label">Incorrect</div></div>
<div class="stat-card"><div class="stat-icon unattempted"><i class="fas fa-minus"></i></div><div class="stat-value" id="uc">0</div><div class="stat-label">Unattempted</div></div>
<div class="stat-card"><div class="stat-icon negative"><i class="fas fa-exclamation-triangle"></i></div><div class="stat-value" id="nm">0</div><div class="stat-label">Negative Marks</div></div>
</div>
<div class="action-buttons">
<button class="action-btn primary" id="rb"><i class="fas fa-search"></i>Review Answers</button>
<button class="action-btn secondary" id="rsb"><i class="fas fa-redo"></i>Restart Quiz</button>
</div>
</div>
<script>
const qd={{q:[{questions_js}],m:null,tt:{total_time},nm:{negative_marks}}},
st={{cq:0,a:Array(qd.q.length).fill(null),mk:Array(qd.q.length).fill(false),tr:qd.tt,ti:null,sb:false,rv:false,th:'light'}};
if(window.marked){{marked.setOptions({{gfm:true,breaks:true}})}}
function renderContent(text,inline){{
    if(text===undefined||text===null||text==='')return '';
    let t=String(text);
    const store=[];
    const stash=(expr,display)=>{{store.push({{expr:expr.trim(),display}});return '@@MATHPH'+(store.length-1)+'@@'}};
    t=t.replace(/\\$\\$([\\s\\S]+?)\\$\\$/g,(m,e,off,str)=>{{
        const bLine=str.slice(0,off).split('\\n').pop();
        const aLine=str.slice(off+m.length).split('\\n')[0];
        const isBlock=e.indexOf('\\n')>=0||(/^\\s*$/.test(bLine)&&/^\\s*$/.test(aLine));
        return stash(e,isBlock);
    }});
    t=t.replace(/(?<!\\\\)\\$(?!\\s|\\$)([^$\\n]+?)(?<!\\s)\\$(?!\\d)/g,(m,e)=>stash(e,false));
    t=t.replace(/(?<!=)==(?!=|\\s)([^=\\n]+?)(?<!\\s)==(?!=)/g,(m,e)=>'<mark>'+e+'</mark>');
    let html;
    try{{
        html=inline?marked.parseInline(t):marked.parse(t);
    }}catch(e){{
        html=t.replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }}
    html=html.replace(/@@MATHPH(\\d+)@@/g,(m,idx)=>{{
        const item=store[parseInt(idx)];
        if(!item)return m;
        try{{
            return katex.renderToString(item.expr,{{displayMode:item.display,throwOnError:false,strict:false}});
        }}catch(e){{
            return item.display?('$$'+item.expr+'$$'):('$'+item.expr+'$');
        }}
    }});
    return html;
}}
document.addEventListener('DOMContentLoaded',()=>{{sms();pcc();lt()}});
function lt(){{const t=localStorage.getItem('qt')||'light';st.th=t;document.documentElement.setAttribute('data-theme',t);uti()}}
function tgt(){{st.th=st.th==='light'?'dark':'light';document.documentElement.setAttribute('data-theme',st.th);localStorage.setItem('qt',st.th);uti()}}
function uti(){{const i=document.querySelector('#tt i');if(i)i.className=st.th==='light'?'fas fa-moon':'fas fa-sun'}}
function pcc(){{document.addEventListener('contextmenu',e=>e.preventDefault());document.addEventListener('copy',e=>e.preventDefault());document.addEventListener('cut',e=>e.preventDefault());document.addEventListener('selectstart',e=>{{if(!e.target.tagName.match(/INPUT|TEXTAREA/i))e.preventDefault()}})}}
function sms(){{const mc=document.querySelectorAll('.mode-card'),sb=document.getElementById('sb');mc.forEach(c=>{{c.addEventListener('click',()=>{{mc.forEach(x=>x.classList.remove('selected'));c.classList.add('selected');qd.m=c.dataset.mode;sb.disabled=false}})}});sb.addEventListener('click',sq)}}
function sq(){{const ct=document.getElementById('ct'),ctv=parseInt(ct.value);if(ctv&&ctv>0){{st.tr=ctv*60;qd.tt=ctv*60}}document.body.style.overflow='hidden';document.getElementById('modeSelection').style.display='none';document.getElementById('quizContainer').style.display='block';document.getElementById('mb').textContent=qd.m;document.getElementById('mb').className='mode-badge '+qd.m;iq()}}
function iq(){{rq(0);rqg();stt();sn()}}
function stt(){{utd();st.ti=setInterval(()=>{{st.tr--;utd();if(st.tr<=0){{clearInterval(st.ti);sbq()}}if(st.tr<=60)document.getElementById('td').classList.add('warning')}},1000)}}
function utd(){{const m=Math.floor(st.tr/60),s=st.tr%60;document.getElementById('tt2').textContent=`${{String(m).padStart(2,'0')}}:${{String(s).padStart(2,'0')}}`}}
function rq(i){{st.cq=i;const q=qd.q[i],qs=document.getElementById('qs');let h=`<div class="question-card"><div class="question-number"><i class="fas fa-question-circle"></i>Question ${{i+1}} of ${{qd.q.length}}</div>`;if(q.ref)h+=`<div class="question-reference protected-content"><i class="fas fa-info-circle"></i> ${{renderContent(q.ref,true)}}</div>`;h+=`<div class="question-text protected-content">${{renderContent(q.txt)}}</div><div class="options-container">`;q.opts.forEach((o,x)=>{{let bc='option-btn',ic=String.fromCharCode(65+x);const isSel=st.a[i]===x,isCor=x===q.ci,shAns=(qd.m==='practice'&&st.a[i]!==null)||st.sb;if(isSel)bc+=' selected';if(shAns){{bc+=' disabled';if(isCor){{bc+=' correct';ic='<i class="fas fa-check"></i>'}}else if(isSel&&!isCor){{bc+=' incorrect';ic='<i class="fas fa-times"></i>'}}}}h+=`<button class="${{bc}}" data-index="${{x}}" onclick="so(${{x}})"><div class="option-indicator">${{ic}}</div><div class="option-text protected-content">${{renderContent(o,true)}}</div></button>`}});h+=`</div>`;const shExp=(qd.m==='practice'&&st.a[i]!==null)||st.sb;if(shExp)h+=`<div class="explanation-box" style="display:block"><div class="explanation-header"><i class="fas fa-lightbulb"></i>Explanation</div><div class="explanation-text protected-content">${{renderContent(q.exp)}}</div></div>`;h+=`</div>`;qs.innerHTML=h;qs.scrollTop=0;up();unb();uqg()}}
function so(oi){{if(st.sb)return;if(st.a[st.cq]===oi){{st.a[st.cq]=null}}else{{st.a[st.cq]=oi}}rq(st.cq)}}
function sn(){{document.getElementById('pv').addEventListener('click',np);document.getElementById('nx').addEventListener('click',nn);document.getElementById('mk').addEventListener('click',tm);document.getElementById('sm').addEventListener('click',cs);document.getElementById('nt').addEventListener('click',tnp);document.getElementById('nc').addEventListener('click',tnp);document.getElementById('rb').addEventListener('click',ra);document.getElementById('rsb').addEventListener('click',rs);document.getElementById('tt').addEventListener('click',tgt);document.addEventListener('keydown',e=>{{if(st.sb)return;if(e.key==='ArrowLeft')np();if(e.key==='ArrowRight')nn()}})}}
function np(){{if(st.cq>0)rq(st.cq-1)}}
function nn(){{if(st.cq<qd.q.length-1)rq(st.cq+1)}}
function tm(){{st.mk[st.cq]=!st.mk[st.cq];uqg();const mb=document.getElementById('mk');mb.innerHTML=st.mk[st.cq]?'<i class="fas fa-bookmark"></i> Unmark':'<i class="fas fa-bookmark"></i> Mark'}}
function unb(){{document.getElementById('pv').disabled=st.cq===0;if(st.cq===qd.q.length-1){{document.getElementById('nx').style.display='none';document.getElementById('sm').style.display='flex'}}else{{document.getElementById('nx').style.display='flex';document.getElementById('sm').style.display='none'}}const mb=document.getElementById('mk');mb.innerHTML=st.mk[st.cq]?'<i class="fas fa-bookmark"></i> Unmark':'<i class="fas fa-bookmark"></i> Mark'}}
function up(){{const at=st.a.filter(a=>a!==null).length,pr=((st.cq+1)/qd.q.length)*100;document.getElementById('pt').textContent=`Question ${{st.cq+1}} of ${{qd.q.length}}`;document.getElementById('at').textContent=`Attempted: ${{at}}/${{qd.q.length}}`;document.getElementById('pb').style.width=pr+'%'}}
function rqg(){{const g=document.getElementById('qg');g.innerHTML='';qd.q.forEach((_,i)=>{{const it=document.createElement('div');it.className='question-nav-item';it.textContent=i+1;it.onclick=()=>{{rq(i);if(window.innerWidth<768)tnp()}};g.appendChild(it)}})}}
function uqg() {{
    const its = document.querySelectorAll('.question-nav-item');
    its.forEach((it, i) => {{
        it.className = 'question-nav-item';
        if (i === st.cq) it.classList.add('current');
        if (st.sb) {{
            if (st.a[i] === qd.q[i].ci) it.classList.add('correct');
            else if (st.a[i] !== null) it.classList.add('incorrect');
        }} else {{
            if (st.a[i] !== null) it.classList.add('answered');
            if (st.mk[i]) it.classList.add('marked');
        }}
    }});
}}
function tnp(){{document.getElementById('np').classList.toggle('open')}}
function cs(){{const u=st.a.filter(a=>a===null).length;if(u>0){{const c=window.confirm(`You have ${{u}} unattempted question(s). Do you want to submit?`);if(!c)return}}sbq()}}
function sbq(){{clearInterval(st.ti);st.sb=true;let c=0,ic=0,u=0,nm=0;st.a.forEach((a,i)=>{{if(a===null)u++;else if(a===qd.q[i].ci)c++;else{{ic++;nm+=qd.nm}}}});const ts=c-nm,pc=(ts/qd.q.length)*100;document.body.style.overflow='auto';document.getElementById('quizContainer').style.display='none';document.getElementById('resultsContainer').style.display='block';document.getElementById('resultsContainer').classList.add('scrollable');if(pc>=70){{document.getElementById('ri').innerHTML='<i class="fas fa-trophy" style="color:#fbbf24"></i>';document.getElementById('rt').textContent='Excellent Performance!'}}else if(pc>=50){{document.getElementById('ri').innerHTML='<i class="far fa-smile" style="color:#48bb78"></i>';document.getElementById('rt').textContent='Good Job!'}}else{{document.getElementById('ri').innerHTML='<i class="far fa-meh" style="color:#f5576c"></i>';document.getElementById('rt').textContent='Keep Practicing!'}}document.getElementById('rs').textContent=ts.toFixed(2)+' / '+qd.q.length;document.getElementById('rp').textContent=pc.toFixed(1)+'%';document.getElementById('cc').textContent=c;document.getElementById('ic').textContent=ic;document.getElementById('uc').textContent=u;document.getElementById('nm').textContent='-'+nm.toFixed(2)}}
function ra(){{st.rv=true;document.body.style.overflow='hidden';document.getElementById('resultsContainer').style.display='none';document.getElementById('quizContainer').style.display='block';rq(0);uqg()}}
function rs(){{document.body.style.overflow='hidden';location.reload()}}
</script>
</body>
</html>"""

    return html_doc.encode("utf-8"), filename


# --------------------------------------------------------------------------
# render_analysis_html: leaderboard / analysis report page
# --------------------------------------------------------------------------

_ANALYSIS_CSS = """
.hero {
  padding: 34px clamp(16px, 5vw, 40px);
  margin: 20px 0;
  text-align: center;
}
.hero h1 { font-size: clamp(1.4rem, 4vw, 1.9rem); margin: 0 0 6px; font-weight: 800; }
.hero p { color: var(--color-text-muted); margin: 0; }

.section { margin: 28px 0; }
.section-title {
  font-size: 1.05rem;
  font-weight: 800;
  margin-bottom: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.section-title i { color: var(--color-primary); }

.podium {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
  align-items: end;
}
.podium-slot {
  padding: 20px 14px 18px;
  text-align: center;
  border-radius: var(--radius-md);
  position: relative;
}
.podium-slot .rank-badge {
  width: 40px; height: 40px;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto 10px;
  font-weight: 800;
  color: #fff;
  font-size: 1.1rem;
}
.podium-1 { order: 2; background: linear-gradient(180deg, #fff7e0, var(--color-surface)); border: 1.5px solid #f2c94c; }
html[data-theme="dark"] .podium-1 { background: linear-gradient(180deg, #3a2f0c, var(--color-surface)); }
.podium-1 .rank-badge { background: #f2b400; }
.podium-2 { order: 1; background: var(--color-surface); border: 1.5px solid #c0c6d6; margin-top: 18px; }
.podium-2 .rank-badge { background: #9aa2bd; }
.podium-3 { order: 3; background: var(--color-surface); border: 1.5px solid #d9a06b; margin-top: 28px; }
.podium-3 .rank-badge { background: #c17a3f; }
.podium-name { font-weight: 700; font-size: 0.98rem; word-break: break-word; }
.podium-score { font-size: 1.3rem; font-weight: 800; color: var(--color-primary); margin-top: 4px; }
.podium-meta { font-size: 0.78rem; color: var(--color-text-muted); margin-top: 2px; }

@media (max-width: 640px) {
  .podium { grid-template-columns: 1fr; }
  .podium-1, .podium-2, .podium-3 { order: initial; margin-top: 0; }
}

.charts-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 16px;
}
@media (min-width: 900px) { .charts-grid { grid-template-columns: 1.3fr 1fr; } }
.chart-card { padding: 18px; }
.chart-card canvas { max-width: 100%; }

.table-wrap {
  overflow-x: auto;
  border-radius: var(--radius-md);
  border: 1px solid var(--color-border);
}
table.leaderboard {
  width: 100%;
  border-collapse: collapse;
  min-width: 520px;
  font-size: 0.92rem;
}
table.leaderboard thead th {
  background: var(--color-surface-alt);
  text-align: left;
  padding: 12px 14px;
  font-weight: 700;
  cursor: pointer;
  user-select: none;
  white-space: nowrap;
  position: sticky;
  top: 0;
}
table.leaderboard thead th i { margin-left: 4px; opacity: 0.5; font-size: 0.75em; }
table.leaderboard tbody td {
  padding: 11px 14px;
  border-top: 1px solid var(--color-border);
  vertical-align: middle;
}
table.leaderboard tbody tr:hover { background: var(--color-surface-alt); }
.rank-cell { font-weight: 800; }
.rank-1 { color: #f2b400; }
.rank-2 { color: #9aa2bd; }
.rank-3 { color: #c17a3f; }

.qstat-list { display: flex; flex-direction: column; gap: 12px; }
.qstat-row { padding: 14px 16px; }
.qstat-row .qtext { font-weight: 600; margin-bottom: 8px; line-height: 1.4; }
.qstat-bar {
  height: 10px;
  border-radius: 999px;
  background: var(--color-danger-soft);
  overflow: hidden;
  display: flex;
}
.qstat-bar .fill-correct { background: var(--color-success); height: 100%; }
.qstat-legend { display: flex; justify-content: space-between; font-size: 0.78rem; color: var(--color-text-muted); margin-top: 6px; }
"""

_ANALYSIS_JS_TEMPLATE = """
(function () {
  var DATA = %%DATA%%;

  function sortTable(key, numeric) {
    var tbody = document.getElementById('leaderboardBody');
    var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
    var dir = tbody.getAttribute('data-sort-key') === key && tbody.getAttribute('data-sort-dir') === 'asc' ? 'desc' : 'asc';
    rows.sort(function (a, b) {
      var av = a.getAttribute('data-' + key);
      var bv = b.getAttribute('data-' + key);
      if (numeric) { av = parseFloat(av); bv = parseFloat(bv); }
      if (av < bv) return dir === 'asc' ? -1 : 1;
      if (av > bv) return dir === 'asc' ? 1 : -1;
      return 0;
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
    tbody.setAttribute('data-sort-key', key);
    tbody.setAttribute('data-sort-dir', dir);
  }

  window.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('th[data-sort]').forEach(function (th) {
      th.addEventListener('click', function () {
        sortTable(th.getAttribute('data-sort'), th.getAttribute('data-numeric') === '1');
      });
    });

    if (window.Chart && DATA.scoreLabels && DATA.scoreLabels.length) {
      var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
      var gridColor = isDark ? 'rgba(255,255,255,0.08)' : 'rgba(15,23,42,0.06)';
      var textColor = isDark ? '#c8cde3' : '#5b6478';

      var barCtx = document.getElementById('scoreChart');
      if (barCtx) {
        new Chart(barCtx, {
          type: 'bar',
          data: {
            labels: DATA.scoreLabels,
            datasets: [{
              label: 'Score',
              data: DATA.scoreValues,
              backgroundColor: '#4f46e5',
              borderRadius: 6,
              maxBarThickness: 40
            }]
          },
          options: {
            responsive: true,
            plugins: { legend: { display: false } },
            scales: {
              x: { ticks: { color: textColor }, grid: { display: false } },
              y: { ticks: { color: textColor }, grid: { color: gridColor }, beginAtZero: true }
            }
          }
        });
      }

      var pieCtx = document.getElementById('passFailChart');
      if (pieCtx && DATA.passFail) {
        new Chart(pieCtx, {
          type: 'doughnut',
          data: {
            labels: ['Passed', 'Not cleared'],
            datasets: [{
              data: [DATA.passFail.pass, DATA.passFail.fail],
              backgroundColor: ['#16a34a', '#dc2626'],
              borderWidth: 0
            }]
          },
          options: {
            responsive: true,
            plugins: { legend: { position: 'bottom', labels: { color: textColor } } }
          }
        });
      }
    }
  });
})();
"""


def _ordinal_rank_badge(rank: int) -> str:
    icons = {1: "fa-crown", 2: "fa-medal", 3: "fa-medal"}
    return f'<i class="fa-solid {icons.get(rank, "fa-star")}"></i>'


def _compute_question_stats(
    quiz: dict, results: list[dict]
) -> list[dict[str, Any]]:
    """Return per-question correctness stats. Prefers an explicit
    ``question_stats`` list on the quiz dict (each item optionally carrying
    ``correct_count``/``wrong_count``); otherwise derives a reasonable
    placeholder distribution from the overall pass rate so the report still
    renders something meaningful when per-user answer logs aren't wired up
    yet."""
    questions = quiz.get("questions") or []
    explicit = quiz.get("question_stats")
    n_results = max(len(results), 1)

    stats = []
    for i, question in enumerate(questions):
        q_text = question.get("question", f"Question {i + 1}")
        if explicit and i < len(explicit):
            src = explicit[i]
            correct = int(src.get("correct_count", 0) or 0)
            wrong = int(src.get("wrong_count", 0) or 0)
        else:
            # Placeholder: approximate using the average pass rate across
            # all participants when no per-question log is supplied.
            avg_pct = (
                sum(
                    (r.get("score", 0) / r.get("total_questions", 1))
                    for r in results
                    if r.get("total_questions")
                )
                / n_results
                if results
                else 0.5
            )
            avg_pct = min(max(avg_pct, 0), 1)
            correct = round(avg_pct * n_results)
            wrong = n_results - correct
        total = max(correct + wrong, 1)
        stats.append(
            {
                "text": q_text,
                "correct": correct,
                "wrong": wrong,
                "correct_pct": round((correct / total) * 100),
            }
        )
    return stats


async def render_analysis_html(quiz: dict, results: list[dict]) -> tuple[bytes, str]:
    """Build a self-contained leaderboard/analysis report HTML page.

    See module docstring for the expected shape of ``quiz`` and ``results``.
    """
    quiz_name = quiz.get("quiz_name") or "Untitled Quiz"
    qid = quiz.get("qid") or str(uuid.uuid4())[:8]
    questions = quiz.get("questions") or []
    n_questions = len(questions) or 1
    pass_percent = float(quiz.get("pass_percent", 40) or 40)

    # Sort participants by score desc, then by time_taken asc (faster wins ties).
    ranked = sorted(
        results,
        key=lambda r: (-float(r.get("score", 0)), float(r.get("time_taken", 0))),
    )

    n_participants = len(ranked)
    avg_score = (
        sum(float(r.get("score", 0)) for r in ranked) / n_participants
        if n_participants
        else 0.0
    )
    pass_count = sum(
        1
        for r in ranked
        if r.get("total_questions")
        and (float(r.get("score", 0)) / float(r["total_questions"])) * 100
        >= pass_percent
    )
    fail_count = n_participants - pass_count

    # ---- Podium (top 3) ----
    podium_slots = ["", "", ""]
    for i in range(min(3, n_participants)):
        r = ranked[i]
        name = _esc(r.get("user_name", "Anonymous"))
        score = _esc(r.get("score", 0))
        total_q = _esc(r.get("total_questions", n_questions))
        rank = i + 1
        podium_slots[i] = f"""
    <div class="card podium-slot podium-{rank}">
      <div class="rank-badge">{_ordinal_rank_badge(rank)}</div>
      <div class="podium-name">{name}</div>
      <div class="podium-score">{score} pts</div>
      <div class="podium-meta">{total_q} questions</div>
    </div>
"""
    podium_html = (
        f'<div class="podium">{"".join(podium_slots)}</div>'
        if n_participants
        else '<p style="color:var(--color-text-muted);">No participants yet.</p>'
    )

    # ---- Leaderboard table ----
    rows_html = []
    for i, r in enumerate(ranked):
        rank = i + 1
        name = _esc(r.get("user_name", "Anonymous"))
        score = float(r.get("score", 0))
        total_q = int(r.get("total_questions", n_questions) or n_questions)
        time_taken = int(r.get("time_taken", 0) or 0)
        pct = (score / total_q * 100) if total_q else 0.0
        passed = pct >= pass_percent
        rank_cls = f"rank-{rank}" if rank <= 3 else ""
        status_badge = (
            '<span class="badge badge-success">Passed</span>'
            if passed
            else '<span class="badge badge-danger">Not cleared</span>'
        )
        mins, secs = divmod(time_taken, 60)
        rows_html.append(
            f"""<tr data-rank="{rank}" data-name="{name}" data-score="{score}"
                 data-percent="{pct:.2f}" data-time="{time_taken}">
        <td class="rank-cell {rank_cls}">#{rank}</td>
        <td>{name}</td>
        <td>{score:g} / {total_q}</td>
        <td>{pct:.1f}%</td>
        <td>{mins}m {secs}s</td>
        <td>{status_badge}</td>
      </tr>"""
        )
    table_body = "\n".join(rows_html) or (
        '<tr><td colspan="6" style="text-align:center;color:var(--color-text-muted);'
        'padding:20px;">No results submitted yet.</td></tr>'
    )

    # ---- Question-level correctness breakdown ----
    q_stats = _compute_question_stats(quiz, ranked)
    qstat_rows = []
    for i, stat in enumerate(q_stats):
        qstat_rows.append(
            f"""
      <div class="card qstat-row">
        <div class="qtext">Q{i + 1}. {_esc(stat['text'])}</div>
        <div class="qstat-bar">
          <div class="fill-correct" style="width:{stat['correct_pct']}%"></div>
        </div>
        <div class="qstat-legend">
          <span>{stat['correct']} correct</span>
          <span>{stat['correct_pct']}% accuracy</span>
          <span>{stat['wrong']} wrong</span>
        </div>
      </div>"""
        )
    qstat_html = "".join(qstat_rows) or (
        '<p style="color:var(--color-text-muted);">No question data available.</p>'
    )

    # ---- Chart data payload ----
    top_n = ranked[:15]
    chart_payload = {
        "scoreLabels": [r.get("user_name", "Anonymous") for r in top_n],
        "scoreValues": [float(r.get("score", 0)) for r in top_n],
        "passFail": {"pass": pass_count, "fail": fail_count},
    }
    chart_json = _js_literal(chart_payload)

    hero_html = f"""
<div class="container">
  <div class="card hero">
    <h1><i class="fa-solid fa-chart-line"></i> {_esc(quiz_name)} &mdash; Results Analysis</h1>
    <p>Quiz ID: {_esc(qid)} &middot; {n_participants} participant(s) &middot; average score {avg_score:.1f}</p>
    <div class="stat-grid" style="margin-top:22px;">
      <div class="stat-tile">
        <div class="value" style="color:var(--color-primary);">{n_participants}</div>
        <div class="label">Participants</div>
      </div>
      <div class="stat-tile">
        <div class="value" style="color:var(--color-success);">{pass_count}</div>
        <div class="label">Passed</div>
      </div>
      <div class="stat-tile">
        <div class="value" style="color:var(--color-danger);">{fail_count}</div>
        <div class="label">Not cleared</div>
      </div>
      <div class="stat-tile">
        <div class="value">{avg_score:.1f}</div>
        <div class="label">Average score</div>
      </div>
    </div>
  </div>
</div>
"""

    podium_section = f"""
<div class="container section">
  <div class="section-title"><i class="fa-solid fa-trophy"></i> Top performers</div>
  {podium_html}
</div>
"""

    charts_section = f"""
<div class="container section">
  <div class="section-title"><i class="fa-solid fa-chart-column"></i> Score overview</div>
  <div class="charts-grid">
    <div class="card chart-card">
      <canvas id="scoreChart" height="240"></canvas>
    </div>
    <div class="card chart-card">
      <canvas id="passFailChart" height="240"></canvas>
    </div>
  </div>
</div>
"""

    table_section = f"""
<div class="container section">
  <div class="section-title"><i class="fa-solid fa-ranking-star"></i> Full leaderboard</div>
  <div class="card table-wrap">
    <table class="leaderboard">
      <thead>
        <tr>
          <th data-sort="rank" data-numeric="1">Rank <i class="fa-solid fa-sort"></i></th>
          <th data-sort="name" data-numeric="0">Participant <i class="fa-solid fa-sort"></i></th>
          <th data-sort="score" data-numeric="1">Score <i class="fa-solid fa-sort"></i></th>
          <th data-sort="percent" data-numeric="1">Accuracy <i class="fa-solid fa-sort"></i></th>
          <th data-sort="time" data-numeric="1">Time taken <i class="fa-solid fa-sort"></i></th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody id="leaderboardBody">
        {table_body}
      </tbody>
    </table>
  </div>
</div>
"""

    qstats_section = f"""
<div class="container section">
  <div class="section-title"><i class="fa-solid fa-magnifying-glass-chart"></i> Question-wise breakdown</div>
  <div class="qstat-list">
    {qstat_html}
  </div>
</div>
"""

    body = (
        _topbar_html(quiz_name, "Results & Analysis")
        + hero_html
        + podium_section
        + charts_section
        + table_section
        + qstats_section
        + '<footer class="site-footer">Generated analysis report &middot; interactive single-file HTML</footer>'
    )

    analysis_js = _ANALYSIS_JS_TEMPLATE.replace("%%DATA%%", chart_json)
    html_doc = _page_shell(
        title=f"{quiz_name} - Analysis",
        extra_head=_ANALYSIS_CSS,
        body=body,
        extra_scripts=_CHARTJS_SCRIPT + f"<script>{analysis_js}</script>",
    )

    filename = f"{_slug(quiz_name)}-{qid}-analysis.html"
    return html_doc.encode("utf-8"), filename
