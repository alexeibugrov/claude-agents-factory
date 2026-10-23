FROM node:20

# bash + pipefail so any failing stage in a piped/chained RUN aborts the layer.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# BuildKit auto-populates TARGETARCH (amd64/arm64) per --platform; declare to use.
ARG TARGETARCH

ARG TZ
ENV TZ="$TZ"

# Locale. The base image generates only C / C.UTF-8 / POSIX — not en_US.UTF-8 —
# yet zsh-in-docker bakes en_US.UTF-8 exports into ~/.zshrc. Pointing LANG at an
# ungenerated locale makes Python tooling warn (and some abort with "could not
# initialize the preferred locale"). C.UTF-8 is always present in
# glibc and is the deterministic container locale. The interactive zsh sources
# ~/.zshrc *after* this ENV, so the same export is re-applied there (see the
# zsh-in-docker RUN below) — the ENV alone does not cover interactive shells.
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8

ARG CLAUDE_CODE_VERSION=latest
ARG MCP_SSH_MANAGER_VERSION=3.3.0
ARG GIT_DELTA_VERSION=0.18.2
ARG ZSH_IN_DOCKER_VERSION=1.2.0
ARG GH_VERSION=2.93.0
# uv — the Python package/venv manager every agent under agents/ builds with, and the
# runner for the pinned telegram-mcp server below.
ARG UV_VERSION=0.11.17
ARG TELEGRAM_MCP_VERSION=3.1.13

# Linters (release binaries)
ARG ACTIONLINT_VERSION=1.7.12
ARG GITLEAKS_VERSION=8.30.1
ARG HADOLINT_VERSION=2.14.0
ARG SHELLCHECK_VERSION=0.11.0
ARG SHFMT_VERSION=3.13.1
ARG TRIVY_VERSION=0.70.0
ARG YQ_VERSION=4.53.2
ARG ZIZMOR_VERSION=1.24.1

# Linters (pip)
ARG RUFF_VERSION=0.15.13
ARG SEMGREP_VERSION=1.163.0
ARG YAMLLINT_VERSION=1.38.0

# Linters (npm)
ARG MARKDOWNLINT_CLI2_VERSION=0.22.1
ARG PYRIGHT_VERSION=1.1.409

# Install basic development tools and iptables/ipset.
# `apt-get upgrade` pulls Debian security patches over the base layer (addresses
# upstream-image CVEs that haven't been re-rolled into a fresh base tag yet).
RUN apt-get update && apt-get upgrade -y --no-install-recommends && apt-get install -y --no-install-recommends \
  less \
  git \
  procps \
  sudo \
  fzf \
  zsh \
  man-db \
  unzip \
  gnupg2 \
  iptables \
  ipset \
  iproute2 \
  dnsutils \
  aggregate \
  jq \
  nano \
  vim \
  curl \
  ca-certificates \
  apt-transport-https \
  python3 \
  python3-pip \
  xz-utils \
  postgresql \
  postgresql-client \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

