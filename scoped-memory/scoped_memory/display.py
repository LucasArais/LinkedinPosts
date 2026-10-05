"""Apresentacao no terminal (rich) - sem logica de decisao, so renderizacao."""

from typing import List, Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from .store import Memory

console = Console()

HELP = (
    "[bold]/user <nome>[/bold]  troca o usuario ativo\n"
    "[bold]/team <nome>[/bold]  define o time do usuario ativo ([dim]/team -[/dim] remove)\n"
    "[bold]/whoami[/bold]       mostra usuario/time ativo\n"
    "[bold]/memories[/bold]     lista as memorias visiveis pro usuario ativo\n"
    "[bold]/help[/bold]         esta ajuda   [bold]/quit[/bold] sai\n"
    "qualquer outra linha e uma mensagem pro agente"
)


def print_banner(model: str, db_path: str) -> None:
    console.rule("[bold cyan]scoped-memory[/bold cyan]")
    console.print(Panel(f"{HELP}\n\n[dim]modelo: {model} | banco: {db_path}[/dim]", border_style="cyan"))


def prompt_label(user_id: Optional[str], team_id: Optional[str]) -> str:
    if user_id is None:
        return "[dim](sem usuario)[/dim] > "
    team = f"[magenta]@{team_id}[/magenta]" if team_id else ""
    return f"[bold green]{user_id}[/bold green]{team} > "


def print_whoami(user_id: Optional[str], team_id: Optional[str]) -> None:
    if user_id is None:
        console.print("[yellow]nenhum usuario ativo - use /user <nome>[/yellow]")
        return
    console.print(f"usuario: [bold green]{user_id}[/bold green] | time: [magenta]{team_id or '(nenhum)'}[/magenta]")


def print_memories(user_id: str, team_id: Optional[str], memories: List[Memory]) -> None:
    title = f"memorias visiveis para {user_id}" + (f" @ {team_id}" if team_id else "")
    if not memories:
        console.print(f"[dim]{title}: nenhuma[/dim]")
        return
    table = Table(title=title, border_style="blue")
    table.add_column("id", justify="right")
    table.add_column("escopo")
    table.add_column("conteudo")
    table.add_column("criada em", style="dim")
    for m in memories:
        scope = f"[green]user:{m.scope_id}[/green]" if m.scope_type == "user" else f"[magenta]team:{m.scope_id}[/magenta]"
        table.add_row(str(m.id), scope, m.content, m.created_at)
    console.print(table)


def print_turn(reply: str, used: List[Memory], saved: Optional[dict]) -> None:
    if used:
        console.print(f"[dim]  ↳ {len(used)} memoria(s) injetada(s) no contexto[/dim]")
    console.print(Panel(Markdown(reply), title="agente", border_style="yellow", title_align="left"))
    if saved:
        color = "magenta" if saved["scope"] == "team" else "green"
        console.print(f"[{color}]  ✚ memoria gravada ({saved['scope']}): {saved['content']}[/{color}]")


def print_error(msg: str) -> None:
    console.print(f"[bold red]ERRO:[/bold red] {msg}")
