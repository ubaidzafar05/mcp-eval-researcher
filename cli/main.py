from __future__ import annotations

import json
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from core.config import load_config
from core.identity import check_git_identity
from graph.runtime import GraphRuntime
from main import run_research

app = typer.Typer(add_completion=False, help="Cloud Hive CLI")
console = Console()


@app.command()
def research(
    query: str = typer.Argument(..., help="Research query to execute."),
    judge_provider: str = typer.Option(
        "groq", help="Judge provider: groq, hf, or stub."
    ),
    mcp_mode: str = typer.Option(
        "auto",
        help="MCP mode: auto, transport, inprocess.",
    ),
    mcp_transport: str = typer.Option(
        "stdio",
        help="MCP transport: stdio or streamable-http.",
    ),
    no_interactive: bool = typer.Option(
        False, "--no-interactive", help="Disable interactive HITL prompts."
    ),
    json_output: bool = typer.Option(False, "--json", help="Print JSON output."),
) -> None:
    cfg = load_config(
        {
            "judge_provider": judge_provider,
            "mcp_mode": mcp_mode,
            "mcp_transport": mcp_transport,
            "interactive_hitl": not no_interactive,
        }
    )
    result = run_research(query, config=cfg)
    if json_output:
        console.print(result.model_dump_json(indent=2))
        return

    console.rule(f"Cloud Hive Run {result.run_id}")
    console.print(f"[bold]Status:[/bold] {result.status}")
    console.print(
        f"[bold]Scores:[/bold] faithfulness={result.eval_result.faithfulness:.2f} "
        f"relevancy={result.eval_result.relevancy:.2f} "
        f"citation_coverage={result.eval_result.citation_coverage:.2f}"
    )
    console.print(f"[bold]Artifacts:[/bold] {result.artifacts_path}")
    console.print("\n[bold]Final Report[/bold]\n")
    console.print(result.final_report)


@app.command()
def doctor() -> None:
    cfg = load_config({"interactive_hitl": False})
    with GraphRuntime.from_config(cfg) as runtime:
        probe = runtime.mcp_client.startup_probe()
    identity = check_git_identity(expected_owner=cfg.expected_github_owner)

    table = Table(title="Cloud Hive Doctor")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Python", "3.11.x expected")
    table.add_row("Judge Provider", cfg.judge_provider)
    table.add_row("MCP Mode", cfg.mcp_mode)
    table.add_row("MCP Transport", cfg.mcp_transport)
    table.add_row("Web Endpoint", probe.web_endpoint)
    table.add_row("Local Endpoint", probe.local_endpoint)
    table.add_row("Transport Enabled", str(probe.transport_enabled))
    table.add_row("Transport Active", str(probe.transport_active))
    table.add_row("Fallback Active", str(probe.fallback_active))
    table.add_row("Fallback Reason", probe.fallback_reason or "none")
    table.add_row(
        "HTTP Token Ready",
        str(bool(cfg.mcp_auth_token or cfg.mcp_allow_insecure_http)),
    )
    table.add_row("Groq Key Present", str(bool(cfg.groq_api_key)))
    table.add_row("Tavily Key Present", str(bool(cfg.tavily_api_key)))
    table.add_row("Firecrawl Key Present", str(bool(cfg.firecrawl_api_key)))
    table.add_row("LangSmith Key Present", str(bool(cfg.langsmith_api_key)))
    table.add_row("Web MCP Healthy", str(probe.web_healthy))
    table.add_row("Local MCP Healthy", str(probe.local_healthy))
    table.add_row("Output Dir", cfg.output_dir)
    table.add_row("Memory Dir", cfg.memory_dir)
    table.add_row("Metrics Enabled", str(cfg.metrics_enabled))
    table.add_row("Metrics Host:Port", f"{cfg.metrics_host}:{cfg.metrics_port}")
    table.add_row("Identity OK", str(identity.ok))
    table.add_row("Git User", identity.user_name or "unset")
    table.add_row("Git Email", identity.user_email or "unset")
    table.add_row("Origin Owner", identity.owner or "unset")
    console.print(table)
    if identity.reasons:
        console.print("\n[bold yellow]Identity warnings[/bold yellow]")
        for reason in identity.reasons:
            console.print(f"- {reason}")


@app.command()
def eval(run_id: str = typer.Option(..., help="Run id to inspect eval artifacts.")) -> None:
    eval_path = Path("outputs") / run_id / "eval.json"
    if not eval_path.exists():
        raise typer.BadParameter(f"Could not find eval artifact at {eval_path}")
    data = json.loads(eval_path.read_text(encoding="utf-8"))
    table = Table(title=f"Eval Summary - {run_id}")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("faithfulness", str(data.get("faithfulness")))
    table.add_row("relevancy", str(data.get("relevancy")))
    table.add_row("citation_coverage", str(data.get("citation_coverage")))
    table.add_row("pass_gate", str(data.get("pass_gate")))
    table.add_row("reasons", ", ".join(data.get("reasons", [])))
    console.print(table)


@app.command()
def stress(
    suite: str = typer.Option("basic", help="Stress suite name."),
    iterations: int = typer.Option(5, min=1, max=50),
) -> None:
    queries = [
        "Latest trends in edge AI model serving",
        "Compare tavily and duckduckgo for LLM retrieval",
        "How to handle LLM free-tier rate limits robustly",
        "Key risks in autonomous research agents",
        "Best practices for citation quality checks",
    ]
    if suite != "basic":
        queries.append("API documentation crawling strategy with firecrawl")

    cfg = load_config({"interactive_hitl": False})
    durations: list[float] = []
    completed = 0
    for i in range(iterations):
        query = queries[i % len(queries)]
        start = time.perf_counter()
        result = run_research(query, config=cfg)
        elapsed = time.perf_counter() - start
        durations.append(elapsed)
        if result.status != "aborted":
            completed += 1

    p50 = sorted(durations)[len(durations) // 2]
    success_rate = completed / max(1, iterations)
    table = Table(title="Stress Summary")
    table.add_column("Metric")
    table.add_column("Value")
    table.add_row("iterations", str(iterations))
    table.add_row("success_rate", f"{success_rate:.2%}")
    table.add_row("p50_latency_sec", f"{p50:.2f}")
    table.add_row("target_p50_sec", "<= 30")
    console.print(table)


def main() -> None:
    app()
