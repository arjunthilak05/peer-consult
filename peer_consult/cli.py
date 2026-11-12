"""peer-consult command line (Typer + backward-compatible ask/doctor).

    peer-consult setup [--force] [--dry-run]       install the agent skills + default config
    peer-consult uninstall                          remove them again
    peer-consult --version
    peer-consult doctor [--live]
    peer-consult ask --caller claude --target codex --request-file request.json
    peer-consult council discuss [--question "..." | --request-file req.json] [--chair claude]
    peer-consult council plan    [--question "..." | --request-file req.json] [--chair claude]
    peer-consult council execute --run-id <id> --approve [--writer claude]
    peer-consult council status  [--run-id <id>]
    peer-consult council resume  --run-id <id>
    peer-consult council cancel  --run-id <id>
    peer-consult council report  --run-id <id> [--format markdown|json]
    peer-consult council doctor  [--live]
    peer-consult council office  [--host 127.0.0.1] [--port 4173]

Top-level aliases (`peer-consult discuss|plan|execute|status|resume|cancel|report|office`)
are also registered for convenience across provider skills.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shlex
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from click.exceptions import ClickException
from click.exceptions import Exit as ClickExit

from . import __version__
from .config import PROVIDERS, ConfigError, load_config, validate_effort, validate_model
from .core import EXIT_OK, EXIT_USAGE, ask
from .council import CouncilOrchestrator
from .doctor import doctor
from .reporting import render_council_markdown
from .request import RequestError, load_request
from .state import CouncilStore

app = typer.Typer(
    name="peer-consult",
    help="Read-only second opinions and a three-agent council for Claude Code, OpenAI Codex CLI and Google Antigravity CLI (agy).",
    add_completion=False,
    no_args_is_help=True,
)
council_app = typer.Typer(
    name="council",
    help="Multi-agent council orchestration: discuss, plan, execute, status, resume, cancel, report, doctor, office",
    add_completion=False,
    no_args_is_help=True,
)
app.add_typer(council_app, name="council")


def _emit(obj: dict, output_file: str | None) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=True, indent=2) + "\n")
    sys.stdout.flush()
    if output_file:
        Path(output_file).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _summary(out: dict) -> None:
    m, e = out.get("model") or {}, out.get("effort") or {}
    line = (f"status={out.get('status')} target={out.get('target')} model requested={m.get('requested')} "
            f"reported={m.get('reported') or 'unknown'} effort requested={e.get('requested')} "
            f"observed={e.get('observed') or 'unknown'} elapsed={out.get('elapsed_seconds')}s")
    if out.get("error"):
        line += f" error={out['error']['kind']}: {out['error']['message']}"
    print(f"[peer-consult] {line}", file=sys.stderr, flush=True)


def _council_summary(out: dict) -> None:
    line = (
        f"status={out.get('status')} run_id={out.get('run_id')} mode={out.get('mode')} "
        f"run_status={out.get('run_status')} stage={out.get('current_stage')} chair={out.get('chair')}"
    )
    if out.get("writer"):
        line += f" writer={out.get('writer')}"
    if out.get("error"):
        line += f" error={out['error'].get('kind')}: {out['error'].get('message')}"
    print(f"[peer-consult:council] {line}", file=sys.stderr, flush=True)


def _build_request_loader(
    request_file: str | None,
    delete_request_file: bool,
    question: str | None,
    task_id: str | None,
    goal: str | None,
    help_type: str,
    help_type_detail: str | None,
    files: list[str] | None,
):
    def _loader() -> dict:
        if request_file and request_file != "-":
            p = Path(request_file)
            try:
                raw = p.read_text(encoding="utf-8-sig")
            except OSError as e:
                raise RequestError("invalid_request", f"cannot read request file: {e}")
            if delete_request_file:
                p.unlink(missing_ok=True)
            return load_request(raw)
        if question is not None:
            req_dict: dict = {
                "question": question,
                "help_type": help_type,
            }
            if help_type == "other" and not help_type_detail:
                req_dict["help_type_detail"] = "council discussion/planning"
            elif help_type_detail:
                req_dict["help_type_detail"] = help_type_detail
            if task_id:
                req_dict["task_id"] = task_id
            if goal:
                req_dict["goal"] = goal
            if files:
                req_dict["files"] = [{"path": f} for f in files]
            return load_request(json.dumps(req_dict, ensure_ascii=False))
        raw = sys.stdin.buffer.read().decode("utf-8-sig")
        return load_request(raw)

    return _loader


def _load_cfg_or_exit(output_file: str | None = None) -> dict:
    try:
        return load_config()
    except ConfigError as e:
        _emit({"status": "error", "error": {"kind": "config_error", "message": str(e)}}, output_file)
        raise typer.Exit(code=EXIT_USAGE)


def _run_discuss_or_plan(
    mode: str,
    *,
    question: str | None,
    request_file: str | None,
    delete_request_file: bool,
    task_id: str | None,
    goal: str | None,
    help_type: str,
    help_type_detail: str | None,
    files: list[str] | None,
    caller: str,
    chair: str | None,
    writer: str | None,
    base_dir: str | None,
    timeout: float | None,
    output_file: str | None,
    markdown_file: str | None,
) -> None:
    cfg = _load_cfg_or_exit(output_file)
    loader = _build_request_loader(
        request_file, delete_request_file, question, task_id, goal, help_type, help_type_detail, files
    )
    orch = CouncilOrchestrator(cfg)
    code, out = asyncio.run(
        orch.start_council_run(
            loader,
            mode=mode,
            caller=caller,
            chair_override=chair,
            writer_override=writer,
            base_dir=Path(base_dir) if base_dir else Path.cwd(),
            timeout_override=timeout,
        )
    )
    if markdown_file and out.get("run_id"):
        run_obj = orch.store.get_run(out["run_id"])
        if run_obj:
            md = render_council_markdown(run_obj, orch.store.get_stage_outputs(out["run_id"]))
            Path(markdown_file).write_text(md, encoding="utf-8")
    _emit(out, output_file)
    _council_summary(out)
    raise typer.Exit(code=code)


# ------------------------------------------------------------------
# Typer Commands (registered on both `council` sub-app and root `app`)
# ------------------------------------------------------------------

def _register_council_commands(target_app: typer.Typer) -> None:
    @target_app.command("discuss", help="Run 3-agent independent proposals, anonymized cross-critique, and chair synthesis.")
    def cmd_discuss(
        question: Annotated[Optional[str], typer.Option("--question", "-q", help="Question or problem statement")] = None,
        request_file: Annotated[Optional[str], typer.Option("--request-file", "-f", help="Path to request JSON packet ('-' for stdin)")] = None,
        delete_request_file: Annotated[bool, typer.Option("--delete-request-file", help="Delete request file after reading")] = False,
        task_id: Annotated[Optional[str], typer.Option("--task-id", help="Task identifier")] = None,
        goal: Annotated[Optional[str], typer.Option("--goal", help="High-level task goal")] = None,
        help_type: Annotated[str, typer.Option("--help-type", help="diagnosis | design_critique | experiment_review | code_review | other")] = "design_critique",
        help_type_detail: Annotated[Optional[str], typer.Option("--help-type-detail", help="Detail when help_type is 'other'")] = None,
        files: Annotated[Optional[list[str]], typer.Option("--file", help="Explicit file path to include (repeatable)")] = None,
        caller: Annotated[str, typer.Option("--caller", help="Calling agent (claude | codex | agy | user)")] = "user",
        chair: Annotated[Optional[str], typer.Option("--chair", help="Synthesis chair override (claude | codex | agy)")] = None,
        base_dir: Annotated[Optional[str], typer.Option("--base-dir", help="Base directory for relative file paths")] = None,
        timeout: Annotated[Optional[float], typer.Option("--timeout", help="Per-stage timeout in seconds")] = None,
        output_file: Annotated[Optional[str], typer.Option("--output-file", "-o", help="Write JSON output to file")] = None,
        markdown_file: Annotated[Optional[str], typer.Option("--markdown-file", "-m", help="Write Markdown report to file")] = None,
    ) -> None:
        _run_discuss_or_plan(
            "discuss",
            question=question,
            request_file=request_file,
            delete_request_file=delete_request_file,
            task_id=task_id,
            goal=goal,
            help_type=help_type,
            help_type_detail=help_type_detail,
            files=files,
            caller=caller,
            chair=chair,
            writer=None,
            base_dir=base_dir,
            timeout=timeout,
            output_file=output_file,
            markdown_file=markdown_file,
        )

    @target_app.command("plan", help="Synthesize an actionable, evidence-based implementation plan and await approval.")
    def cmd_plan(
        question: Annotated[Optional[str], typer.Option("--question", "-q", help="Objective or planning question")] = None,
        request_file: Annotated[Optional[str], typer.Option("--request-file", "-f", help="Path to request JSON packet ('-' for stdin)")] = None,
        delete_request_file: Annotated[bool, typer.Option("--delete-request-file", help="Delete request file after reading")] = False,
        task_id: Annotated[Optional[str], typer.Option("--task-id", help="Task identifier")] = None,
        goal: Annotated[Optional[str], typer.Option("--goal", help="High-level task goal")] = None,
        help_type: Annotated[str, typer.Option("--help-type", help="diagnosis | design_critique | experiment_review | code_review | other")] = "design_critique",
        help_type_detail: Annotated[Optional[str], typer.Option("--help-type-detail", help="Detail when help_type is 'other'")] = None,
        files: Annotated[Optional[list[str]], typer.Option("--file", help="Explicit file path to include (repeatable)")] = None,
        caller: Annotated[str, typer.Option("--caller", help="Calling agent (claude | codex | agy | user)")] = "user",
        chair: Annotated[Optional[str], typer.Option("--chair", help="Synthesis chair override (claude | codex | agy)")] = None,
        writer: Annotated[Optional[str], typer.Option("--writer", help="Preferred single writer (claude | codex | agy)")] = None,
        base_dir: Annotated[Optional[str], typer.Option("--base-dir", help="Base directory for relative file paths")] = None,
        timeout: Annotated[Optional[float], typer.Option("--timeout", help="Per-stage timeout in seconds")] = None,
        output_file: Annotated[Optional[str], typer.Option("--output-file", "-o", help="Write JSON output to file")] = None,
        markdown_file: Annotated[Optional[str], typer.Option("--markdown-file", "-m", help="Write Markdown report to file")] = None,
    ) -> None:
        _run_discuss_or_plan(
            "plan",
            question=question,
            request_file=request_file,
            delete_request_file=delete_request_file,
            task_id=task_id,
            goal=goal,
            help_type=help_type,
            help_type_detail=help_type_detail,
            files=files,
            caller=caller,
            chair=chair,
            writer=writer,
            base_dir=base_dir,
            timeout=timeout,
            output_file=output_file,
            markdown_file=markdown_file,
        )

    @target_app.command("execute", help="Execute an approved council plan in an isolated Git worktree with single writer and dual peer review.")
    def cmd_execute(
        run_id: Annotated[str, typer.Option("--run-id", "-r", help="Council plan run ID to execute")],
        approve: Annotated[bool, typer.Option("--approve", help="Explicitly approve execution of the synthesized plan")] = False,
        approval_token: Annotated[Optional[str], typer.Option("--approval-token", help="HMAC approval token issued by `council plan`")] = None,
        writer: Annotated[Optional[str], typer.Option("--writer", help="Single writer agent override (claude | codex | agy)")] = None,
        test_cmd: Annotated[Optional[str], typer.Option("--test-cmd", help="Deterministic test command (parsed as argv, shell=False)")] = None,
        timeout: Annotated[Optional[float], typer.Option("--timeout", help="Stage timeout in seconds")] = None,
        create_pr: Annotated[bool, typer.Option("--create-pr", help="Generate draft PR summary (never auto-merges or deploys)")] = False,
        output_file: Annotated[Optional[str], typer.Option("--output-file", "-o", help="Write JSON output to file")] = None,
        markdown_file: Annotated[Optional[str], typer.Option("--markdown-file", "-m", help="Write Markdown report to file")] = None,
    ) -> None:
        cfg = _load_cfg_or_exit(output_file)
        orch = CouncilOrchestrator(cfg)
        parsed_test_argv = shlex.split(test_cmd, posix=(sys.platform != "win32")) if test_cmd else None
        code, out = asyncio.run(
            orch.execute_plan(
                run_id,
                approve=approve,
                approval_token=approval_token,
                writer_override=writer,
                test_argv=parsed_test_argv,
                timeout_override=timeout,
                create_pr=create_pr,
            )
        )
        if markdown_file and out.get("run_id"):
            run_obj = orch.store.get_run(out["run_id"])
            if run_obj:
                md = render_council_markdown(run_obj, orch.store.get_stage_outputs(out["run_id"]))
                Path(markdown_file).write_text(md, encoding="utf-8")
        _emit(out, output_file)
        _council_summary(out)
        raise typer.Exit(code=code)

    @target_app.command("status", help="Inspect the status of a council run or list recent runs.")
    def cmd_status(
        run_id: Annotated[Optional[str], typer.Option("--run-id", "-r", help="Run ID to inspect (omit to list recent runs)")] = None,
        limit: Annotated[int, typer.Option("--limit", "-n", help="Max runs to list when --run-id is omitted")] = 20,
        output_file: Annotated[Optional[str], typer.Option("--output-file", "-o", help="Write JSON output to file")] = None,
    ) -> None:
        cfg = _load_cfg_or_exit(output_file)
        orch = CouncilOrchestrator(cfg)
        if run_id:
            env = orch.format_run_envelope(run_id)
            if env.get("error", {}) and env["error"].get("kind") == "run_not_found":
                _emit(env, output_file)
                raise typer.Exit(code=EXIT_USAGE)
            _emit(env, output_file)
            _council_summary(env)
            raise typer.Exit(code=EXIT_OK)
        runs = orch.store.list_runs(limit=limit)
        summary_list = [
            {
                "run_id": r["run_id"],
                "task_id": r["task_id"],
                "mode": r["mode"],
                "run_status": r["status"],
                "current_stage": r["current_stage"],
                "chair": r["chair"],
                "writer": r["writer"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in runs
        ]
        _emit({"status": "ok", "runs": summary_list, "count": len(summary_list)}, output_file)
        raise typer.Exit(code=EXIT_OK)

    @target_app.command("resume", help="Resume an interrupted or failed council run without repeating completed stages.")
    def cmd_resume(
        run_id: Annotated[str, typer.Option("--run-id", "-r", help="Run ID to resume")],
        timeout: Annotated[Optional[float], typer.Option("--timeout", help="Stage timeout in seconds")] = None,
        output_file: Annotated[Optional[str], typer.Option("--output-file", "-o", help="Write JSON output to file")] = None,
        markdown_file: Annotated[Optional[str], typer.Option("--markdown-file", "-m", help="Write Markdown report to file")] = None,
    ) -> None:
        cfg = _load_cfg_or_exit(output_file)
        orch = CouncilOrchestrator(cfg)
        code, out = asyncio.run(orch.resume_run(run_id, timeout_override=timeout))
        if markdown_file and out.get("run_id"):
            run_obj = orch.store.get_run(out["run_id"])
            if run_obj:
                md = render_council_markdown(run_obj, orch.store.get_stage_outputs(out["run_id"]))
                Path(markdown_file).write_text(md, encoding="utf-8")
        _emit(out, output_file)
        _council_summary(out)
        raise typer.Exit(code=code)

    @target_app.command("cancel", help="Request cancellation of a council run and terminate active subprocess trees.")
    def cmd_cancel(
        run_id: Annotated[str, typer.Option("--run-id", "-r", help="Run ID to cancel")],
        output_file: Annotated[Optional[str], typer.Option("--output-file", "-o", help="Write JSON output to file")] = None,
    ) -> None:
        _load_cfg_or_exit(output_file)
        store = CouncilStore()
        ok = store.request_cancel(run_id)
        if not ok:
            _emit(
                {"status": "error", "error": {"kind": "run_not_found", "message": f"run '{run_id}' not found"}},
                output_file,
            )
            raise typer.Exit(code=EXIT_USAGE)
        run = store.get_run(run_id)
        if run and run["status"] not in ("COMPLETED", "FAILED"):
            store.update_run(run_id, status="CANCELLED")
        _emit({"status": "ok", "run_id": run_id, "cancel_requested": True}, output_file)
        raise typer.Exit(code=EXIT_OK)

    @target_app.command("report", help="Render the human-readable Markdown or JSON report for a council run.")
    def cmd_report(
        run_id: Annotated[str, typer.Option("--run-id", "-r", help="Run ID to render")],
        fmt: Annotated[str, typer.Option("--format", help="Output format: markdown | json")] = "markdown",
        output_file: Annotated[Optional[str], typer.Option("--output-file", "-o", help="Write report to file")] = None,
    ) -> None:
        cfg = _load_cfg_or_exit(output_file)
        orch = CouncilOrchestrator(cfg)
        run = orch.store.get_run(run_id)
        if not run:
            _emit(
                {"status": "error", "error": {"kind": "run_not_found", "message": f"run '{run_id}' not found"}},
                output_file,
            )
            raise typer.Exit(code=EXIT_USAGE)
        if fmt.lower() == "json":
            env = orch.format_run_envelope(run_id)
            _emit(env, output_file)
            raise typer.Exit(code=EXIT_OK)
        md = render_council_markdown(run, orch.store.get_stage_outputs(run_id))
        if output_file:
            Path(output_file).write_text(md, encoding="utf-8")
        sys.stdout.write(md + "\n")
        sys.stdout.flush()
        raise typer.Exit(code=EXIT_OK)

    @target_app.command("doctor", help="Diagnose executables, auth, models, restrictions, skills, and council store.")
    def cmd_doctor(
        live: Annotated[bool, typer.Option("--live", help="Run a tiny real consultation against each target")] = False,
    ) -> None:
        cfg = _load_cfg_or_exit(None)
        code, rep = doctor(cfg, live=live)
        _emit(rep, None)
        for c in rep["checks"]:
            mark = {True: "OK  ", False: "FAIL", None: "INFO"}[c["ok"]]
            print(f"[{mark}] {c['name']}", file=sys.stderr)
        raise typer.Exit(code=code)

    @target_app.command("office", help="Launch the Interactive Pixel-Art AI Council Office web server.")
    def cmd_office(
        host: Annotated[Optional[str], typer.Option("--host", help="Bind host (default from config: 127.0.0.1)")] = None,
        port: Annotated[Optional[int], typer.Option("--port", help="Bind port (default from config: 4173)")] = None,
        no_browser: Annotated[bool, typer.Option("--no-browser", help="Do not automatically open a browser tab")] = False,
    ) -> None:
        cfg = _load_cfg_or_exit(None)
        from .office_server import run_office_server
        bind_host = host or cfg.get("office", {}).get("host", "127.0.0.1")
        bind_port = int(port or cfg.get("office", {}).get("port", 4173))
        run_office_server(cfg=cfg, host=bind_host, port=bind_port, open_browser=not no_browser)


@app.callback()
def _root(
    version: Annotated[bool, typer.Option("--version", "-V", help="Show the version and exit.")] = False,
) -> None:  # pragma: no cover - main() handles --version before Typer
    if version:
        print(f"peer-consult {__version__}")
        raise typer.Exit()


# `ask`, `setup` and `uninstall` are dispatched by main() before Typer sees them (argparse keeps the
# original `ask` interface byte-for-byte). These stubs only make them visible in `peer-consult --help`.
_PASSTHROUGH = {"context_settings": {"ignore_unknown_options": True, "allow_extra_args": True}, "add_help_option": False}


@app.command("ask", help="Consult one other agent CLI as a bounded read-only adviser (see `peer-consult ask -h`).", **_PASSTHROUGH)
def _cmd_ask(ctx: typer.Context) -> None:  # pragma: no cover - main() intercepts first
    raise typer.Exit(code=_legacy_ask_or_doctor(["ask", *ctx.args]))


@app.command("setup", help="Install the ask-* and council skills for Claude Code, Codex and agy, plus a default config.", **_PASSTHROUGH)
def _cmd_setup(ctx: typer.Context) -> None:  # pragma: no cover - main() intercepts first
    from .installer import setup_main
    raise typer.Exit(code=setup_main(ctx.args))


@app.command("uninstall", help="Remove the skills `setup` wrote (unmodified files only); keeps config and history.", **_PASSTHROUGH)
def _cmd_uninstall(ctx: typer.Context) -> None:  # pragma: no cover - main() intercepts first
    from .installer import uninstall_main
    raise typer.Exit(code=uninstall_main(ctx.args))


_register_council_commands(council_app)
_register_council_commands(app)



# ------------------------------------------------------------------
# Backward-Compatible `ask` and `doctor` Dispatcher
# ------------------------------------------------------------------

def _legacy_ask_or_doctor(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="peer-consult",
        description="Bounded Claude Code / Codex / Antigravity (agy) consultation helper",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor", help="diagnose executables, auth, models, restrictions and skills")
    d.add_argument("--live", action="store_true", help="also run a tiny real consultation against each target")
    a = sub.add_parser("ask", help="consult another agent CLI as a read-only adviser")
    a.add_argument("--caller", required=True, choices=PROVIDERS)
    a.add_argument("--target", required=True, choices=PROVIDERS)
    a.add_argument("--request-file", help="request JSON path ('-' or omitted = stdin)")
    a.add_argument("--delete-request-file", action="store_true", help="delete the request file after reading it")
    a.add_argument("--base-dir", help="directory relative 'files' paths resolve against (default: cwd)")
    a.add_argument("--model", help="override the configured model for this call (no fallback)")
    a.add_argument("--effort", help="override the configured effort for this call")
    a.add_argument("--timeout", type=float, help="seconds before the adviser process tree is killed")
    a.add_argument("--output-file", help="also write the result as UTF-8 JSON to this path")
    a.add_argument("--dry-run", action="store_true", help="validate and render the packet; do not launch")
    args = ap.parse_args(argv)

    try:
        cfg = load_config()
    except ConfigError as e:
        _emit({"status": "error", "error": {"kind": "config_error", "message": str(e)}}, None)
        return EXIT_USAGE

    if args.cmd == "doctor":
        code, rep = doctor(cfg, live=args.live)
        _emit(rep, None)
        for c in rep["checks"]:
            mark = {True: "OK  ", False: "FAIL", None: "INFO"}[c["ok"]]
            print(f"[{mark}] {c['name']}", file=sys.stderr)
        return code

    try:
        if args.model:
            validate_model(args.model)
        if args.effort:
            validate_effort(args.target, args.effort)
    except ConfigError as e:
        _emit({"status": "error", "error": {"kind": "invalid_override", "message": str(e)}}, args.output_file)
        return EXIT_USAGE

    def loader():
        if args.request_file and args.request_file != "-":
            p = Path(args.request_file)
            try:
                raw = p.read_text(encoding="utf-8-sig")
            except OSError as e:
                raise RequestError("invalid_request", f"cannot read request file: {e}")
            if args.delete_request_file:
                p.unlink(missing_ok=True)
        else:
            raw = sys.stdin.buffer.read().decode("utf-8-sig")
        return load_request(raw)

    code, out = ask(
        loader,
        caller=args.caller,
        target=args.target,
        cfg=cfg,
        base_dir=Path(args.base_dir) if args.base_dir else Path.cwd(),
        model_override=args.model,
        effort_override=args.effort,
        timeout_override=args.timeout,
        dry_run=args.dry_run,
    )
    _emit(out, args.output_file)
    _summary(out)
    return code


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    args_list = list(sys.argv[1:] if argv is None else argv)
    if args_list and args_list[0] in ("--version", "-V", "version"):
        print(f"peer-consult {__version__}")
        return EXIT_OK
    if args_list and args_list[0] in ("ask", "doctor"):
        return _legacy_ask_or_doctor(args_list)
    if args_list and args_list[0] == "setup":
        from .installer import setup_main
        return setup_main(args_list[1:])
    if args_list and args_list[0] == "uninstall":
        from .installer import uninstall_main
        return uninstall_main(args_list[1:])

    try:
        cmd = typer.main.get_command(app)
        rv = cmd.main(args=args_list, prog_name="peer-consult", standalone_mode=False)
        return int(rv) if isinstance(rv, int) else EXIT_OK
    except (typer.Exit, ClickExit) as e:
        return int(getattr(e, "exit_code", getattr(e, "code", 0)) or 0)
    except ClickException as e:
        e.show()
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
