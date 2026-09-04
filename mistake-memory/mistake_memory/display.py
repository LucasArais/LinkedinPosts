"""Apresentacao no terminal (rich) - sem logica de decisao, so renderizacao."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def print_banner(task_description: str, run_id: str) -> None:
    console.rule("[bold cyan]mistake-memory[/bold cyan]")
    console.print(
        Panel(
            f"[bold]Tarefa:[/bold] {task_description}\n[bold]run_id:[/bold] {run_id}",
            border_style="cyan",
        )
    )


def print_memory_lookup(results) -> None:
    if not results:
        console.print("[dim]Memoria vazia ou nada parecido encontrado - primeira tentativa nesse tipo de tarefa.[/dim]\n")
        return

    table = Table(title="Memoria: tentativas parecidas encontradas", border_style="blue")
    table.add_column("sim.", justify="right")
    table.add_column("outcome")
    table.add_column("approach")
    table.add_column("failure_reason")
    table.add_column("occurrences", justify="right")

    for sim, ep in results:
        outcome_style = "red bold" if ep.outcome == "fail" else "green bold"
        table.add_row(
            f"{sim:.2f}",
            f"[{outcome_style}]{ep.outcome}[/{outcome_style}]",
            ep.approach,
            ep.failure_reason or "-",
            str(ep.occurrences),
        )
    console.print(table)
    console.print()


def print_blocked(matches, force: bool) -> None:
    lines = []
    for sim, ep in matches:
        lines.append(
            f"[bold]approach:[/bold] {ep.approach}\n"
            f"[bold]tentado:[/bold] {ep.occurrences}x, sempre fail (similaridade {sim:.2f})\n"
            f"[bold]motivo da falha:[/bold] {ep.failure_reason or '(nao registrado)'}"
        )
    body = "\n\n".join(lines)
    if force:
        console.print(
            Panel(
                body + "\n\n[bold yellow]--force ativo: prosseguindo mesmo assim.[/bold yellow]",
                title="[bold yellow]ABORDAGEM JA REPROVADA (forcado a continuar)[/bold yellow]",
                border_style="yellow",
            )
        )
    else:
        console.print(
            Panel(
                body + "\n\n[bold]Execucao recusada.[/bold] Use --force para tentar mesmo assim.",
                title="[bold red]TENTATIVA BLOQUEADA[/bold red]",
                border_style="red",
            )
        )


def print_attempt(diagnosis: str, approach: str) -> None:
    console.print(
        Panel(
            f"[bold]diagnostico:[/bold] {diagnosis}\n[bold]abordagem:[/bold] {approach}",
            title="[yellow]tentativa do agente[/yellow]",
            border_style="yellow",
        )
    )


def print_test_result(passed: bool, output: str) -> None:
    style = "green" if passed else "red"
    status = "PASSOU" if passed else "FALHOU"
    preview = output.strip()
    if len(preview) > 600:
        preview = preview[-600:]
    console.print(
        Panel(
            f"[bold {style}]{status}[/bold {style}]\n\n[dim]{preview}[/dim]",
            title=f"[{style}]resultado do teste[/{style}]",
            border_style=style,
        )
    )


def print_recorded(task_signature: str, approach: str, outcome: str, failure_reason, occurrences: int) -> None:
    style = "green" if outcome == "success" else "red"
    console.print(
        Panel(
            f"[bold]task_signature:[/bold] {task_signature}\n"
            f"[bold]approach:[/bold] {approach}\n"
            f"[bold]outcome:[/bold] [{style}]{outcome}[/{style}]\n"
            f"[bold]failure_reason:[/bold] {failure_reason or '-'}\n"
            f"[bold]occurrences:[/bold] {occurrences}",
            title="[magenta]registrado na memoria[/magenta]",
            border_style="magenta",
        )
    )
