# Fixing behaviour: prompts and evals, not guardrails

When an agent does the wrong thing, there are two ways to respond. One is to add code that prevents
that specific wrong thing. The other is to change the prompt, the model, or the tools — and add a
test that proves the new behaviour.

**Default to the second.** The first is seductive because it is fast and provably stops the exact
case in front of you. It is also how an agent stops being an agent: each guardrail removes a
decision from the model, and after enough of them you have a brittle rule engine wearing an LLM as a
hat, with worse behaviour on every case nobody hardcoded.

## The narrow exception

A short list of **safety vetoes** is legitimate. What makes a veto sanctioned rather than a
workaround:

- It is **config-gated**, so turning it off is a reviewed config change, not a code edit.
- It is **categorical**, not case-specific: "no state changes at all while disarmed", never "not this
  symbol" or "not on Tuesdays".
- It is **documented** where a reviewer will find it, and it **logs when it fires** — a veto that
  silently swallows an action is indistinguishable from a bug.

The write gate ([architecture/agent-anatomy.md](../architecture/agent-anatomy.md)) is the canonical
example. A hardcoded `if value > 100: return` buried in a tool handler is not.

The second exception is **infrastructure reliability**, which is not agent behaviour at all. Moving
logs to journald so they survive a redeploy is not a guardrail; it touches no prompt, model, or tool.

## Prompts belong in git

Each role's prompt is a committed version file, `prompts/<role>/v<N>.md`, and `agent_config.yaml`
names the live one ([conventions/agents.md](../conventions/agents.md)). A prompt change is then a new
file plus a pointer change: a reviewable diff that ships through the normal PR path, and a rollback
is the pointer.

The failure this avoids is specific and was real: in `bb-trade-agent`, the live prompt for the
original agent lived in a gitignored config file, so the `prompts/` directory in the repo was
decorative — people edited it and nothing changed at runtime. If a prompt exists in more than one
place, say plainly which one is live.

## Evals

An eval suite is what lets you change a prompt without guessing. The shape that worked:

- **A mock backend** implementing the same interface as the real one, so the whole loop runs —
  including the real tool handlers and the real guards — with no external side effects.
- **Scenarios as data** (YAML), each with an input and the expected end state. Data scales; a test
  function per case does not.
- **Grade the end state, not the transcript.** Asserting on which tools were called in which order
  locks in one particular way of being right and breaks on every harmless variation.
- **Run the real loop.** An eval harness that reimplements the loop grades a copy of the agent, and
  the copy is the one that stays correct.

Cost is the honest constraint: every eval run is real model calls against the owner's subscription.
Keep the suite small enough to run on a prompt change, and treat a model bake-off as an occasional
exercise rather than a per-commit gate.

## Human-reviewed prompt evals

Some outputs have no checkable end state: a proposal is good when the operator would send it. Then
the operator is the grader, and the loop is built around their review. The shape that worked
([upwork-scout](../../agents/upwork-scout/README.md), on Promptfoo — see the
[promptfoo skill](../../.claude/skills/promptfoo/SKILL.md)):

- **A thin provider runs the real loop** with only the system prompt swapped for the version under
  test. A fresh session per case, writes off.
- **One prompt version per batch**, and every run records the prompt sha, the dataset sha, the model
  settings and the commit, so a verdict is always tied to what produced it.
- **Unreviewed never looks approved.** Each output carries a pending-review marker until the operator
  rates it, and the export reads only the operator's verdict.
- **A separate editor model proposes, the operator decides.** The editor gets the prompt, the exact
  inputs, the outputs and every verdict and comment (approvals too, so good behaviour survives), and
  returns one candidate with each change tied to the cases behind it, plus conflicts and problems a
  prompt cannot fix. Nothing scores or adopts automatically.
- **Tuning and validation stay disjoint**, and the editor refuses validation feedback.
- **Make the eval fail the way production fails**, including retries. An eval that is stricter or
  looser than production grades a different agent.