# Docker-in-Docker; dockerd is started by init-firewall.sh after the rules (the flush wipes its chains).
ARG DOCKER_MAJOR=29
RUN install -m 0755 -d /etc/apt/keyrings && \
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc && \
  echo "deb [arch=${TARGETARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" \
    > /etc/apt/sources.list.d/docker.list && \
  apt-get update && apt-get install -y --no-install-recommends \
    "docker-ce=5:${DOCKER_MAJOR}.*" \
    "docker-ce-cli=5:${DOCKER_MAJOR}.*" \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin \
  && apt-get clean && rm -rf /var/lib/apt/lists/* && \
  usermod -aG docker node

# Ensure default node user has access to /usr/local/share
RUN mkdir -p /usr/local/share/npm-global && \
  chown -R node:node /usr/local/share

ARG USERNAME=node

# Persist bash history.
RUN SNIPPET="export PROMPT_COMMAND='history -a' && export HISTFILE=/commandhistory/.bash_history" \
  && mkdir /commandhistory \
  && touch /commandhistory/.bash_history \
  && chown -R $USERNAME /commandhistory

# Set `DEVCONTAINER` environment variable to help with orientation
ENV DEVCONTAINER=true

# Indirection for skill examples — the linter-config dir can move without rewrites.
ENV LINT_CONFIGS=/workspaces/claude-agents-factory/.agentic/linter-configs

# Repo-root indirection — used by shell-command examples in CLAUDE.md, the skills, and
# the knowledge base. This Dockerfile is the SINGLE SOURCE OF TRUTH for these paths, so
# docs write ${VAR} and a move needs no doc sweep. This is a monorepo: the agents live
# in-tree under agents/, so there is nothing to clone and no per-repo variable.
#   AGENTS_FACTORY: this repo (cwd) — agentic config, knowledge base, and all agent code.
#   AGENTS:         the agents/ root; one self-contained agent per subdirectory.
#   KB:             the knowledge base — how-to-build-an-agent docs, conventions, tasks.
ENV AGENTS_FACTORY=/workspaces/claude-agents-factory
ENV AGENTS=/workspaces/claude-agents-factory/agents
ENV KB=/workspaces/claude-agents-factory/kb

# Create workspace and config directories and set permissions.
# /home/node/.ssh is created here with 0700 so bind-mounted private keys satisfy
# OpenSSH's strict-mode parent-dir check (otherwise sshd/ssh refuses the key).
# /home/node/.ssh-manager pre-existed so the .env bind-mount has a valid parent;
# the binary writes runtime state (history, backups) into the same dir.
# /home/node/.config/gh exists so the named-volume mount lands on a node-owned dir;
# `gh auth login` writes hosts.yml into the volume and persists across rebuilds.
RUN mkdir -p /workspace /home/node/.claude /home/node/.ssh /home/node/.ssh-manager /home/node/.config/gh && \
  chown -R node:node /workspace /home/node/.claude /home/node/.ssh /home/node/.ssh-manager /home/node/.config && \
  chmod 700 /home/node/.ssh

WORKDIR /workspace

# git-delta
RUN wget "https://github.com/dandavison/delta/releases/download/${GIT_DELTA_VERSION}/git-delta_${GIT_DELTA_VERSION}_${TARGETARCH}.deb" && \
  sudo dpkg -i "git-delta_${GIT_DELTA_VERSION}_${TARGETARCH}.deb" && \
  rm "git-delta_${GIT_DELTA_VERSION}_${TARGETARCH}.deb"

# gh (GitHub CLI) — pinned release binary, not Debian's stale `gh` (2.23.0) whose
# Actions log parser returns empty on reusable-workflow runs (fixed upstream in v2.70.0).
RUN curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${TARGETARCH}.tar.gz" -o /tmp/gh.tar.gz && \
  tar -xzf /tmp/gh.tar.gz -C /tmp && \
  install -m 0755 "/tmp/gh_${GH_VERSION}_linux_${TARGETARCH}/bin/gh" /usr/local/bin/gh && \
  rm -rf /tmp/gh.tar.gz "/tmp/gh_${GH_VERSION}_linux_${TARGETARCH}"

# shellcheck (.tar.xz, single binary; uses uname -m style)
RUN MARCH=$([ "$TARGETARCH" = "amd64" ] && echo x86_64 || echo aarch64) && \
  curl -fsSL "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/shellcheck-v${SHELLCHECK_VERSION}.linux.${MARCH}.tar.xz" -o /tmp/shellcheck.tar.xz && \
  tar -xJf /tmp/shellcheck.tar.xz -C /tmp && \
  install -m 0755 "/tmp/shellcheck-v${SHELLCHECK_VERSION}/shellcheck" /usr/local/bin/shellcheck && \
  rm -rf /tmp/shellcheck.tar.xz "/tmp/shellcheck-v${SHELLCHECK_VERSION}"

# shfmt
RUN curl -fsSL "https://github.com/mvdan/sh/releases/download/v${SHFMT_VERSION}/shfmt_v${SHFMT_VERSION}_linux_${TARGETARCH}" -o /usr/local/bin/shfmt && \
  chmod 0755 /usr/local/bin/shfmt

# actionlint
RUN curl -fsSL "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_${TARGETARCH}.tar.gz" -o /tmp/actionlint.tar.gz && \
  tar -xzf /tmp/actionlint.tar.gz -C /tmp/ actionlint && \
  install -m 0755 /tmp/actionlint /usr/local/bin/actionlint && \
  rm -f /tmp/actionlint.tar.gz /tmp/actionlint

# zizmor (Rust binary; asset name is a full target triple)
RUN TARGET=$([ "$TARGETARCH" = "amd64" ] && echo x86_64-unknown-linux-gnu || echo aarch64-unknown-linux-gnu) && \
  curl -fsSL "https://github.com/zizmorcore/zizmor/releases/download/v${ZIZMOR_VERSION}/zizmor-${TARGET}.tar.gz" -o /tmp/zizmor.tar.gz && \
  tar -xzf /tmp/zizmor.tar.gz -C /tmp zizmor && \
  install -m 0755 /tmp/zizmor /usr/local/bin/zizmor && \
  rm -f /tmp/zizmor.tar.gz /tmp/zizmor

# gitleaks (asset names: x64 / arm64)
RUN GARCH=$([ "$TARGETARCH" = "amd64" ] && echo x64 || echo arm64) && \
  curl -fsSL "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${GARCH}.tar.gz" -o /tmp/gitleaks.tar.gz && \
  tar -xzf /tmp/gitleaks.tar.gz -C /tmp gitleaks && \
  install -m 0755 /tmp/gitleaks /usr/local/bin/gitleaks && \
  rm -f /tmp/gitleaks.tar.gz /tmp/gitleaks

# hadolint (asset names: x86_64 / arm64)
RUN HARCH=$([ "$TARGETARCH" = "amd64" ] && echo x86_64 || echo arm64) && \
  curl -fsSL "https://github.com/hadolint/hadolint/releases/download/v${HADOLINT_VERSION}/hadolint-Linux-${HARCH}" -o /usr/local/bin/hadolint && \
  chmod 0755 /usr/local/bin/hadolint

# trivy (asset names: 64bit / ARM64)
RUN TARCH=$([ "$TARGETARCH" = "amd64" ] && echo 64bit || echo ARM64) && \
  curl -fsSL "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-${TARCH}.tar.gz" -o /tmp/trivy.tar.gz && \
  tar -xzf /tmp/trivy.tar.gz -C /tmp trivy && \
  install -m 0755 /tmp/trivy /usr/local/bin/trivy && \
  rm -f /tmp/trivy.tar.gz /tmp/trivy

# yq
RUN curl -fsSL "https://github.com/mikefarah/yq/releases/download/v${YQ_VERSION}/yq_linux_${TARGETARCH}" -o /usr/local/bin/yq && \
  chmod 0755 /usr/local/bin/yq

# Python tooling, system-wide (--break-system-packages is fine inside the container).
# yamllint/semgrep/ruff are linters; uv builds and runs every agent's own venv under
# agents/<name>/ and is also the runner for the telegram-mcp server installed below.
RUN pip3 install --no-cache-dir --break-system-packages \
    "yamllint==${YAMLLINT_VERSION}" \
    "semgrep==${SEMGREP_VERSION}" \
    "ruff==${RUFF_VERSION}" \
    "uv==${UV_VERSION}"

# Set up non-root user
USER node

# Install global packages
ENV NPM_CONFIG_PREFIX=/usr/local/share/npm-global
ENV PATH=$PATH:/usr/local/share/npm-global/bin

# Set the default shell to zsh rather than sh
ENV SHELL=/bin/zsh

# Set the default editor and visual
ENV EDITOR=nano
ENV VISUAL=nano

# Default powerline10k theme
RUN sh -c "$(wget -O- https://github.com/deluan/zsh-in-docker/releases/download/v${ZSH_IN_DOCKER_VERSION}/zsh-in-docker.sh)" -- \
  -p git \
  -p fzf \
  -a "source /usr/share/doc/fzf/examples/key-bindings.zsh" \
  -a "source /usr/share/doc/fzf/examples/completion.zsh" \
  -a "export PROMPT_COMMAND='history -a' && export HISTFILE=/commandhistory/.bash_history" \
  -a "export LANG=C.UTF-8 LC_ALL=C.UTF-8 LANGUAGE=" \
  -x

# Trust the bind-mounted workspace. The opened checkout appears inside the container
# with the host UID; without this, git 2.35+ refuses to operate on it with a
# "dubious ownership" warning.
#
# Also wire `gh` as the HTTPS credential helper for github.com and rewrite
# git@github.com: SSH URLs to https://github.com/ — so `git clone`/`git push` (CLI or
# VS Code Source Control) uses the OAuth token from `gh auth login` instead
# of requiring a bind-mounted SSH key. Combined with the named gh-config
# volume in devcontainer.json, one `gh auth login` persists across rebuilds
# and task containers.
RUN git config --global --add safe.directory '*' && \
  git config --global credential.https://github.com.helper '!gh auth git-credential' && \
  git config --global url.https://github.com/.insteadOf git@github.com: && \
  git config --global user.name "Aleksei Bugrov" && \
  git config --global user.email "bugroff.a@gmail.com"

# Install Claude
RUN npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}

# Install mcp-ssh-manager (provides the `mcp-ssh-manager` binary referenced by .mcp.json)
RUN npm install -g mcp-ssh-manager@${MCP_SSH_MANAGER_VERSION}

# Telegram MCP server (read-only Telegram access for Claude), pinned and installed at
# build time so the firewalled runtime needs no PyPI/GitHub egress — only Telegram's DC
# ranges. Credentials are never baked in: the server reads the gitignored
# .env.telegram.mcp at runtime (see .mcp.json).
USER root
RUN git clone --depth 1 --branch "v${TELEGRAM_MCP_VERSION}" \
      https://github.com/chigwell/telegram-mcp.git /opt/telegram-mcp && \
    chown -R node:node /opt/telegram-mcp
USER node
RUN uv --directory /opt/telegram-mcp sync

# npm-based linters (pyright, markdownlint-cli2)
RUN npm install -g \
    pyright@${PYRIGHT_VERSION} \
    markdownlint-cli2@${MARKDOWNLINT_CLI2_VERSION}


# Copy and set up firewall script
COPY init-firewall.sh /usr/local/bin/
USER root
RUN chmod +x /usr/local/bin/init-firewall.sh && \
  echo "node ALL=(root) NOPASSWD: /usr/local/bin/init-firewall.sh" > /etc/sudoers.d/node-firewall && \
  chmod 0440 /etc/sudoers.d/node-firewall
USER node
