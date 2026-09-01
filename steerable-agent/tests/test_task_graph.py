"""
Testes deterministicos do TaskGraph - sem chamada de API, sem rede. O foco
e a invariante de seguranca central do projeto: um diff de replan nunca
pode alterar ou remover um no 'done', mesmo que tente.
"""

import json

import pytest

from steerable_agent.task_graph import BLOCKED, DONE, PENDING, RUNNING, GraphError, TaskGraph, TaskNode


def _graph_with_two_nodes(status_a=PENDING, status_b=PENDING):
    g = TaskGraph(objective="objetivo de teste")
    g.add_node(TaskNode(id="a", description="tarefa a", status=status_a, deps=[]))
    g.add_node(TaskNode(id="b", description="tarefa b", status=status_b, deps=["a"]))
    return g


# ---------------------------------------------------------------------------
# construcao / navegacao basica
# ---------------------------------------------------------------------------


def test_add_duplicate_id_raises():
    g = TaskGraph(objective="x")
    g.add_node(TaskNode(id="a", description="d"))
    with pytest.raises(GraphError):
        g.add_node(TaskNode(id="a", description="outra"))


def test_next_ready_node_respects_deps():
    g = _graph_with_two_nodes()
    ready = g.next_ready_node()
    assert ready.id == "a"  # b depende de a, que ainda nao esta done


def test_next_ready_node_after_dep_done():
    g = _graph_with_two_nodes(status_a=DONE)
    ready = g.next_ready_node()
    assert ready.id == "b"


def test_is_complete_true_only_when_all_done_or_blocked():
    g = _graph_with_two_nodes(status_a=DONE, status_b=DONE)
    assert g.is_complete()
    g2 = _graph_with_two_nodes(status_a=DONE, status_b=PENDING)
    assert not g2.is_complete()


def test_is_stuck_detects_deadlock():
    # 'b' depende de 'c', que nao existe no grafo - fica pending para sempre
    g = TaskGraph(objective="x")
    g.add_node(TaskNode(id="b", description="d", deps=["c"]))
    assert g.is_stuck()


def test_mark_blocked_dangling():
    g = TaskGraph(objective="x")
    g.add_node(TaskNode(id="b", description="d", deps=["c"]))
    blocked = g.mark_blocked_dangling()
    assert blocked == ["b"]
    assert g.nodes["b"].status == BLOCKED


# ---------------------------------------------------------------------------
# apply_diff - a invariante de seguranca central
# ---------------------------------------------------------------------------


def test_diff_removes_pending_node():
    g = _graph_with_two_nodes()
    result = g.apply_diff({"remove_pending": ["b"], "modify_pending": [], "add_nodes": []})
    assert result.removed == ["b"]
    assert "b" not in g.nodes


def test_diff_cannot_remove_done_node():
    g = _graph_with_two_nodes(status_a=DONE)
    result = g.apply_diff({"remove_pending": ["a"], "modify_pending": [], "add_nodes": []})
    assert result.removed == []
    assert len(result.rejected) == 1
    assert "a" in g.nodes  # continua la, intocado
    assert g.nodes["a"].status == DONE


def test_diff_cannot_remove_running_node():
    g = _graph_with_two_nodes(status_a=RUNNING)
    result = g.apply_diff({"remove_pending": ["a"], "modify_pending": [], "add_nodes": []})
    assert result.removed == []
    assert result.rejected
    assert g.nodes["a"].status == RUNNING


def test_diff_modifies_pending_description():
    g = _graph_with_two_nodes()
    result = g.apply_diff(
        {"remove_pending": [], "modify_pending": [{"id": "b", "description": "nova descricao"}], "add_nodes": []}
    )
    assert result.modified == ["b"]
    assert g.nodes["b"].description == "nova descricao"


def test_diff_cannot_modify_done_node():
    g = _graph_with_two_nodes(status_a=DONE)
    original_description = g.nodes["a"].description
    result = g.apply_diff(
        {"remove_pending": [], "modify_pending": [{"id": "a", "description": "tentativa de reescrever"}], "add_nodes": []}
    )
    assert result.modified == []
    assert len(result.rejected) == 1
    assert g.nodes["a"].description == original_description
    assert g.nodes["a"].status == DONE


def test_diff_adds_node_with_valid_deps():
    g = _graph_with_two_nodes()
    result = g.apply_diff(
        {"remove_pending": [], "modify_pending": [], "add_nodes": [{"id": "c", "description": "nova tarefa", "deps": ["a"]}]}
    )
    assert result.added == ["c"]
    assert g.nodes["c"].deps == ["a"]
    assert g.nodes["c"].status == PENDING


