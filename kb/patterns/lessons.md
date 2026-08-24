# Lessons from the first generation

Extracted from [`bb-trade-agent`](https://github.com/arbproject-org/bb-trade-agent), which ran three
agents in production. Each lesson has an incident behind it. They are recorded here because they are
not visible in any single file — they are the reasons this factory's template looks the way it does.

## Runtime

**Container logs die with the container.** The default `json-file` driver writes into the
container's writable layer, which `docker rm` destroys — and every redeploy does a recreate. Three
audit runs were blinded before anyone noticed the decision traces were gone. Fix: journald with a
stable per-agent tag. The trace is the primary debugging artefact of an LLM agent; treat losing it as
data loss, not an inconvenience.

**Silence is not success.** A signal burned every retry on "Claude Code returned an error result"
and nobody was alerted — on a real input that is a silent drop. Any non-success outcome now logs a
greppable marker so journald alerting has something to watch.

**Retry only what placed no write.** An attempt that already called a mutating tool must never be
retried: re-running it duplicates the action. Retry the transient failures that changed nothing;
surface the rest as errors for a human.

**One shared resource means one deploy at a time.** Two agents deploying concurrently shared root's
`~/.docker/config.json` on the VM, where one run's `docker logout` broke the other's in-flight
`pull`. Per-workflow concurrency does not help — the group has to be constant across callers.

**A green deploy is not a running agent.** Nothing checked that the container survived `up -d`. A
crash-looping stack reported success. The pipeline now waits and checks.

**Rollback needs an immutable tag.** With only a mutable `latest`, the deploy's own
`docker image prune -f` deleted the previous revision as soon as it was superseded. The documented
"just redeploy the old tag" procedure turned out to reference a tag that no longer existed. `type=sha`
on every build is the fix.

## Agent design

**Module globals do not survive going async.** The original agent routed accounts by swapping a
module-level client, which was safe only because it processed inputs strictly serially. Making it
async required threading an explicit per-run context through every tool first. Start with the
context; retrofitting it is a much larger change than writing it.

**Deduplicate before doing anything expensive.** The same real-world event arrived as two
differently-worded messages seconds apart, and both ran — producing duplicate destructive actions. A
content hash could not catch it, because the wordings differed. What worked was a second,
semantic key (`<action>:<subject>`) with a much shorter TTL: short enough not to suppress a genuine
repeat hours later, long enough to collapse the twins. Claim the key atomically, before any model
call.

**The demo/live boundary is a config flip.** A non-production account plus a config flag, both
required, both living only in the production stack's own config and env. No code branches on
"is this production".

**Split config from secrets and commit the config.** Prompts, models, routing and limits belong in
git where changes are reviewable; only credentials stay out. The agent then ships prompt changes
through the normal PR path.

## Process

**Verify throwaway scripts before trusting their output.** A one-off analysis script with a bug
produced confident, wrong numbers that shaped a decision. Lint even the disposable ones.

**Don't conclude "no data" from silence.** `gh run view --log` redirects to Azure Blob Storage; when
the devcontainer firewall blocked those hosts, log retrieval returned *empty*, not an error. An
environment limit will often look exactly like an absence of data. Check egress before believing it.

**An agent's docs belong next to the agent.** Knowledge scattered across a wiki, a README, and an
architecture page drifts apart within weeks. One page per agent, in its directory, is the rule this
factory adopted as a direct result.
