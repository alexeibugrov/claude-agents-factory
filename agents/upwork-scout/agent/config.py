"""Parse the committed, secret-free ``agent_config.yaml`` into an :class:`AgentConfig`.

Secrets are deliberately absent from this file and from the image: they arrive as environment
variables from the gitignored ``.env.<agent>`` on the VM. The config carries only what is safe
to version — models, limits, both role prompts, searches, filters, and the agent's own knobs.

Loading fails fast. A missing model or an unparseable file should stop the container at startup,
where it is obvious, rather than surface as a confusing failure on the first real request.

This agent has two roles (``screener`` and ``writer``), each with its own model, limits and prompt,
so the template's single top-level ``system_prompt`` is replaced by one per role. The screener runs
only while ``settings.pipeline.screening_enabled`` is true; its section is always required.

``about_me_file`` names one document about the operator, written for no particular role, that is
appended to every role's prompt.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import yaml

# The compose file bind-mounts the config here; AGENT_CONFIG overrides it so one image can serve
# several stacks (e.g. a dev and a prod variant that differ only by config).
_DEFAULT_CONFIG = Path(__file__).parent.parent / "agent_config.yaml"

# Operator hard limit: no actor run may return more than this many jobs.
MAX_RESULTS_LIMIT = 10

EFFORTS = ("low", "medium", "high", "xhigh", "max")

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Code prefilters (D7). Every rule is off when its value is null; the code only implements the
# rule types, the operator owns the thresholds.
PREFILTER_KEYS = (
    "require_payment_verified",
    "min_client_total_spent",
    "min_client_rating",
    "min_client_review_count",
    "max_total_applicants",
    "job_types",
    "min_hourly_rate",
    "min_fixed_budget",
    "exclude_client_country_codes",
    "include_client_country_codes",
)

# Upwork returns 0 jobs, silently, for a query over ~90 words; 80 leaves a margin.
MAX_QUERY_WORDS = 80
_OPERATORS = {"OR", "AND", "NOT"}


class AgentConfigError(RuntimeError):
    """Raised when ``agent_config.yaml`` is missing, unparseable, or incomplete."""


@dataclass(frozen=True)
class RoleConfig:
    """One agent role (screener or writer): its model, limits and system prompt."""

    name: str
    model: str
    system_prompt: str
    # The prompt version's file as configured (prompts/<role>/v<N>.md); None for an inline prompt.
    system_prompt_file: str | None = None
    # The shared ABOUT ME document, appended to system_prompt (prompts/about-me/v<N>.md).
    about_me: str | None = None
    about_me_file: str | None = None
    fallback_model: str | None = None
    max_turns: int = 4
    max_budget_usd: float | None = None
    # Reasoning effort passed to the SDK; None leaves the model's default.
    effort: str | None = None
    # Wall-clock cap on one run; past it the run fails (and is retried within max_attempts).
    timeout_s: float = 600.0

    @property
    def full_prompt(self) -> str:
        """What the model gets: the role prompt, then ABOUT ME."""
        return compose_prompt(self.system_prompt, self.about_me)

    @property
    def prompt_sha(self) -> str:
        """Ties every stored verdict or draft to the exact prompt, ABOUT ME included, that produced it."""
        return hashlib.sha256(self.full_prompt.encode("utf-8")).hexdigest()[:16]

    @property
    def prompt_ref(self) -> str:
        """``<file>[+<about me file>]@<sha>``: which versions are live, as the startup log names them."""
        files = self.system_prompt_file or "inline"
        if self.about_me_file:
            files += f"+{self.about_me_file}"
        return f"{files}@{self.prompt_sha}"


def compose_prompt(prompt: str, about_me: str | None) -> str:
    return f"{prompt}\n\n{about_me}" if about_me else prompt


@dataclass(frozen=True)
class Search:
    """One Apify search: a stable slug plus the actor input merged over the shared defaults."""

    name: str
    run_input: dict[str, Any]
    # From APIFY_STATE_SUFFIX: a local run on the same Apify account must not consume the VM's
    # incremental state, or the VM never sees the jobs the local run already took.
    state_suffix: str = ""

    @property
    def state_key(self) -> str:
        # Renaming a search deliberately resets its incremental state.
        key = f"upwork-scout-{self.name}"
        return f"{key}-{self.state_suffix}" if self.state_suffix else key


@dataclass(frozen=True)
class ApifyConfig:
    actor_id: str
    searches: tuple[Search, ...]
    timeout_secs: int = 600
    memory_mbytes: int = 1024
    max_charge_per_run_usd: float = 0.05


@dataclass(frozen=True)
class PipelineConfig:
    # On: every job past the prefilters is rated 0-5, then offered whatever its match. Off: offered unrated.
    screening_enabled: bool = False
    max_screen_per_cycle: int = 10
    max_offers_per_cycle: int = 50
    max_draft_per_cycle: int = 5
    max_attempts: int = 3
    max_age_hours_to_screen: float | None = 6
    skip_known_reposts: bool = True


@dataclass(frozen=True)
class TelegramConfig:
    chat_id: int | str | None = None
    topic_id: int | None = None
    session_path: str = "/app/telegram-session/upwork_scout"
    send_interval_s: float = 1.0
    # A reply to an offer containing one of these tokens (case-insensitive, whole token) asks the
    # writer for a proposal.
    triggers: tuple[str, ...] = ("+", "go")
    # Safety-net poll; a reply event wakes the poll at once (agent/telegram.py on_reply).
    poll_interval_s: float = 60.0


@dataclass(frozen=True)
class DbConfig:
    host: str = "db"
    port: int = 5432
    name: str = "upwork_scout"
    user: str = "upwork_scout"


@dataclass(frozen=True)
class AgentConfig:
    screener: RoleConfig
    writer: RoleConfig
    apify: ApifyConfig
    interval_minutes: float = 30
    allow_writes: bool = False
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    prefilter: dict[str, Any] = field(default_factory=dict)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    db: DbConfig = field(default_factory=DbConfig)

    @classmethod
    def load(cls, path: str | os.PathLike[str] | None = None) -> "AgentConfig":
        cfg_path = Path(path or os.environ.get("AGENT_CONFIG") or _DEFAULT_CONFIG)
        if not cfg_path.is_file():
            raise AgentConfigError(f"agent config not found: {cfg_path}")
        try:
            raw = yaml.safe_load(cfg_path.read_text()) or {}
        except yaml.YAMLError as exc:
            raise AgentConfigError(f"agent config is not valid YAML: {cfg_path}: {exc}") from exc
        return cls.from_dict(raw, source=str(cfg_path), base_dir=cfg_path.parent)

    @classmethod
    def from_dict(cls, raw: dict[str, Any], source: str = "config", base_dir: Path | None = None) -> "AgentConfig":
        agent = raw.get("agent") or {}
        settings = raw.get("settings") or {}
        allow_writes = bool(agent.get("allow_writes", False))

        schedule = settings.get("schedule") or {}
        interval = float(schedule.get("interval_minutes", 30))
        if interval <= 0:
            raise AgentConfigError(f"settings.schedule.interval_minutes must be > 0 in {source}")

        prefilter = settings.get("prefilter") or {}
        unknown = set(prefilter) - set(PREFILTER_KEYS)
        if unknown:
            raise AgentConfigError(f"unknown settings.prefilter keys {sorted(unknown)} in {source}")

        telegram = _telegram(settings.get("telegram") or {})
        if allow_writes and telegram.chat_id is None:
            raise AgentConfigError(f"settings.telegram.chat_id is required when allow_writes is true ({source})")

        about_me_file = raw.get("about_me_file")
        about_me = _read_prompt_file("about_me_file", about_me_file, source, base_dir) if about_me_file else None
        return cls(
            screener=_role("screener", raw.get("screener"), source, base_dir, about_me, about_me_file),
            writer=_role("writer", raw.get("writer"), source, base_dir, about_me, about_me_file),
            apify=_apify(settings.get("apify") or {}, source),
            interval_minutes=interval,
            allow_writes=allow_writes,
            pipeline=_pipeline(settings.get("pipeline") or {}),
            prefilter=prefilter,
            telegram=telegram,
            db=DbConfig(**(settings.get("db") or {})),
        )


def _role(
    name: str,
    raw: dict[str, Any] | None,
    source: str,
    base_dir: Path | None,
    about_me: str | None = None,
    about_me_file: str | None = None,
) -> RoleConfig:
    if not raw:
        raise AgentConfigError(f"'{name}' role section is required in {source}")
    model = raw.get("model")
    if not model:
        raise AgentConfigError(f"{name}.model is required in {source}")
    effort = raw.get("effort")
    if effort is not None and effort not in EFFORTS:
        raise AgentConfigError(f"{name}.effort must be one of {', '.join(EFFORTS)} (got {effort!r}) in {source}")
    prompt = _prompt_text(name, raw, source, base_dir)
    if not prompt:
        raise AgentConfigError(f"{name}.system_prompt is required in {source}")
    return RoleConfig(
        name=name,
        model=model,
        system_prompt=prompt,
        system_prompt_file=raw.get("system_prompt_file"),
        about_me=about_me,
        about_me_file=about_me_file,
        fallback_model=raw.get("fallback_model"),
        max_turns=int(raw.get("max_turns", 4)),
        max_budget_usd=raw.get("max_budget_usd"),
        effort=effort,
        timeout_s=float(raw.get("timeout_s", 600)),
    )


def _prompt_text(name: str, raw: dict[str, Any], source: str, base_dir: Path | None) -> str:
    """The role prompt, inline (``system_prompt``) or from a file (``system_prompt_file``).

    A file path is relative to the config file's directory. Prompts live in their own files so each
    has a readable git history; CI ships the directory next to the config, like the config itself.
    """
    if raw.get("system_prompt") and raw.get("system_prompt_file"):
        raise AgentConfigError(f"{name}: set system_prompt or system_prompt_file, not both, in {source}")
    if not raw.get("system_prompt_file"):
        return (raw.get("system_prompt") or "").strip()
    return _read_prompt_file(f"{name}.system_prompt_file", raw["system_prompt_file"], source, base_dir)


def _read_prompt_file(key: str, file: str, source: str, base_dir: Path | None) -> str:
    path = Path(file)
    if not path.is_absolute():
        path = (base_dir or Path.cwd()) / path
    if not path.is_file():
        raise AgentConfigError(f"{key} not found: {path} ({source})")
    return path.read_text(encoding="utf-8").strip()


def search_query(run_input: dict[str, Any]) -> str:
    """The Upwork query of a search: ``query``, or the URL-decoded ``q`` of ``searchUrl``."""
    if run_input.get("query"):
        return str(run_input["query"])
    params = parse_qs(urlsplit(str(run_input.get("searchUrl") or "")).query)
    return (params.get("q") or [""])[0]


def query_words(query: str) -> int:
    """Words as Upwork counts them: operators and quotes aside, split on whitespace, ``-`` and ``/``."""
    tokens = re.split(r"[\s\-/]+", query.replace('"', " ").replace("(", " ").replace(")", " "))
    return sum(1 for t in tokens if t and t not in _OPERATORS)


def _apify(raw: dict[str, Any], source: str) -> ApifyConfig:
    actor_id = raw.get("actor_id")
    if not actor_id:
        raise AgentConfigError(f"settings.apify.actor_id is required in {source}")
    defaults = dict(raw.get("defaults_input") or {})
    searches: list[Search] = []
    state_suffix = os.environ.get("APIFY_STATE_SUFFIX", "").strip()
    if state_suffix and not _SLUG.match(state_suffix):
        raise AgentConfigError(f"APIFY_STATE_SUFFIX {state_suffix!r} must be a lowercase slug")
    for entry in raw.get("searches") or []:
        name = str(entry.get("name") or "")
        if not _SLUG.match(name):
            raise AgentConfigError(f"search name {name!r} must be a lowercase slug in {source}")
        if any(s.name == name for s in searches):
            raise AgentConfigError(f"duplicate search name {name!r} in {source}")
        run_input = {**defaults, **(entry.get("run_input") or {})}
        if not (run_input.get("query") or run_input.get("searchUrl")):
            raise AgentConfigError(f"search {name!r} needs run_input.query or run_input.searchUrl in {source}")
        words = query_words(search_query(run_input))
        if words > MAX_QUERY_WORDS:
            raise AgentConfigError(
                f"search {name!r}: query has {words} words, max {MAX_QUERY_WORDS}"
                f" (Upwork returns 0 above ~90) in {source}"
            )
        max_results = int(run_input.get("maxResults", 0))
        if not 0 < max_results <= MAX_RESULTS_LIMIT:
            raise AgentConfigError(
                f"search {name!r}: maxResults must be 1..{MAX_RESULTS_LIMIT} (got {max_results}) in {source}"
            )
        searches.append(Search(name=name, run_input=run_input, state_suffix=state_suffix))
    if not searches:
        raise AgentConfigError(f"settings.apify.searches must list at least one search in {source}")
    return ApifyConfig(
        actor_id=actor_id,
        searches=tuple(searches),
        timeout_secs=int(raw.get("timeout_secs", 600)),
        memory_mbytes=int(raw.get("memory_mbytes", 1024)),
        max_charge_per_run_usd=float(raw.get("max_charge_per_run_usd", 0.05)),
    )


def _pipeline(raw: dict[str, Any]) -> PipelineConfig:
    return PipelineConfig(**raw)


def _telegram(raw: dict[str, Any]) -> TelegramConfig:
    values = dict(raw)
    # Local runs point at their own session (one session per place, never shared with the VM).
    if os.environ.get("TELEGRAM_SESSION_PATH"):
        values["session_path"] = os.environ["TELEGRAM_SESSION_PATH"]
    if "triggers" in values:
        values["triggers"] = tuple(str(t).strip().lower() for t in values["triggers"] or [] if str(t).strip())
        if not values["triggers"] or any(len(t.split()) > 1 for t in values["triggers"]):
            raise AgentConfigError("settings.telegram.triggers must list single words or signs, at least one")
    return TelegramConfig(**values)
