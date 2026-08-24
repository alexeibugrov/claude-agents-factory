# Designing an agent's tool surface

The tools are the agent. The prompt shapes intent; the tools decide what is possible. Most agent
failures that look like "the model got confused" are really a tool surface that made the wrong
action easy and the right one hard.

## Give the model the operation it actually needs

Prefer one tool that performs the intended operation over three primitives the model must compose
correctly. Composition is where reasoning errors turn into wrong actions: every intermediate step is
a chance to pass the wrong value, and the model has no way to verify the intermediate state.

If an operation is only ever done as a unit, expose it as a unit.

## Make results self-describing

Return a dict with a `success` boolean and, on failure, a human-readable `error`. The model reads
tool results and adapts; a bare `null`, an empty list, or an exception string with no structure
gives it nothing to act on, and it will usually either retry identically or invent a result.

Include the identifiers a follow-up call would need — an id, a resulting state — so the next tool
call does not require a second lookup.

## Never raise

A raising handler kills the Claude session and loses the run. Catch everything and degrade to
`{"success": False, "error": ...}`. This is enforced by the wrapper in
[agents/_template/agent/tools.py](../../agents/_template/agent/tools.py); keep it when you edit.

## Bind per run, never globally

Handlers take the run's context explicitly. Module-level clients are safe only while runs are
strictly serial, and the loop is async — the first concurrent run silently crosses state. This was a
real migration hazard in `bb-trade-agent`, where the original serial agent's module globals had to
become an explicit per-run `ToolContext` before the async agent could exist.

## Separate reads from writes, in the schema and in the guard

Reads should always be permitted; writes are what the guard gates. Keep the two sets obviously
distinct in naming, and keep `WRITE_TOOLS` in `guards.py` exhaustive. A write tool missing from that
set is not a lint error — it is an agent that can change something while it is supposedly gated.

## Filter noise out of the reported summary

Pure state reads are how the model orients itself and are usually not interesting to the operator.
Reporting every read buries the one write that mattered. Log everything; *summarise* selectively.

## Schemas: describe, constrain, and mention the quirks

Use `enum` for closed sets and `required` honestly. Put the awkward parts of the underlying API in
the `description` — the parameter that is named differently on update than on create, the unit that
is not what you would guess. The model reads descriptions, and a sentence there is cheaper than a
retry loop.
