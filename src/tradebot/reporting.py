"""Write reproducible local backtest artifacts."""

import csv
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4


def implementation_sha256() -> str:
    digest = hashlib.sha256()
    for source in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(source.name.encode())
        digest.update(b"\x00")
        digest.update(hashlib.sha256(source.read_bytes()).digest())
    return digest.hexdigest()


def write_run(
    config, result, start, end, *, model_evidence: dict | None = None
) -> Path:
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{uuid4().hex}"
    directory = config.output_dir / run_id
    directory.mkdir(parents=True)
    peak = result.starting_equity
    drawdown = 0
    monthly_equity = {}
    for point in result.equity_curve:
        peak = max(peak, point.equity)
        drawdown = max(drawdown, (peak - point.equity) / peak)
        month = (point.timestamp - timedelta(microseconds=1)).strftime("%Y-%m")
        monthly_equity[month] = point.equity
    prior_equity = result.starting_equity
    monthly_returns = {}
    for month, equity in monthly_equity.items():
        monthly_returns[month] = equity / prior_equity - 1 if prior_equity > 0 else None
        prior_equity = equity
    wins = [trade.net_pnl for trade in result.trades if trade.net_pnl > 0]
    losses = [-trade.net_pnl for trade in result.trades if trade.net_pnl < 0]
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "start": start,
        "end_exclusive": end,
        "configuration": config.model_dump(mode="json"),
        "implementation_sha256": implementation_sha256(),
        "funding_missing_mark_model": "uses_mark_minute_open",
        "python": sys.version,
        "dataset_manifest_sha256": hashlib.sha256(
            config.dataset.manifest.read_bytes()
        ).hexdigest(),
        "metadata_sha256": hashlib.sha256(
            config.dataset.metadata.read_bytes()
        ).hexdigest(),
        "starting_equity": result.starting_equity,
        "ending_equity": result.ending_equity,
        "net_return": result.ending_equity / result.starting_equity - 1,
        "monthly_net_returns": monthly_returns,
        "max_drawdown": drawdown,
        "closed_trades": len(result.trades),
        "win_rate": len(wins) / len(result.trades) if result.trades else None,
        "average_win": sum(wins) / len(wins) if wins else None,
        "average_loss": sum(losses) / len(losses) if losses else None,
        "profit_factor": sum(wins) / sum(losses) if losses else None,
        "total_fees": sum(trade.entry_fee + trade.exit_fee for trade in result.trades),
        "total_funding": sum(trade.funding for trade in result.trades),
        "turnover_usdt": sum(
            trade.plan.quantity * (trade.plan.entry_price + trade.exit_price)
            for trade in result.trades
        ),
        "exposure_fraction": sum(point.exposed for point in result.equity_curve)
        / max(1, len(result.equity_curve)),
        "entry_rejections": result.rejections,
        "daily_overshoots": result.daily_overshoots,
        "liquidations": result.liquidations,
        "invalid_intents": result.invalid_intents,
    }
    if config.dataset.public_api_report is not None:
        summary["public_api_report_sha256"] = hashlib.sha256(
            config.dataset.public_api_report.read_bytes()
        ).hexdigest()
    if model_evidence is not None:
        summary["model_evidence"] = model_evidence
    with (directory / "equity.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["timestamp", "equity", "exposed"])
        for point in result.equity_curve:
            writer.writerow([point.timestamp.isoformat(), point.equity, point.exposed])
    (directory / "trades.json").write_text(
        json.dumps([asdict(trade) for trade in result.trades], default=str, indent=2),
        encoding="utf-8",
    )
    (directory / "summary.json").write_text(
        json.dumps(summary, default=str, indent=2) + "\n", encoding="utf-8"
    )
    return directory
