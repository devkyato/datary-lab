"""Datary command-line interface."""

from __future__ import annotations

import argparse
import csv
import importlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import IO, Any, Dict, List, Optional, Sequence

from datary import __version__
from datary.comparison import compare_sessions
from datary.config import DEFAULT_PLOT_MAX_POINTS, default_workspace
from datary.conversion import convert_source
from datary.formats import SUPPORTED_FORMATS
from datary.generators import PROFILES, generate_records
from datary.inspection import inspect_source, load_source
from datary.models import RecordOptions
from datary.plotting import create_plot
from datary.recorder import record_stream
from datary.replay import replay_session
from datary.reports import write_report
from datary.sessions import Session, list_sessions
from datary.utils import (
    atomic_text,
    csv_safe_cell,
    markdown_safe,
    parse_key_values,
    safe_filename_component,
    safe_output,
    sparkline,
    terminal_safe,
)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="datary", description="Local-first terminal laboratory for reproducible data."
    )
    root.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    root.add_argument(
        "--workspace",
        type=Path,
        default=default_workspace(),
        help="session workspace (or DATARY_WORKSPACE)",
    )
    commands = root.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record", help="record a named session from standard input")
    record.add_argument("name")
    record.add_argument("--format", choices=SUPPORTED_FORMATS)
    record.add_argument("--time-field")
    record.add_argument("--target-field")
    record.add_argument("--response-field")
    record.add_argument("--sequence-field")
    record.add_argument("--latency-field")
    record.add_argument("--bytes-field")
    record.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
    record.add_argument("--unit", action="append", default=[], metavar="FIELD=UNIT")
    record.add_argument("--command", dest="original_command")
    record.add_argument("--overwrite", action="store_true")
    record.add_argument("--include-path", action="store_true")
    record.add_argument("--max-line-bytes", type=int, default=1_048_576)
    record.add_argument("--max-fields", type=int, default=1000)
    inspect = commands.add_parser("inspect", help="inspect a session or data file")
    inspect.add_argument("source")
    inspect.add_argument("--format", choices=SUPPORTED_FORMATS)
    inspect.add_argument("--time-field")
    inspect.add_argument("--target-field")
    inspect.add_argument("--response-field")
    inspect.add_argument("--sequence-field")
    inspect.add_argument("--latency-field")
    inspect.add_argument("--bytes-field")
    inspect.add_argument("--field")
    inspect.add_argument("--quality", action="store_true")
    inspect.add_argument(
        "--monotonic-field",
        action="append",
        default=[],
        help="field expected to be non-decreasing; repeat for multiple fields",
    )
    inspect.add_argument(
        "--counter-field",
        action="append",
        default=[],
        help="counter field checked for resets; repeat for multiple fields",
    )
    inspect.add_argument("--plot", help="comma-separated fields")
    inspect.add_argument("--plot-format", choices=("png", "svg"), default="png")
    inspect.add_argument(
        "--plot-kind",
        choices=("line", "scatter", "step", "histogram"),
        default="line",
    )
    inspect.add_argument(
        "--plot-max-points",
        type=int,
        default=None,
        help=(
            "maximum plotted points per field before extrema-preserving downsampling "
            f"(default {DEFAULT_PLOT_MAX_POINTS})"
        ),
    )
    inspect.add_argument("--overwrite-plot", action="store_true")
    inspect.add_argument("--json", action="store_true")
    compare = commands.add_parser("compare", help="compare two or more sessions/files")
    compare.add_argument("sources", nargs="+")
    compare.add_argument("--field", action="append")
    compare.add_argument("--goal")
    compare.add_argument("--report", type=Path)
    compare.add_argument("--overwrite", action="store_true")
    compare.add_argument(
        "--format", choices=("terminal", "json", "markdown", "csv"), default="terminal"
    )
    replay = commands.add_parser("replay", help="replay a recorded session")
    replay.add_argument("session")
    replay.add_argument("--speed", type=float, default=1.0)
    replay.add_argument("--loop", action="store_true")
    replay.add_argument("--format", choices=("jsonl", "csv"), default="jsonl")
    replay.add_argument("--no-timing", action="store_true")
    replay.add_argument("--virtual", action="store_true", help=argparse.SUPPRESS)
    report = commands.add_parser("report", help="generate a local report")
    report.add_argument("session")
    report.add_argument("--format", choices=("markdown", "json"), default="markdown")
    report.add_argument("--output", type=Path)
    report.add_argument("--overwrite", action="store_true")
    generate = commands.add_parser("generate", help="generate deterministic synthetic data")
    generate.add_argument("profile", choices=PROFILES)
    generate.add_argument("--seed", type=int, default=0)
    generate.add_argument("--duration", type=float, default=10.0)
    generate.add_argument("--sample-rate", type=float, default=10.0)
    generate.add_argument("--noise", type=float, default=0.05)
    generate.add_argument("--missing-rate", type=float)
    generate.add_argument("--duplicate-rate", type=float)
    generate.add_argument("--format", choices=("jsonl", "csv"), default="jsonl")
    generate.add_argument("--output", type=Path)
    generate.add_argument("--overwrite", action="store_true")
    generate.add_argument("--real-time", action="store_true")
    convert = commands.add_parser("convert", help="convert a supported local file")
    convert.add_argument("source", type=Path)
    convert.add_argument("--to", choices=("csv", "jsonl"), required=True)
    convert.add_argument("--format", choices=SUPPORTED_FORMATS)
    convert.add_argument("--output", type=Path)
    convert.add_argument("--overwrite", action="store_true")
    commands.add_parser("sessions", help="list sessions")
    doctor = commands.add_parser("doctor", help="check installation and session integrity")
    doctor.add_argument("--json", action="store_true")
    return root


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        return _dispatch(arguments)
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except OSError:
            pass
        return 0
    except KeyboardInterrupt:
        print("datary: interrupted", file=sys.stderr)
        return 130
    except FileExistsError as error:
        target = terminal_safe(error)
        print(
            f"datary: error: path already exists: {target} (pass --overwrite to replace it)",
            file=sys.stderr,
        )
        return 2
    except (OSError, ValueError, json.JSONDecodeError, ImportError) as error:
        print(f"datary: error: {terminal_safe(error)}", file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace) -> int:
    workspace = args.workspace
    if args.command == "record":
        path = record_stream(
            sys.stdin,
            RecordOptions(
                name=args.name,
                workspace=workspace,
                input_format=args.format,
                time_field=args.time_field,
                command=args.original_command,
                parameters=parse_key_values(args.param),
                units=parse_key_values(args.unit),
                overwrite=args.overwrite,
                include_path=args.include_path,
                max_line_bytes=args.max_line_bytes,
                max_fields=args.max_fields,
                target_field=args.target_field,
                response_field=args.response_field,
                sequence_field=args.sequence_field,
                latency_field=args.latency_field,
                bytes_field=args.bytes_field,
            ),
        )
        session = Session.open(path)
        print(
            f"Recorded {session.manifest['valid_record_count']} valid and "
            f"{session.manifest['invalid_record_count']} invalid records in "
            f"{terminal_safe(path)}"
        )
    elif args.command == "inspect":
        inspection = inspect_source(
            _resolve(args.source, workspace),
            input_format=args.format,
            time_field=args.time_field,
            monotonic_fields=args.monotonic_field,
            counter_fields=args.counter_field,
            target_field=args.target_field,
            response_field=args.response_field,
            sequence_field=args.sequence_field,
            latency_field=args.latency_field,
            bytes_field=args.bytes_field,
        )
        if args.json:
            print(json.dumps(inspection.to_dict(), indent=2, ensure_ascii=False))
        else:
            _print_inspection(inspection.to_dict(), args.field, args.quality)
        if args.plot:
            source = _resolve(args.source, workspace)
            records, _, _, _, manifest_time = load_source(source, args.format)
            session_path = Path(source) if Path(source).is_dir() else workspace
            fields = [field.strip() for field in args.plot.split(",") if field.strip()]
            if not fields:
                raise ValueError("--plot requires at least one non-empty field")
            plot_root = session_path / "plots"
            if plot_root.is_symlink():
                raise ValueError("session plot directory may not be a symbolic link")
            filename = "plot-" + safe_filename_component("-".join(fields), "data")
            output = safe_output(
                plot_root,
                Path(f"{filename}.{args.plot_format}"),
            )
            max_points = (
                DEFAULT_PLOT_MAX_POINTS if args.plot_max_points is None else args.plot_max_points
            )
            plot = create_plot(
                records,
                fields,
                output,
                time_field=args.time_field or manifest_time,
                kind=args.plot_kind,
                overwrite=args.overwrite_plot,
                max_points=max_points,
            )
            print(f"Plot: {terminal_safe(plot.path)}")
            info = plot.downsample
            print(
                "Plot downsample: "
                f"algorithm={info.algorithm} applied={info.applied} "
                f"original={info.original_point_count} plotted={info.plotted_point_count} "
                f"max_points={info.max_points} "
                f"preserved_extrema={info.preserved_global_extrema}"
            )
            print(f"Plot metadata: {terminal_safe(plot.metadata_path)}")
    elif args.command == "compare":
        if len(args.sources) < 2:
            raise ValueError("compare requires at least two sources")
        result = compare_sessions(
            [_resolve(source, workspace) for source in args.sources], args.field, args.goal
        )
        rendered = _comparison_output(result.to_dict(), args.format)
        if args.report:
            if args.report.exists() and not args.overwrite:
                raise FileExistsError(args.report)
            atomic_text(args.report, rendered)
        else:
            print(rendered)
    elif args.command == "replay":
        session = Session.open(_resolve(args.session, workspace))
        while True:
            replay_session(
                session,
                sys.stdout,
                speed=args.speed,
                no_timing=args.no_timing,
                virtual=args.virtual,
                output_format=args.format,
            )
            if not args.loop:
                break
    elif args.command == "report":
        session = Session.open(_resolve(args.session, workspace))
        suffix = ".json" if args.format == "json" else ".md"
        report_root = session.path / "reports"
        if args.output is None and report_root.is_symlink():
            raise ValueError("session report directory may not be a symbolic link")
        output = args.output or report_root / f"report{suffix}"
        if output.exists() and not args.overwrite:
            raise FileExistsError(output)
        write_report(session, output, args.format)
        print(terminal_safe(output))
    elif args.command == "generate":
        _generate(args)
    elif args.command == "convert":
        output = args.output or args.source.with_suffix(".csv" if args.to == "csv" else ".jsonl")
        valid, invalid = convert_source(args.source, output, args.to, args.format, args.overwrite)
        print(
            f"Converted {valid} records ({invalid} invalid) to {terminal_safe(output)}",
            file=sys.stderr,
        )
    elif args.command == "sessions":
        for session in list_sessions(workspace):
            print(
                f"{terminal_safe(session.name)}\t"
                f"{session.manifest.get('valid_record_count', 0)}\t"
                f"{terminal_safe(session.manifest.get('ended_at', ''))}"
            )
    elif args.command == "doctor":
        checks = _doctor(workspace)
        if args.json:
            print(json.dumps(checks, indent=2))
        else:
            doctor_lines: List[str] = []
            for name, value in checks.items():
                status = (
                    "OK"
                    if value
                    else ("OPTIONAL-MISSING" if name.startswith("optional_") else "FAIL")
                )
                doctor_lines.append(f"{status}  {name}")
            print("\n".join(doctor_lines))
        required = [value for name, value in checks.items() if not name.startswith("optional_")]
        return 0 if all(required) else 1
    return 0


