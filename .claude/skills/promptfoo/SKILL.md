---
name: promptfoo
description: Use when setting up, running or debugging Promptfoo evals — a promptfooconfig, a custom Python provider, the web viewer with human 👍/👎 review, `promptfoo eval` / `view` / `export`, eval caching, or a prompt-iteration loop built on them. Encodes the version, caching, templating and manual-rating behaviours that are not obvious from the docs.
---

# promptfoo

Promptfoo runs prompt × test-case matrices, stores evals and ratings in a local SQLite database, and
serves a viewer for reading and rating outputs. These rules are what it took to make it run a real
agent faithfully and keep human verdicts trustworthy.

## Files covered

- `**/promptfooconfig*.yaml`
- `**/evals/**` where a `package.json` pins `promptfoo`

## Linters

None. Promptfoo has no linter here; validate a generated config with `promptfoo validate config -c <file>`.

## Runtime

1. **Pin it** in a `package.json` with a committed lockfile and call `node_modules/.bin/promptfoo`,
   never `npx promptfoo@latest`. Releases from 0.122 require Node ≥ 22.22: check
   `npm view promptfoo@<v> engines.node` before pinning, and bump the runtime rather than pinning an
   old release.
2. **Docs:** if promptfoo.dev is unreachable, read `site/docs/` from the GitHub repository at the
   pinned tag; `src/` at the same tag settles behaviour questions the docs leave open.
3. **Environment for every call:** `PROMPTFOO_CONFIG_DIR` inside the project checkout (the database
   holds evals *and* human ratings; a home directory is lost on a container rebuild),
   `PROMPTFOO_DISABLE_TELEMETRY=1`, `PROMPTFOO_DISABLE_UPDATE=1`, `PROMPTFOO_DISABLE_SHARING=1`.
4. **`eval` exits 100** when any test fails. That is a result, not an error; treat only other non-zero
   codes as failures.

## Python providers

1. **Cache key** = provider file hash + rendered prompt + provider config + test vars. Modules the
   provider imports and files they read are **not** in it, so a cached rerun after an agent code or
   config change silently replays old outputs. For agent evals default to `--no-cache` and make
   cache reuse an explicit opt-in. Errors are never cached.
2. **Interpreter:** set `PROMPTFOO_PYTHON` (or `config.pythonExecutable`) to the project's venv
   Python so the provider can import the application. `async def call_api(prompt, options, context)`
   is supported; `context["vars"]`, `context["test"]["metadata"]` and `options["config"]` carry the
   case and settings.
3. **Return** `{"output": ..., "metadata": {...}}`, or `{"output": "", "error": ...}` for a failed
   run so it shows as ERROR and is never mistaken for a reviewable output. `metadata` lands in the
   result and in exports.

## Prompts

1. **A system prompt must arrive verbatim.** Prompt text is Nunjucks-rendered and a `.txt`/`.md`
   prompt file is split into several prompts on lines of `---`. For a verbatim prompt set
   `PROMPTFOO_DISABLE_TEMPLATING=true`, reject `{{`, `{%`, `{#` and `---` lines before running, and
   have the provider verify a hash of what it received.
2. **Pass the prompt inline** (`prompts: [{raw: <text>, label: <name>@<sha>}]`). A `file://` prompt's
   label gets its path and content appended; inline also makes the generated config a full record.

## Human review in the viewer

1. **A verdict is a `gradingResult.componentResults` entry with `assertion.type == "human"`**, created
   only by 👍/👎. A comment (`gradingResult.comment`) or a 🔢 score alone creates no such entry.
   Read verdicts from that component, never from `success`/`pass`.
2. **No assertions means every output shows PASS.** When humans grade, add a deterministic
   pending-review assertion (`type: javascript`, always `{pass: false}`); a 👍/👎 overrides it, so
   *Passes* shows human approvals only. The viewer then counts a 👎 as two failed checks: one output.
3. **Compare mode does not save ratings.** Rate in the single-eval view; tell reviewers which eval id
   to open — the viewer stays on whichever eval it last showed.
4. **`promptfoo export eval <id>` reads the database**, so it returns the latest saved ratings and
   comments. Put run provenance in the config's `metadata`; it comes back in every export.
5. **The viewer holds port 15500.** Stop any instance you started before handing back to the operator.
