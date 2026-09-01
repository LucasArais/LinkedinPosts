"""
Camada de apresentacao no terminal, via `rich`. Deliberadamente separada
da logica de orquestracao (orchestrator.py) - nenhuma decisao e tomada
aqui, so renderizacao. Pensada para ficar boa em screenshot/GIF: paineis
com cor por tipo de evento, uma tabela do estado do grafo, e destaque
forte no momento em que uma instrucao injetada chega pela inbox (o
"climax" visual da demo).
"""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .task_graph import BLOCKED, DONE, PENDING, RUNNING, DiffApplyResult, TaskGraph

console = Console()

STATUS_STYLE = {
    PENDING: "grey62",
    RUNNING: "yellow bold",
    DONE: "green bold",
    BLOCKED: "red bold",
}
STATUS_ICON = {
    PENDING: "o",
    RUNNING: ">",
    DONE: "v",
    BLOCKED: "x",
}


def print_banner(objective: str, resuming: bool) -> None:
    console.rule("[bold cyan]steerable-agent[/bold cyan]")
    mode = "[yellow]retomando checkpoint existente[/yellow]" if resuming else "[green]iniciando plano novo[/green]"
    console.print(Panel(f"[bold]Objetivo:[/bold] {objective}\n[bold]Modo:[/bold] {mode}", border_style="cyan"))


def print_graph_table(graph: TaskGraph, title: str = "Estado do grafo") -> None:
    table = Table(title=title, border_style="cyan", show_lines=False)
    table.add_column("", width=2)
    table.add_column("id", style="bold")
    table.add_column("description")
    table.add_column("deps", style="dim")
    table.add_column("status")

    for node in graph.nodes.values():
        style = STATUS_STYLE.get(node.status, "white")
        table.add_row(
            STATUS_ICON.get(node.status, "?"),
            node.id,
            node.description,
            ", ".join(node.deps) or "-",
            Text(node.status, style=style),
        )
    console.print(table)


def print_initial_plan(graph: TaskGraph) -> None:
    console.print(f"\n[bold green]Plano inicial gerado com {len(graph.nodes)} tarefas[/bold green]")
    print_graph_table(graph, title="Plano inicial")


def print_node_start(node) -> None:
    console.print(
        Panel(
            f"[bold yellow]> executando[/bold yellow]  [bold]{node.id}[/bold]: {node.description}\n"
            f"[dim]deps: {', '.join(node.deps) or '(nenhuma)'}[/dim]",
            border_style="yellow",
        )
    )


def print_node_done(node) -> None:
    preview = (node.result or "").strip().replace("\n", " ")
    if len(preview) > 220:
        preview = preview[:220] + "..."
    console.print(
        Panel(
            f"[bold green]v concluido[/bold green]  [bold]{node.id}[/bold]\n[dim]{preview}[/dim]",
            border_style="green",
        )
    )


def print_inbox_instruction(instruction: str, source_file: str) -> None:
    console.print()
    console.rule("[bold magenta]NOVA INSTRUCAO RECEBIDA[/bold magenta]", style="magenta")
    console.print(
        Panel(
            f"[bold]origem:[/bold] {source_file}\n\n[bold white]\"{instruction.strip()}\"[/bold white]",
            title="[magenta]inbox[/magenta]",
            border_style="magenta",
        )
    )


def print_replan_result(result: DiffApplyResult) -> None:
    lines = []
    for node_id in result.added:
        lines.append(f"[green]+ adicionado[/green]  {node_id}")
    for node_id in result.modified:
        lines.append(f"[yellow]~ modificado[/yellow]  {node_id}")
    for node_id in result.removed:
        lines.append(f"[red]- removido[/red]    {node_id}")
    for reason in result.rejected:
        lines.append(f"[bold red]! recusado[/bold red]   {reason}")

    if not lines:
        lines = ["[dim](diff vazio - nenhuma mudanca proposta)[/dim]"]

    console.print(
        Panel("\n".join(lines), title="[magenta]diff aplicado pelo replanner[/magenta]", border_style="magenta")
    )
    console.rule(style="magenta")
    console.print()


def print_stuck(graph: TaskGraph) -> None:
    console.print(
        Panel(
            "O orquestrador nao tem mais nenhuma tarefa pronta para rodar, mas o plano nao "
            "esta completo (provavelmente uma dependencia ficou invalida). Veja os nos "
            "'blocked' abaixo.",
            title="[bold red]EXECUCAO TRAVADA[/bold red]",
            border_style="red",
        )
    )
    print_graph_table(graph, title="Estado final (travado)")


def print_complete(graph: TaskGraph) -> None:
    console.print()
    console.rule("[bold green]PLANO CONCLUIDO[/bold green]", style="green")
    print_graph_table(graph, title="Estado final")
    done = graph.done_nodes()
    if done:
        last = done[-1]
        console.print(
            Panel(
                (last.result or "").strip(),
                title=f"[green]resultado final ({last.id})[/green]",
                border_style="green",
            )
        )