def _resolve(source: str, workspace: Path) -> Path:
    path = Path(source)
    return path if path.exists() else workspace / source


def _print_inspection(data: Dict[str, Any], selected: Optional[str], show_quality: bool) -> None:
    print(f"Source: {terminal_safe(data['source'])} ({terminal_safe(data['format'])})")
    print(f"Records: {data['record_count']} valid, {data['invalid_count']} invalid")
    for field in sorted(data["fields"]):
        if selected and field != selected:
            continue
        metric = data["metrics"].get(field)
        unit = f" [{terminal_safe(data['units'][field])}]" if field in data["units"] else ""
        line = f"{terminal_safe(field)}{unit}: {terminal_safe(data['fields'][field])}"
        if metric and metric.get("valid_count"):
            values = metric.get("sparkline_values", [])
            line += (
                f" min={metric['minimum']:.6g} mean={metric['mean']:.6g} "
                f"max={metric['maximum']:.6g} {sparkline(values, _ascii_terminal())}"
            )
        print(line)
    if data["timing"]:
        print(f"Timing: {json.dumps(data['timing'], sort_keys=True)}")
    for category, metrics in sorted(data.get("engineering", {}).items()):
        printable = {
            key: value
            for key, value in metrics.items()
            if key not in {"assumptions", "warnings", "required_fields"}
        }
        print(
            f"{terminal_safe(str(category).title())}: "
            f"{terminal_safe(json.dumps(printable, sort_keys=True))}"
        )
    if show_quality or data["quality"]:
        print(f"Quality findings: {len(data['quality'])}")
        for item in data["quality"]:
            separator = "-" if _ascii_terminal() else "—"
            print(
                f"  {terminal_safe(item['severity'])}: "
                f"{terminal_safe(item['check_id'])} "
                f"{terminal_safe(item.get('field') or '')} {separator} "
                f"{terminal_safe(item['explanation'])}"
            )