def test_diff_add_node_rejects_missing_deps():
    g = _graph_with_two_nodes()
    result = g.apply_diff(
        {"remove_pending": [], "modify_pending": [], "add_nodes": [{"id": "c", "description": "d", "deps": ["nao-existe"]}]}
    )
    assert result.added == []
    assert result.rejected
    assert "c" not in g.nodes


def test_diff_add_node_allows_chained_deps_within_same_diff():
    g = _graph_with_two_nodes()
    diff = {
        "remove_pending": [],
        "modify_pending": [],
        "add_nodes": [
            {"id": "c", "description": "c", "deps": ["a"]},
            {"id": "d", "description": "d", "deps": ["c"]},  # depende de um no adicionado no MESMO diff
        ],
    }
    result = g.apply_diff(diff)
    assert set(result.added) == {"c", "d"}
    assert g.nodes["d"].deps == ["c"]


def test_diff_rejects_duplicate_id():
    g = _graph_with_two_nodes()
    result = g.apply_diff(
        {"remove_pending": [], "modify_pending": [], "add_nodes": [{"id": "a", "description": "d", "deps": []}]}
    )
    assert result.added == []
    assert result.rejected


def test_diff_modify_pending_can_add_new_dependency():
    """
    Regressao de um bug real encontrado ao vivo: o replanner adicionava uma
    tarefa nova e so atualizava a description de uma tarefa existente pra
    mencionar ela, sem atualizar as deps - a tarefa existente rodava sem
    esperar pela nova, porque 'esperar' so existe via deps, nao via texto.
    """
    g = TaskGraph(objective="x")
    g.add_node(TaskNode(id="a", description="pesquisa A", status=DONE, result="dados de A"))
    g.add_node(TaskNode(id="b", description="pesquisa B", status=DONE, result="dados de B"))
    g.add_node(TaskNode(id="comparativo", description="compara A e B", deps=["a", "b"]))
    diff = {
        "remove_pending": [],
        "modify_pending": [
            {"id": "comparativo", "description": "compara A, B e C", "deps": ["a", "b", "c"]}
        ],
        "add_nodes": [{"id": "c", "description": "pesquisa C", "deps": []}],
    }
    result = g.apply_diff(diff)
    assert "c" in result.added
    assert "comparativo" in result.modified
    assert g.nodes["comparativo"].deps == ["a", "b", "c"]
    assert g.nodes["comparativo"].description == "compara A, B e C"


def test_diff_modify_pending_rejects_deps_creating_cycle():
    g = TaskGraph(objective="x")
    g.add_node(TaskNode(id="a", description="a", deps=[]))
    g.add_node(TaskNode(id="b", description="b", deps=["a"]))
    # tentando fazer 'a' depender de 'b', que ja depende de 'a' -> ciclo
    result = g.apply_diff(
        {"remove_pending": [], "modify_pending": [{"id": "a", "description": "a", "deps": ["b"]}], "add_nodes": []}
    )
    assert result.modified == []
    assert result.rejected
    assert g.nodes["a"].deps == []


def test_diff_modify_pending_rejects_missing_deps():
    g = _graph_with_two_nodes()
    result = g.apply_diff(
        {"remove_pending": [], "modify_pending": [{"id": "b", "description": "b", "deps": ["nao-existe"]}], "add_nodes": []}
    )
    assert result.modified == []
    assert result.rejected


def test_diff_modify_pending_deps_on_done_node_still_rejects_whole_op():
    g = _graph_with_two_nodes(status_a=DONE)
    result = g.apply_diff(
        {"remove_pending": [], "modify_pending": [{"id": "a", "description": "x", "deps": []}], "add_nodes": []}
    )
    assert result.modified == []
    assert result.rejected
    assert g.nodes["a"].status == DONE


def test_diff_removing_dep_blocks_dependents():
    g = _graph_with_two_nodes()  # b depende de a
    result = g.apply_diff({"remove_pending": ["a"], "modify_pending": [], "add_nodes": []})
    assert result.removed == ["a"]
    assert g.nodes["b"].status == BLOCKED  # dependencia sumiu, fica bloqueado em vez de travar silenciosamente


# ---------------------------------------------------------------------------
# serializacao
# ---------------------------------------------------------------------------


def test_save_and_load_roundtrip(tmp_path):
    g = _graph_with_two_nodes(status_a=DONE)
    g.nodes["a"].result = "resultado da tarefa a"
    path = tmp_path / "checkpoint.json"
    g.save(path)

    loaded = TaskGraph.load(path)
    assert loaded.objective == g.objective
    assert loaded.nodes["a"].status == DONE
    assert loaded.nodes["a"].result == "resultado da tarefa a"
    assert loaded.nodes["b"].deps == ["a"]


def test_save_is_valid_json(tmp_path):
    g = _graph_with_two_nodes()
    path = tmp_path / "checkpoint.json"
    g.save(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["objective"] == "objetivo de teste"
    assert len(data["nodes"]) == 2
