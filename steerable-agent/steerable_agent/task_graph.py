"""
TaskGraph: o plano do orquestrador como um DAG persistido. Cada TaskNode
tem um id, descricao, status, dependencias e resultado. O grafo inteiro
serializa/desserializa para JSON em disco (checkpoint.json), permitindo
retomar uma execucao do zero apos reiniciar o processo.

A invariante de seguranca central do projeto vive aqui, nao no replanner:
`apply_diff` recusa qualquer tentativa de remover ou modificar um no que
nao esteja com status "pending". Isso significa que mesmo se o replanner
(uma chamada de LLM, portanto nao confiavel por padrao) devolver um diff
tentando apagar ou reescrever um no "done", a violacao e detectada e
rejeitada aqui - o mesmo principio de "guardrail fora do modelo" dos
projetos irmaos guarded-agent e browser-sandbox.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

PENDING = "pending"
RUNNING = "running"
DONE = "done"
BLOCKED = "blocked"

VALID_STATUSES = {PENDING, RUNNING, DONE, BLOCKED}


class GraphError(Exception):
    pass


@dataclass
class TaskNode:
    id: str
    description: str
    status: str = PENDING
    deps: List[str] = field(default_factory=list)
    result: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status,
            "deps": list(self.deps),
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskNode":
        return cls(
            id=data["id"],
            description=data["description"],
            status=data.get("status", PENDING),
            deps=list(data.get("deps", [])),
            result=data.get("result"),
        )


@dataclass
class DiffApplyResult:
    added: List[str] = field(default_factory=list)
    modified: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    rejected: List[str] = field(default_factory=list)  # mensagens legiveis do motivo

    @property
    def is_noop(self) -> bool:
        return not (self.added or self.modified or self.removed)


class TaskGraph:
    def __init__(self, objective: str, nodes: Optional[Dict[str, TaskNode]] = None):
        self.objective = objective
        self.nodes: Dict[str, TaskNode] = nodes or {}

    # ------------------------------------------------------------------
    # Construcao / consulta
    # ------------------------------------------------------------------
    def add_node(self, node: TaskNode) -> None:
        if node.id in self.nodes:
            raise GraphError(f"id de no duplicado: '{node.id}'")
        self.nodes[node.id] = node

    def get(self, node_id: str) -> Optional[TaskNode]:
        return self.nodes.get(node_id)

    def done_nodes(self) -> List[TaskNode]:
        return [n for n in self.nodes.values() if n.status == DONE]

    def pending_nodes(self) -> List[TaskNode]:
        return [n for n in self.nodes.values() if n.status == PENDING]

    def is_complete(self) -> bool:
        return all(n.status in (DONE, BLOCKED) for n in self.nodes.values())

    def next_ready_node(self) -> Optional[TaskNode]:
        """Primeiro no pending cujas dependencias estao todas done, ou None."""
        for node in self.nodes.values():
            if node.status != PENDING:
                continue
            if all(self.nodes.get(dep) and self.nodes[dep].status == DONE for dep in node.deps):
                return node
        return None

    def is_stuck(self) -> bool:
        """
        True se existem nos pending, nenhum esta pronto pra rodar, e
        nenhum esta rodando no momento - ou seja, o orquestrador nao tem
        mais nada a fazer mas o grafo nao esta completo (deadlock/dep
        invalida). O loop principal usa isso para parar em vez de girar
        para sempre.
        """
        pendings = self.pending_nodes()
        if not pendings:
            return False
        running_exists = any(n.status == RUNNING for n in self.nodes.values())
        return self.next_ready_node() is None and not running_exists

    def mark_blocked_dangling(self) -> List[str]:
        """
        Marca como blocked qualquer no pending cuja dep aponte para um id
        que nao existe mais no grafo (por exemplo, apos um replan remover
        um no do qual outro dependia). Retorna os ids recem-bloqueados.
        """
        newly_blocked = []
        for node in self.pending_nodes():
            missing = [d for d in node.deps if d not in self.nodes]
            if missing:
                node.status = BLOCKED
                node.result = f"bloqueado: dependencia(s) inexistente(s) {missing}"
                newly_blocked.append(node.id)
        return newly_blocked

    # ------------------------------------------------------------------
    # Transicoes de estado (usadas pelo orchestrator)
    # ------------------------------------------------------------------
    def mark_running(self, node_id: str) -> None:
        self.nodes[node_id].status = RUNNING

    def mark_done(self, node_id: str, result: str) -> None:
        node = self.nodes[node_id]
        node.status = DONE
        node.result = result

    # ------------------------------------------------------------------
    # Aplicacao de diff do replanner - a fronteira de seguranca do projeto
    # ------------------------------------------------------------------
    def apply_diff(self, diff: dict) -> DiffApplyResult:
        result = DiffApplyResult()

        remove_pending = diff.get("remove_pending", [])
        modify_pending = diff.get("modify_pending", [])
        add_nodes = diff.get("add_nodes", [])

        # 1. Remocoes: so pending pode ser removido.
        for node_id in remove_pending:
            node = self.nodes.get(node_id)
            if node is None:
                result.rejected.append(f"remove_pending '{node_id}': no nao existe")
                continue
            if node.status != PENDING:
                result.rejected.append(
                    f"remove_pending '{node_id}': recusado - status e '{node.status}', so 'pending' pode ser removido"
                )
                continue
            del self.nodes[node_id]
            result.removed.append(node_id)

        # 2. Adicoes ANTES das modificacoes: deps devem apontar para nos
        # que ja existem (no grafo ou ja adicionados nesta mesma leva de
        # diff), e um modify_pending logo abaixo pode precisar referenciar
        # um id recem-criado aqui (ex: uma tarefa existente que passa a
        # depender de uma tarefa nova).
        known_ids = set(self.nodes.keys())
        for entry in add_nodes:
            new_id = entry.get("id")
            description = entry.get("description")
            deps = list(entry.get("deps", []))

            if not new_id or not description:
                result.rejected.append(f"add_nodes: entrada invalida (faltando id/description): {entry}")
                continue
            if new_id in known_ids:
                result.rejected.append(f"add_nodes '{new_id}': id ja existe no grafo, ignorado")
                continue
            missing_deps = [d for d in deps if d not in known_ids]
            if missing_deps:
                result.rejected.append(
                    f"add_nodes '{new_id}': recusado - deps inexistentes {missing_deps}"
                )
                continue

            self.nodes[new_id] = TaskNode(id=new_id, description=description, status=PENDING, deps=deps)
            known_ids.add(new_id)
            result.added.append(new_id)

        # 3. Modificacoes: description sempre pode mudar; deps tambem pode
        # ser atualizada (ex: para incluir uma dependencia de uma tarefa
        # recem-adicionada acima), desde que aponte para nos existentes e
        # nao introduza um ciclo.
        for entry in modify_pending:
            node_id = entry.get("id")
            node = self.nodes.get(node_id)
            if node is None:
                result.rejected.append(f"modify_pending '{node_id}': no nao existe")
                continue
            if node.status != PENDING:
                result.rejected.append(
                    f"modify_pending '{node_id}': recusado - status e '{node.status}', so 'pending' pode ser modificado"
                )
                continue

            new_deps = entry.get("deps")
            if new_deps is not None:
                missing_deps = [d for d in new_deps if d not in self.nodes]
                if missing_deps:
                    result.rejected.append(
                        f"modify_pending '{node_id}': recusado - novas deps inexistentes {missing_deps}"
                    )
                    continue
                if self._creates_cycle(node_id, new_deps):
                    result.rejected.append(
                        f"modify_pending '{node_id}': recusado - novas deps {new_deps} criariam um ciclo"
                    )
                    continue

            new_description = entry.get("description")
            if not new_description and new_deps is None:
                result.rejected.append(f"modify_pending '{node_id}': nada para alterar, ignorado")
                continue

            if new_description:
                node.description = new_description
            if new_deps is not None:
                node.deps = list(new_deps)
            result.modified.append(node_id)

        # Depois de qualquer remocao, verifica se alguem ficou orfao.
        self.mark_blocked_dangling()

        return result

    def _creates_cycle(self, node_id: str, new_deps: List[str]) -> bool:
        """True se, apos node_id passar a depender de new_deps, node_id se torna alcancavel a partir de si mesmo."""
        visited = set()
        stack = list(new_deps)
        while stack:
            current = stack.pop()
            if current == node_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            current_node = self.nodes.get(current)
            if current_node:
                stack.extend(current_node.deps)
        return False

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "objective": self.objective,
            "nodes": [n.to_dict() for n in self.nodes.values()],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskGraph":
        nodes = {n["id"]: TaskNode.from_dict(n) for n in data["nodes"]}
        return cls(objective=data["objective"], nodes=nodes)

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(path)  # escrita atomica - nunca deixa um checkpoint corrompido pela metade

    @classmethod
    def load(cls, path: Path) -> "TaskGraph":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)
