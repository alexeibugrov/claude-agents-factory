# Runbook — preparing the VM for a new agent

One-time, per agent, done by the **operator** before its first deploy. CI creates `/app/<name>` and
ships the compose file and config, but it never creates the secrets file — so a first deploy against
an unprepared directory fails at `docker compose up`, which is the intended behaviour.

Claude can prepare the exact lines to paste. Claude does **not** apply them and never reads the
resulting file.

The VM is addressed by **IP (157.90.18.149)** — the old `app.pulse-ai.live` DNS record no longer
resolves. If the host ever moves, it is named in four places: the ssh-manager `.env`, the deploy
workflow's `DEPLOY_HOST`, the firewall's static-IP block, and this runbook.

## Prerequisites

- The agent exists under `agents/<name>/` and its caller workflow is merged to `main`.
- `SSH_PRIVATE_KEY` is set as a repository **secret** (encrypted), not a variable.
- The VM has persistent journald — `/var/log/journal` exists (the Ubuntu default). Without it
  Docker refuses to start a container using the `journald` log driver, with no fallback.

## Steps

1. **Create the directory.**

   ```bash
   ssh root@157.90.18.149 'mkdir -p /app/<name>/claude-config && chown -R 10001:10001 /app/<name>/claude-config'
   ```

   The `10001` uid matches the container's non-root `appuser`, so the CLI can write its session
   scratch into the mount.

2. **Create the secrets file** from `agents/<name>/<name>.env.template`:

   ```bash
   ssh root@157.90.18.149 'cat > /app/<name>/.env.<name>'   # paste, then Ctrl-D
   chmod 600 /app/<name>/.env.<name>
   ```

   It must contain `CLAUDE_CODE_OAUTH_TOKEN` and must **not** contain `ANTHROPIC_API_KEY` — see
   [architecture/auth.md](../architecture/auth.md).

3. **Get a subscription token**, if you do not have a current one. On any machine with a browser:

   ```bash
   claude setup-token
   ```

   It lasts about a year and does not auto-refresh. Renew by re-running this and updating the file.

4. **Deploy.** Merge a change under `agents/<name>/` to `main`, or run the caller workflow manually.

5. **Verify.**

   ```bash
   ssh root@157.90.18.149 'cd /app/<name> && docker compose ps'
   ssh root@157.90.18.149 'journalctl CONTAINER_TAG=<name> --since "10 minutes ago"'
   ```

   A healthy first start logs `agent starting: model=… allow_writes=…`. A startup refusal about
   `ANTHROPIC_API_KEY` or a missing token means step 2 is wrong — fix the file, do not remove
   the check.

## Rotating the token

Update `/app/<name>/.env.<name>`, then `cd /app/<name> && docker compose up -d --force-recreate`.
Every agent has its own copy, so rotate them all when the token changes.

## Removing an agent

```bash
ssh root@157.90.18.149 'cd /app/<name> && docker compose down'
```

Then delete `agents/<name>/` and `.github/workflows/<name>.yml`, and remove `/app/<name>` on the VM
once you are sure nothing in it is worth keeping.