def _comparison_output(data: Dict[str, Any], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(data, indent=2, ensure_ascii=False)
    if fmt == "csv":
        lines = [
            "record_type,field,source,valid_count,minimum,maximum,mean,median,"
            "standard_deviation,unit,comparable"
        ]
        for field, detail in data["fields"].items():
            for source, statistics in detail["statistics_by_source"].items():
                lines.append(
                    ",".join(
                        [
                            "metric",
                            _csv(field),
                            _csv(source),
                            str(statistics.get("valid_count")),
                            str(statistics.get("minimum")),
                            str(statistics.get("maximum")),
                            str(statistics.get("mean")),
                            str(statistics.get("median")),
                            str(statistics.get("standard_deviation")),
                            _csv(str(detail["units"].get(source) or "")),
                            str(detail["comparable"]).lower(),
                        ]
                    )
                )
        for warning in data["warnings"]:
            lines.append(
                ",".join(
                    [
                        "warning",
                        _csv(str(warning)),
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                        "",
                    ]
                )
            )
        return "\n".join(lines) + "\n"
    lines = ["# Datary comparison", ""] if fmt == "markdown" else ["Datary comparison"]
    for field, detail in data["fields"].items():
        display_field = markdown_safe(field) if fmt == "markdown" else terminal_safe(field)
        lines.append(f"{'## ' if fmt == 'markdown' else ''}{display_field}")
        for source, value in detail["means"].items():
            statistics = detail["statistics_by_source"][source]
            unit = detail["units"].get(source) or ""
            lines.append(
                (
                    f"- {markdown_safe(source)}: mean `{value}`, median "
                    f"`{statistics.get('median')}`, standard deviation "
                    f"`{statistics.get('standard_deviation')}`, count "
                    f"`{statistics.get('valid_count')}`, unit "
                    f"{markdown_safe(unit or '<unspecified>')}"
                )
                if fmt == "markdown"
                else (
                    f"  {terminal_safe(source)}: mean={value} "
                    f"median={statistics.get('median')} "
                    f"std={statistics.get('standard_deviation')} "
                    f"n={statistics.get('valid_count')} "
                    f"unit={terminal_safe(unit or '<unspecified>')}"
                )
            )
    lines.extend(
        f"Warning: {markdown_safe(warning)}"
        if fmt == "markdown"
        else f"Warning: {terminal_safe(warning)}"
        for warning in data["warnings"]
    )
    return "\n".join(lines)


def _csv(value: str) -> str:
    import io

    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="").writerow([csv_safe_cell(value)])
    return buffer.getvalue()


