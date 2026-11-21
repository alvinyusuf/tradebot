"""Command-line entry points for local research and evidence review."""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Literal

import typer

from .config import read_config

app = typer.Typer(no_args_is_help=True)
data_app = typer.Typer(no_args_is_help=True)
paper_app = typer.Typer(no_args_is_help=True)
demo_app = typer.Typer(no_args_is_help=True)
app.add_typer(data_app, name="data")
app.add_typer(paper_app, name="paper")
app.add_typer(demo_app, name="demo")


@data_app.command("audit")
def data_audit(
    manifest_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)] = Path(
        "data/audit/manifest.json"
    ),
    public_api_report: Annotated[
        Path | None, typer.Option(exists=True, dir_okay=False)
    ] = None,
) -> None:
    """Summarize existing archival evidence."""
    from .market_data import ArchiveDataset

    try:
        manifest = json.loads(manifest_path.read_bytes())
        dataset = ArchiveDataset(manifest_path, public_api_report=public_api_report)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        typer.echo(f"Bukti audit tidak valid: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    archives = manifest["archives"]
    errors = [entry["source"] for entry in archives if "error" in entry]
    unresolved = dataset.unrepaired_minutes()
    report = {
        "archives_checked": len(archives),
        "archive_errors": errors,
        "unresolved_candles_utc_ms": unresolved,
        "funding_interval_discrepancies": manifest["funding_interval_discrepancies"],
        "funding_timing": dataset.funding_timing,
        "rest_funding_marks_missing": dataset.missing_rest_funding_marks,
        "contract_metadata": manifest["contract_metadata"],
    }
    typer.echo(json.dumps(report, indent=2))
    if (
        errors
        or unresolved
        or report["funding_interval_discrepancies"]
        or dataset.funding_timing != "rest_settlement"
    ):
        raise typer.Exit(code=1)


@data_app.command("curate")
def data_curate(
    manifest_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    output: Annotated[Path, typer.Argument(dir_okay=False)],
    start: Annotated[str, typer.Option()],
    end: Annotated[str, typer.Option()],
    public_api_report: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
) -> None:
    """Publish a validated interval as immutable Parquet."""
    from .market_data import ArchiveDataset

    try:
        dataset = ArchiveDataset(manifest_path, public_api_report=public_api_report)
        checksum = dataset.export_parquet(
            output, datetime.fromisoformat(start), datetime.fromisoformat(end)
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        typer.echo(f"Kurasi gagal: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"{checksum}  {output}")


@app.command("check-config")
def check_config(
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    mode: Annotated[str, typer.Option()] = "backtest",
) -> None:
    """Validate a versioned local config without creating a run."""
    try:
        config = read_config(path, expected_mode=mode)
    except (OSError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Konfigurasi {config.mode} v{config.schema_version} valid")


@app.command()
def backtest(
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    fold: Annotated[int, typer.Option(min=1, max=3)] = 1,
    split: Annotated[
        Literal["train", "validation", "test"], typer.Option()
    ] = "validation",
    final_training: Annotated[
        Path | None, typer.Option(exists=True, dir_okay=False)
    ] = None,
    frozen_sha256: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Evaluate the baseline on one research split."""
    from .experiment import check_holdout
    from .reporting import write_run
    from .research import run_baseline

    try:
        config = read_config(path, expected_mode="backtest")
        partition = fold
        if final_training is not None:
            check_holdout(config, final_training, frozen_sha256)
            partition, split = None, "test"
        elif frozen_sha256 is not None:
            raise ValueError("Hash final memerlukan artifact training final")
        result, start, end = run_baseline(config, partition, split)
        output = write_run(config, result, start, end)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        typer.echo(f"Backtest gagal: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(str(output))


@app.command()
def report(
    run: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
) -> None:
    """Show the summary of a completed local run."""
    try:
        typer.echo((run / "summary.json").read_text(encoding="utf-8"))
    except OSError as exc:
        typer.echo(f"Laporan gagal dibaca: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command("gate")
def review_gate(
    evidence: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """Evaluate local Gate B or paper Gate C evidence."""
    from .gate_report import load_gate_report

    try:
        report = load_gate_report(evidence)
    except (OSError, ValueError, TypeError) as exc:
        typer.echo(f"Bukti gate tidak valid: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(report, indent=2))
    if report["status"] != "pass":
        raise typer.Exit(code=1)


@app.command()
def train(
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    fold: Annotated[int, typer.Option(min=1, max=3)] = 1,
    final: Annotated[bool, typer.Option()] = False,
    development_index: Annotated[
        list[Path] | None, typer.Option(exists=True, dir_okay=False)
    ] = None,
) -> None:
    """Train the fixed PPO experiment on one research partition."""
    from .experiment import train_experiment

    try:
        config = read_config(path, expected_mode="train")
        if development_index and not final:
            raise ValueError("Bukti pengembangan hanya digunakan untuk training final")
        output = train_experiment(
            config,
            None if final else fold,
            development_indexes=tuple(development_index or ()),
        )
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        typer.echo(f"Training gagal: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(str(output))


@app.command()
def evaluate(
    path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    fold: Annotated[int, typer.Option(min=1, max=3)] = 1,
    frozen_sha256: Annotated[
        str | None, typer.Option(help="Frozen final training manifest SHA-256")
    ] = None,
) -> None:
    """Evaluate selected local PPO models on one research test split."""
    from .experiment import evaluate_experiment

    try:
        config = read_config(path, expected_mode="evaluate")
        runs = evaluate_experiment(
            config,
            None if frozen_sha256 is not None else fold,
            frozen_training_sha256=frozen_sha256,
        )
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        typer.echo(f"Evaluasi gagal: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(runs, indent=2))


@paper_app.command("probe")
def paper_probe(
    start: Annotated[str, typer.Argument(help="UTC minute cursor in ISO-8601")],
    max_minutes: Annotated[int, typer.Option(min=1, max=499)] = 5,
) -> None:
    """Check the public paper feed and show market readiness."""
    from dataclasses import asdict

    from .paper import BinancePaperFeed, PaperFeedError

    try:
        feed = BinancePaperFeed(datetime.fromisoformat(start))
        batch = feed.poll(max_minutes=max_minutes)
    except (ValueError, PaperFeedError) as exc:
        typer.echo(f"Probe paper gagal: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            {
                "ready": feed.ready,
                "cursor": feed.cursor,
                "closed_minutes": len(batch.minutes),
                "snapshot": asdict(batch.snapshot),
            },
            default=str,
            indent=2,
        )
    )
    if not feed.ready:
        raise typer.Exit(code=1)


@paper_app.command("check-model")
def paper_check_model(
    directory: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    seed: Annotated[int, typer.Option()],
    frozen_sha256: Annotated[str, typer.Option()],
) -> None:
    """Verify and load a trusted local PPO artifact on CPU."""
    try:
        from .paper_policy import FrozenPaperPolicy

        policy = FrozenPaperPolicy.load(
            directory, seed=seed, training_sha256=frozen_sha256
        )
    except (OSError, ValueError, KeyError, TypeError, ImportError) as exc:
        typer.echo(f"Artifact paper gagal divalidasi: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(policy.model_id)


@paper_app.command("report")
def paper_report(
    journal: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    utc_day: Annotated[str, typer.Option(help="UTC date in YYYY-MM-DD")],
    model_id: Annotated[str, typer.Option()],
    config_id: Annotated[str, typer.Option()],
) -> None:
    """Summarize observed paper equity and runtime events for a UTC date."""
    import sqlite3

    from .paper_audit import PaperAuditLog

    try:
        summary = PaperAuditLog(journal).daily(
            date.fromisoformat(utc_day), model_id=model_id, config_id=config_id
        )
    except (OSError, ValueError, sqlite3.Error) as exc:
        typer.echo(f"Laporan paper gagal: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(summary, indent=2))


@paper_app.command("backup")
def paper_backup(
    state: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    destination: Annotated[Path, typer.Argument(dir_okay=False)],
) -> None:
    """Create a consistent backup of the paper SQLite store."""
    import sqlite3

    from .paper_state import PaperStateStore

    try:
        PaperStateStore(state).backup(destination)
    except (OSError, ValueError, sqlite3.Error) as exc:
        typer.echo(f"Backup paper gagal: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(str(destination))


@demo_app.command("metadata")
def demo_metadata(
    output: Annotated[Path, typer.Argument(dir_okay=False)],
    env_file: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
) -> None:
    """Collect read-only evidence for the Binance Futures demo account."""
    from .demo_credentials import demo_credentials
    from .demo_metadata import fetch_demo_metadata

    try:
        evidence = fetch_demo_metadata(*demo_credentials(env_file))
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(evidence, stream, indent=2)
            stream.write("\n")
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as exc:
        typer.echo(f"Audit metadata demo gagal: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(str(output))


@demo_app.command("preflight")
def demo_check_public(
    output: Annotated[Path | None, typer.Option(dir_okay=False)] = None,
) -> None:
    """Check closed market candles, quote freshness, and the Demo server clock."""
    from .demo_preflight import demo_preflight

    report = demo_preflight()
    payload = json.dumps(report, indent=2)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            stream.write(payload + "\n")
    typer.echo(payload)
    if not report["ready"]:
        raise typer.Exit(code=1)


@demo_app.command("validate-order")
def demo_validate_order(
    side: Annotated[Literal["BUY", "SELL"], typer.Option()],
    quantity: Annotated[str, typer.Option()],
    env_file: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
) -> None:
    """Send a signed validation request to the Demo test-order endpoint."""
    from decimal import Decimal
    from uuid import uuid4

    from .demo_credentials import demo_credentials
    from .demo_execution import DemoAPIError, DemoExecution, DemoRequestUncertain

    try:
        client = DemoExecution(*demo_credentials(env_file))
        client.test_market_order(
            side=side,
            quantity=Decimal(quantity),
            client_id=f"tbtest-{uuid4().hex[:20]}",
        )
    except (
        OSError,
        ArithmeticError,
        ValueError,
        DemoAPIError,
        DemoRequestUncertain,
    ) as exc:
        typer.echo(f"Validasi order demo gagal: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo("Validasi request Demo diterima di endpoint test order")


@demo_app.command("check-account")
def demo_check_account(
    env_file: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
) -> None:
    """Verify Demo account setup with signed read-only requests."""
    from dataclasses import asdict

    from .demo_account import inspect_demo_account
    from .demo_credentials import demo_credentials
    from .demo_execution import DemoAPIError, DemoExecution, DemoRequestUncertain

    try:
        state = inspect_demo_account(DemoExecution(*demo_credentials(env_file)))
    except (OSError, ValueError, DemoAPIError, DemoRequestUncertain) as exc:
        typer.echo(f"Pemeriksaan akun Demo gagal: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(
        json.dumps(
            asdict(state) | {"ready": state.ready, "violations": state.violations},
            indent=2,
        )
    )
    if not state.ready:
        raise typer.Exit(code=1)


@app.command()
def reconcile(
    journal: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
) -> None:
    """List local orders that still need authoritative reconciliation."""
    from dataclasses import asdict

    from .reconciliation import OrderJournal

    orders = OrderJournal(journal).unresolved()
    typer.echo(json.dumps([asdict(order) for order in orders], indent=2))
    if orders:
        raise typer.Exit(code=1)
