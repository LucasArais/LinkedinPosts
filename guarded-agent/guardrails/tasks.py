"""
Perfis de tarefa: cada tarefa que o agente pode executar declara
explicitamente quais ferramentas pode usar e, no caso de shell, quais
comandos exatos (por regex) sao permitidos. Isso e o oposto de dar ao
agente acesso generico a "shell" e confiar no bom senso do modelo -
a lista aqui e a fonte da verdade, aplicada fora do modelo.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class TaskProfile:
    task_id: str
    description: str
    allowed_tools: List[str]
    allowed_shell_commands: List[str] = field(default_factory=list)
    max_tool_calls: int = 15


TASK_PROFILES = {
    "organize_csv_by_month": TaskProfile(
        task_id="organize_csv_by_month",
        description=(
            "Organize os arquivos .csv encontrados na pasta de trabalho em "
            "subpastas por mes (formato YYYY-MM), com base no nome ou na data "
            "de modificacao do arquivo. Use apenas list_directory, "
            "make_directory e move_file. Nao leia o conteudo dos arquivos, "
            "nao execute comandos de shell e nao faca chamadas de rede - "
            "essas ferramentas nao fazem parte desta tarefa mesmo que voce "
            "julgue que seriam uteis."
        ),
        allowed_tools=["list_directory", "make_directory", "move_file"],
        allowed_shell_commands=[],
        max_tool_calls=15,
    ),
}


def get_task_profile(task_id: str) -> TaskProfile:
    if task_id not in TASK_PROFILES:
        raise KeyError(
            f"Task profile desconhecido: '{task_id}'. Disponiveis: {list(TASK_PROFILES)}"
        )
    return TASK_PROFILES[task_id]