def _generate(args: argparse.Namespace) -> None:
    records = generate_records(
        args.profile,
        seed=args.seed,
        duration=args.duration,
        sample_rate=args.sample_rate,
        noise=args.noise,
        missing_rate=args.missing_rate,
        duplicate_rate=args.duplicate_rate,
    )
    requested = args.output
    if requested and requested.exists() and not args.overwrite:
        raise FileExistsError(requested)
    if requested and requested.is_symlink():
        raise ValueError("generator output may not be a symbolic link")
    temporary: Optional[Path] = None
    output: IO[str]
    if requested:
        requested.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{requested.name}.generating-",
            dir=str(requested.parent),
        )
        temporary = Path(temporary_name)
        output = os.fdopen(descriptor, "w", encoding="utf-8", newline="")
    else:
        output = sys.stdout
    close = args.output is not None
    completed = False
    try:
        first = True
        fields: List[str] = []
        writer: Optional[csv.DictWriter[str]] = None
        for record in records:
            if args.format == "jsonl":
                output.write(
                    json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
                )
            else:
                if first:
                    fields = list(record)
                    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
                    csv.writer(output, lineterminator="\n").writerow(
                        [csv_safe_cell(field) for field in fields]
                    )
                assert writer is not None
                writer.writerow(record)
            output.flush()
            if args.real_time and not first:
                time.sleep(1 / args.sample_rate)
            first = False
        completed = True
    finally:
        if close:
            output.close()
        if temporary and requested:
            if completed:
                try:
                    os.replace(temporary, requested)
                except OSError:
                    temporary.unlink(missing_ok=True)
                    raise
            else:
                temporary.unlink(missing_ok=True)


