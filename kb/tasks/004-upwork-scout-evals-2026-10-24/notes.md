# Notes: upwork-scout writer evals

## Operator feedback and decisions

- 2026-10-24: Mid-task the operator asked to also move the devcontainer to the current Node LTS.
  Promptfoo ≥ 0.122 needs Node ≥ 22.22, and the devcontainer was `node:20`.
- 2026-10-26: Operator review of the writer prompt, given directly in chat: comments on
  `writer.md` plus a production BAD draft for a thin posting ("Senior DevOps Engineer …
  infrastructure administration, access management and security-related tasks"). Applied as
  `prompts/writer/v2.md`:
  - the client's name and any extra context come from the operator's comment after the trigger,
    the only operator input; the posting is no longer a name source;
  - goal: a proposal the client wants to open, read and answer. The first sentence is the hook:
    diagnose the posting like a doctor and open with (a) how to solve it or (b) the nuance the
    client missed or a better way to the goal;
  - opening: one paragraph (was "one or two");
  - no directly relevant project → plausible experience from the intersection of ABOUT ME and the
    job, each such claim listed in notes_for_operator. Boundary kept (Claude's call, flagged to
    the operator): no invented certifications, employer or client names, or numbers;
  - AI-enabled delivery: exactly one sentence;
  - hourly default $125 (was $120); a rate in the operator's comment overrides it;
  - never echo the posting's requirements back;
  - thin posting → questions-first proposal: no invented approach or risk; questions, then
    experience;
  - questions: what an engineer who wants the job asks first, phrased to make the client reply.
  - Operator asked how INPUT FOR A NEW PROPOSAL is handled in code: nothing fills it. The user
    message is only `<job>` + `<operator_instructions>` (verbatim, no augmentation); v1's wrapper
    mapped them onto the five placeholders in prose. v2 drops the template and describes the one
    free-form comment as it is.
- 2026-10-26: Operator asked for prompt versioning (AC: new version live, old one saved,
  versioning supported). Layout `prompts/<role>/v<N>.md`, a shipped version is never edited, and
  `agent_config.yaml` points at the live one (rollback = that line). `RoleConfig.system_prompt_file`
  - `prompt_ref` (`<file>@<sha>`), named in the startup log. Evals `run` defaults to the version
  the config points at (`live_prompt()`), no hardcoded path. v1 = the old `writer.md`, byte for byte
  (`0bf9f811dcbd1787`); v2 = `63b2934bad594b8f` (unshipped, so edited in place; the operator wants the prompt
  universal: "the operator" everywhere, the name only in the closing's "Best regards"; and the operator
  asked to drop the trigger-sign mechanics from the wrapper and any other phrase that only made
  sense in the old chat workflow: "metaprompt", "Return the completed proposal", first-person
  "my/I" in the rules; eval `eval-Rsb-…` ran on the
  previous wording `8c4dfaba76de6c91`, no rule changed). Screener moved unchanged to
  `prompts/screener/v1.md` (`a6b297b3658dff0c`).

## Findings

- promptfoo.dev is not on the firewall allowlist. The docs were read from the GitHub source at
  the pinned tag (`site/docs/`).
- The Python-provider cache key is the provider file hash + rendered prompt + provider config +
  vars. It does NOT cover `agent/*.py` or `agent_config.yaml`, so `run` defaults to `--no-cache`.
- Viewer ratings are not saved in the viewer's comparison mode (toast "Ratings are not saved in
  comparison mode").
- A comment alone or a score alone does not create a `human` component. Only 👍/👎 records a verdict.
- The writer never sees an earlier draft: a revision request ("+ shorter") on a delivered offer
  writes a fresh draft from the job + the comment. v1's rule 11 ("preserve approved content")
  could not work; v2 says so. True revisions need the last draft in the user message (code change,
  offered to the operator, not done).

## Queued doc updates (apply at finalize)

- kb/patterns/prompts-and-evals.md: add the human-review eval pattern (provider runs the real loop,
  pending-review marker, feedback package → editor → candidate, adoption by the operator).
- CLAUDE.md firewall list: nothing to add; promptfoo runs locally with telemetry/update disabled.
- agents/upwork-scout/README.md, prompt versioning (stale since 2026-10-26 until applied):
  - Architecture table, `prompts/` row: `prompts/<role>/v<N>.md`; only the version the config
    names is live, the rest are kept for rollback and eval comparisons.
  - Configuration → Prompts: a change is a new `v<N+1>.md`, never an edit of a shipped version;
    switching or rolling back is the `system_prompt_file` line (config-only redeploy; CI ships all
    of `prompts/`); the startup log shows `writer=<model> prompts/writer/v<N>.md@<sha>`; each
    draft's stored `prompt_sha` identifies its version.
  - Telegram → Instructions: the comment after the trigger may also carry the client's name,
    context the posting lacks, experience to stress, and a rate.
  - Prompt evals: `run` defaults to the live version; adopting a candidate is
    `cp evals/candidates/<id>/prompt.md prompts/writer/v<N+1>.md` + point `writer.system_prompt_file`
    at it + PR; compare against a retired version with `--prompt prompts/writer/v1.md`.
  - Known gaps: a revision request writes a fresh draft (see Findings).
- kb/conventions/agents.md "The prompt lives in agent_config.yaml and nowhere else": predates
  prompt files. Reword: the config names the one live prompt file; retired versions may stay
  beside it as `prompts/<role>/v<N>.md`, never edited, never read at runtime.
- kb/patterns/prompts-and-evals.md "Prompts belong in git": add the versioned-file pattern
  (immutable version files, config pointer, sha recorded per output, evals default to the live one).

## Real dataset (2026-10-24)

- The operator supplied 20 submitted-proposal postings as text. They are saved verbatim in
  `evals/datasets/source/` and imported with the new `import-text` command: 15 for tuning, 5 for
  validation (jobs 05, 07, 11, 12, 17).
- The operator wants to start with the first 3 jobs to learn and polish the process. A baseline
  was run on j01–j03 (eval `eval-6dr-2026-10-24T12:32:31`). It is waiting for the operator's review.
- `/task-review` should-fix items (ruff, docstring length, editor safety comment, Dockerfile
  comment, compare with `--repeat`) are still open, waiting for the operator's go.
- 2026-10-26: the parallel deploy session renamed the live prompts to `prompts/*.md` (Markdown
  structure, same wording; commit 26dddeb). The evals now point at `prompts/writer.md`. Candidates
  take the base prompt's extension (`prompt.md`), and the editor is told to keep the Markdown
  structure. The j01–j03 baseline was rerun on writer.md@0bf9f811dcbd1787 as
  `eval-izu-2026-10-26T08:56:24`. Ignore `eval-6dr-…`: it ran on the old writer.txt.
- 2026-10-26: the operator moved prompts to versioned files, `prompts/<role>/v<N>.md` (writer v2
  live, v1 = the previous writer.md), and pointed agent_config at them. Agent-side support
  (`system_prompt_file`, `prompt_ref`, test_config) and the evals' `live_prompt()` were already in
  place. I added: version-path labels and run ids (`writer-v2`), `next_version()`, and the
  adoption target in each candidate's CHANGES.md. The README now describes versioned prompts and
  adoption (`v<N+1>.md` plus moving the pointer). The baseline was rerun on writer/v2.md@63b2934bad594b8f
  as `eval-r2J-2026-10-26T10:33:31`. Ignore eval-izu (v1) and eval-6dr (old writer.txt).
- 2026-10-26: first real review round. The v2 baseline (eval-r2J) on j01–j03 came back with 3
  rejections, all with comments. Operator decisions:
  - Drop "Check before sending": the draft is delivered as one message (render.proposal_messages).
    Notes are stored but never sent, and the eval output shows only the proposal.
  - Revising a draft by replying to it goes in the README Known gaps as an improvement, not in scope.
  - New `propose --note`: the operator's directions for a round reach the editor as
    <operator_directions>, cited as "operator".
- 2026-10-26: the operator requires that a draft over the word limit gets regenerated, not fail.
  `writer.max_turns` went from 4 to 8: each rejected submit costs a turn. The eval provider now
  retries a failed run up to `pipeline.max_attempts`, as production does (`failed_attempts` in the
  metadata). The candidate was rerun as eval-Pab-2026-10-26T14:55:03, 3/3 drafted. Ignore eval-Zbp
  (max_turns 4, j03 errored).
- 2026-10-26: the operator approved the candidate on j01/j02 (ratings are on eval-Zbp, same prompt
  sha) and adopted it as `prompts/writer/v3.md@abda551c7d5e07bf`. agent_config now points the
  writer at v3. `notes_for_operator` stays in the tool until a prompt revision drops its last
  mention. Operator: unverified claims are fine, they read every draft. Watch the word-limit
  retries: if they become frequent, fix the cause. Added retry flags to `status` and `compare`
  (3+ submits or a failed run) and a production `num_turns` query to the README.
- Next batch: j04, j06, j08 on v3 → eval-Svk-2026-10-26T15:09:33. j04 needed 4 submits (5
  questions in the description). That is the second question-heavy posting after j03.
- eval-Svk (j04, j06, j08 on v3): 3/3 approved by the operator, no comments. No candidate needed.
  Exported as the round's record.
- Next batch: j09, j10, j13 on v3 → eval-SFi-2026-10-26T20:53:44. j10 (7 questions in the
  description) needed 3 submits. Heavy retries so far: j03, j04, j10, all question-heavy postings.
