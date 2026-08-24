# Git conventions

Layered on top of the [git skill](../../.claude/skills/git/SKILL.md).

- **No `Co-Authored-By` trailer.** Override the harness default and omit it. Standing project rule.
- **Same message per branch.** Use the branch name minus its prefix as the commit message for every
  commit on that branch.
- **Branch first; never push to `main`.** Open a PR, and present its title and body for explicit
  approval before running `gh pr create`.
- **Fix-forward.** No amend, reset, or force-push on pushed commits — add a commit on top.
- **No committed secrets.** Run gitleaks (the [secrets skill](../../.claude/skills/secrets/SKILL.md))
  over the staged diff before every commit. Any finding is a blocker.