def _doctor(workspace: Path) -> Dict[str, bool]:
    python_ok = (3, 9) <= sys.version_info[:2] <= (3, 14)
    workspace.mkdir(parents=True, exist_ok=True)
    writable = _probe_writable(workspace)
    plotting = False
    try:
        matplotlib: Any = importlib.import_module("matplotlib")
        matplotlib.use("Agg", force=True)
        plotting = True
    except (ImportError, RuntimeError):
        pass
    sessions = list_sessions(workspace)
    broken_sessions = False
    try:
        candidates = [
            child
            for child in workspace.iterdir()
            if child.is_dir() and (child / "manifest.json").exists()
        ]
        for candidate in candidates:
            try:
                Session.open(candidate)
            except ValueError:
                broken_sessions = True
    except OSError:
        broken_sessions = True
    integrity = not broken_sessions and all(not session.verify() for session in sessions)
    outputs = all(
        _probe_writable(session.path / directory)
        for session in sessions
        for directory in ("plots", "reports")
    )
    return {
        "python_3_9_through_3_14": python_ok,
        "workspace_writable": writable,
        "session_output_directories_writable": outputs,
        "optional_plotting_available": plotting,
        "session_integrity": integrity,
        f"datary_{__version__}": True,
    }


def _probe_writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=".datary-doctor-", dir=str(directory))
        os.close(descriptor)
        Path(name).unlink()
        return True
    except OSError:
        return False


def _ascii_terminal() -> bool:
    encoding = sys.stdout.encoding or "ascii"
    try:
        "▁—".encode(encoding)
        return False
    except UnicodeEncodeError:
        return True
