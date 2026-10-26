"""``uv run python -m evals <command>``, from agents/upwork-scout. The README's "Prompt evals" is the guide.

run       one batch: a fixed prompt over a dataset, through the real writer
view      Promptfoo's viewer, where the operator rates (👍/👎) and comments
status    what is reviewed, unreviewed and failed in one eval
export    the reviewed batch as a feedback package (feedback/<run_id>.json)
propose   the editor model reads a package and saves ONE candidate prompt (candidates/<id>/)
compare   two evals side by side, by case id
add-jobs  append Apify actor records to a dataset as new cases
import-text  append postings copied from Upwork as text (datasets/source/*.txt)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evals.common import EvalError, live_prompt, promptfoo, rel


def _cmd_run(a: argparse.Namespace) -> None:
    from evals.experiment import run

    m = run(
        a.prompt or live_prompt(), a.dataset, concurrency=a.jobs, cache=a.reuse_cache, cases=a.case, repeat=a.repeat
    )
    print(f"\nrun {m['run_id']}  eval {m['eval_id']}")
    print(f"prompt {m['prompt']['path']}@{m['prompt']['sha']}  dataset {m['dataset']['id']}@{m['dataset']['version']}")
    if m["git"]["dirty"]:
        print("note: this agent's directory had uncommitted changes (recorded in the manifest)")
    print("next: uv run python -m evals view   (rate each output 👍/👎, comment, then `status`)")


def _cmd_view(a: argparse.Namespace) -> None:
    print(f"Promptfoo viewer on http://localhost:{a.port} (VS Code forwards the port). Ctrl-C stops it.")
    print("Rate in the normal eval view: ratings are NOT saved in the viewer's comparison mode.")
    promptfoo("view", "-n", "-p", str(a.port), check=False)


def _cmd_status(a: argparse.Namespace) -> None:
    from evals.review import status_lines

    print("\n".join(status_lines(a.eval_id)))


def _cmd_export(a: argparse.Namespace) -> None:
    from evals.review import feedback_package

    path, package = feedback_package(a.eval_id, partial=a.partial, out=a.out)
    s = package["summary"]
    print(
        f"wrote {rel(path)}: {s['approved']} approved, {s['rejected']} rejected,"
        f" {s['unreviewed']} unreviewed, {s['error']} errors"
    )
    print(f"next: uv run python -m evals propose {rel(path)}")


def _cmd_propose(a: argparse.Namespace) -> None:
    from evals.editor import propose

    out = propose(a.feedback, model=a.model, effort=a.effort, allow_validation=a.allow_validation, note=a.note)
    prompt = next(out.glob("prompt.*"))
    print(f"candidate saved: {rel(out)}/  ({prompt.name}, CHANGES.md, proposal.json)")
    print(f"next: uv run python -m evals run --prompt {rel(prompt)} --dataset <the same dataset>")


def _cmd_compare(a: argparse.Namespace) -> None:
    from evals.review import compare_lines

    print("\n".join(compare_lines(a.base, a.candidate)))


def _cmd_add_jobs(a: argparse.Namespace) -> None:
    from evals.dataset import add_records

    records = json.loads(a.records.read_text())
    records = records if isinstance(records, list) else [records]
    fixtures = a.fixtures or a.dataset.parent / "fixtures" / a.dataset.stem
    added = add_records(a.dataset, records, fixtures)
    print(f"added {len(added)} case(s) to {rel(a.dataset)}; bump dataset.version before the next run")


def _cmd_import_text(a: argparse.Namespace) -> None:
    from evals.dataset import add_records
    from evals.textimport import parse

    jobs = parse(a.source)
    wanted = sorted(jobs) if not a.jobs else [int(n) for n in a.jobs.split(",")]
    missing = [n for n in wanted if n not in jobs]
    if missing:
        raise EvalError(f"no such job numbers in {rel(a.source)}: {missing}")
    records = [jobs[n][0] for n in wanted]
    cases = {jobs[n][0]["jobId"]: jobs[n][1] for n in wanted}
    fixtures = a.fixtures or a.dataset.parent / "fixtures" / a.source.stem
    added = add_records(a.dataset, records, fixtures, cases)
    print(f"added {len(added)} case(s) to {rel(a.dataset)}: {', '.join(added) or '-'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m evals", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="run one batch")
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument(
        "--prompt", type=Path, help="default: the live version, the writer's system_prompt_file in agent_config.yaml"
    )
    p.add_argument("--jobs", "-j", type=int, help="parallel writer runs (default: settings.yaml)")
    p.add_argument("--case", action="append", help="only this case id (repeatable)")
    p.add_argument("--repeat", type=int, default=1, help="runs per case, to see variance")
    p.add_argument("--reuse-cache", action="store_true", help="reuse cached outputs (see README: caching)")
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("view", help="open Promptfoo's viewer")
    p.add_argument("--port", type=int, default=15500)
    p.set_defaults(func=_cmd_view)

    for name, func, text in (
        ("status", _cmd_status, "review progress of one eval"),
        ("export", _cmd_export, "write the feedback package"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("eval_id", nargs="?", default="latest", help="Promptfoo eval id (default: latest)")
        if name == "export":
            p.add_argument("--partial", action="store_true", help="export although some outputs are unreviewed")
            p.add_argument("--out", type=Path)
        p.set_defaults(func=func)

    p = sub.add_parser("propose", help="ask the editor model for one candidate prompt")
    p.add_argument("feedback", type=Path)
    p.add_argument("--model", help="editor model (default: settings.yaml)")
    p.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"))
    p.add_argument("--allow-validation", action="store_true", help="accept feedback from the validation split")
    p.add_argument("--note", help="the operator's directions for this round, applied to every proposal")
    p.set_defaults(func=_cmd_propose)

    p = sub.add_parser("compare", help="compare two evals by case id")
    p.add_argument("base")
    p.add_argument("candidate")
    p.set_defaults(func=_cmd_compare)

    p = sub.add_parser("add-jobs", help="append actor records (JSON list) to a dataset")
    p.add_argument("records", type=Path)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--fixtures", type=Path, help="default: <dataset dir>/fixtures/<dataset name>/")
    p.set_defaults(func=_cmd_add_jobs)

    p = sub.add_parser("import-text", help="append postings copied from Upwork as text (datasets/source/*.txt)")
    p.add_argument("source", type=Path)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--jobs", help="job numbers, e.g. 1,2,3 (default: all)")
    p.add_argument("--fixtures", type=Path, help="default: <dataset dir>/fixtures/<source name>/")
    p.set_defaults(func=_cmd_import_text)

    args = parser.parse_args(argv)
    try:
        args.func(args)
    except EvalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
