"""Tests unitaires du noyau de l'agent local (registres, outils, contexte, boucle)."""

import os
from types import SimpleNamespace

import pytest
from rich.console import Console

from agent.context import ConversationContext, WorkspaceState
from agent.loop import AgentLoop
from agent.swarm import SwarmManager
from tools.filesystem import register_filesystem_tools
from tools.registry import ToolRegistry, smart_truncate
from tools.shell import register_shell_tool


class FakeOllamaClient:
    """Mock de ollama.Client retournant des flux pré-enregistrés à chaque appel."""

    def __init__(self, scripted_turns):
        self.scripted_turns = list(scripted_turns)
        self.calls = []

    def chat(self, model, messages, tools=None, stream=False, **kwargs):
        self.calls.append(
            {
                "model": model,
                "messages": [dict(m) for m in messages],
                "tools": tools,
                "stream": stream,
            }
        )
        chunks = self.scripted_turns.pop(0)
        return iter(chunks)


def _chunk(content="", thinking="", tool_calls=None, done=False, eval_count=0, prompt_eval_count=0):
    msg = SimpleNamespace(content=content, thinking=thinking, tool_calls=tool_calls)
    return SimpleNamespace(
        message=msg,
        done=done,
        eval_count=eval_count,
        prompt_eval_count=prompt_eval_count,
        eval_duration=1_000_000_000 if done else 0,
    )


def _tool_call(name, arguments):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))


def test_registry_schema_and_smart_truncate():
    reg = ToolRegistry()
    reg.register(
        name="echo",
        description="Renvoie le texte.",
        parameters={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
        handler=lambda text: text,
    )
    schemas = reg.get_ollama_tools()
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "echo"

    long_text = "HEAD_" + ("a" * 3000) + ("b" * 1500) + "_TAIL"
    truncated = smart_truncate(long_text, max_chars=3500)
    assert truncated.startswith("HEAD_")
    assert truncated.endswith("_TAIL")
    assert len(truncated) < len(long_text)
    assert "caractères omis" in truncated


def test_filesystem_tools_and_undo(tmp_path):
    ws = WorkspaceState(str(tmp_path))
    reg = ToolRegistry()
    register_filesystem_tools(reg, ws)

    # write_file + syntax check rollback on invalid Python
    bad_py = reg.execute("write_file", {"path": "sample.py", "content": "def broken(:\n    pass\n"})
    assert "Erreur syntaxe Python" in bad_py
    assert not (tmp_path / "sample.py").exists()

    ok_write = reg.execute("write_file", {"path": "sample.py", "content": "def add(a, b):\n    return a + b\n"})
    assert "créé/écrit" in ok_write
    assert (tmp_path / "sample.py").exists()

    # list_dir, read_file, grep_search
    listing = reg.execute("list_dir", {"path": "."})
    assert "sample.py" in listing

    read_out = reg.execute("read_file", {"path": "sample.py", "start_line": 1, "end_line": 10})
    assert "1 | def add(a, b):" in read_out

    grep_out = reg.execute("grep_search", {"pattern": "return a \\+ b"})
    assert "sample.py:2:" in grep_out

    # edit_file returns diff
    edit_out = reg.execute(
        "edit_file",
        {"path": "sample.py", "old_text": "return a + b", "new_text": "return a + b + 1"},
    )
    assert "-    return a + b" in edit_out
    assert "+    return a + b + 1" in edit_out

    # undo removes newly created file
    undo_msg = ws.undo()
    assert "supprimé sample.py" in undo_msg
    assert not (tmp_path / "sample.py").exists()


def test_context_pruning_never_orphans_tool_message():
    ctx = ConversationContext("SYSTEM")
    ctx.add_user("Question 1")
    ctx.add_assistant("", tool_calls=[{"function": {"name": "read_file", "arguments": {"path": "a.py"}}}])
    ctx.add_tool("read_file", "X" * 2000)
    ctx.add_assistant("Réponse 1")

    ctx.add_user("Question 2")
    ctx.add_assistant("", tool_calls=[{"function": {"name": "read_file", "arguments": {"path": "b.py"}}}])
    ctx.add_tool("read_file", "Y" * 2000)
    ctx.add_assistant("Réponse 2")

    # Budget serré : force compaction puis suppression du tour 1 sans casser le tour 2.
    ctx.prune_if_needed(max_tokens=450)
    assert ctx.messages[0] == {"role": "system", "content": "SYSTEM"}
    roles = [m["role"] for m in ctx.messages]
    for i, role in enumerate(roles):
        if role == "tool":
            assert i > 0 and roles[i - 1] == "assistant"
            assert ctx.messages[i - 1].get("tool_calls")


def test_agent_loop_direct_reply_and_thinking():
    ctx = ConversationContext("SYS")
    reg = ToolRegistry()
    ws = WorkspaceState(".")
    client = FakeOllamaClient(
        [
            [
                _chunk(thinking="Analyse rapide..."),
                _chunk(content="Bonjour, "),
                _chunk(content="tout est prêt.", done=True, eval_count=6, prompt_eval_count=10),
            ]
        ]
    )
    loop = AgentLoop(client, "fake-model", ctx, reg, ws, console=Console(quiet=True), show_thinking=False)
    reply = loop.run_turn("Salut")
    assert reply == "Bonjour, tout est prêt."
    assert ctx.messages[-1] == {"role": "assistant", "content": "Bonjour, tout est prêt."}


def test_agent_loop_native_tool_call_and_inline_think(tmp_path):
    (tmp_path / "hello.txt").write_text("ligne 1\nligne 2\n", encoding="utf-8")
    ws = WorkspaceState(str(tmp_path))
    reg = ToolRegistry()
    register_filesystem_tools(reg, ws)
    ctx = ConversationContext("SYS")

    client = FakeOllamaClient(
        [
            [
                _chunk(content="<think>Je lis le fichier</think>"),
                _chunk(tool_calls=[_tool_call("read_file", {"path": "hello.txt"})], done=True),
            ],
            [
                _chunk(content="Le fichier contient 2 lignes.", done=True, eval_count=8, prompt_eval_count=20),
            ],
        ]
    )
    loop = AgentLoop(client, "fake-model", ctx, reg, ws, console=Console(quiet=True), show_thinking=False)
    reply = loop.run_turn("Lis hello.txt")

    assert reply == "Le fichier contient 2 lignes."
    roles = [m["role"] for m in ctx.messages]
    assert roles == ["system", "user", "assistant", "tool", "assistant"]
    assert "ligne 1" in ctx.messages[3]["content"]


def test_agent_loop_anti_loop_intercepts_and_finalizes(tmp_path):
    ws = WorkspaceState(str(tmp_path))
    reg = ToolRegistry()
    calls_executed = 0

    def flaky_tool(arg: str) -> str:
        nonlocal calls_executed
        calls_executed += 1
        return f"résultat pour {arg}"

    reg.register(
        name="probe",
        description="Outil de test.",
        parameters={"type": "object", "properties": {"arg": {"type": "string"}}, "required": ["arg"]},
        handler=flaky_tool,
    )
    ctx = ConversationContext("SYS")

    identical_call = [_tool_call("probe", {"arg": "same"})]
    client = FakeOllamaClient(
        [
            [_chunk(tool_calls=identical_call, done=True)],  # 1er appel : exécuté
            [_chunk(tool_calls=identical_call, done=True)],  # 2e appel identique : intercepté
            [_chunk(tool_calls=identical_call, done=True)],  # 3e appel identique : force synthèse
            [_chunk(content="Synthèse finale propre.", done=True)],
        ]
    )
    loop = AgentLoop(client, "fake-model", ctx, reg, ws, console=Console(quiet=True))
    reply = loop.run_turn("Teste la boucle")

    assert calls_executed == 1
    assert reply == "Synthèse finale propre."
    assert client.calls[-1]["tools"] == []


def _make_swarm(client, tmp_path, orch_model="huihui_ai/qwen3-abliterated:14b"):
    ws = WorkspaceState(str(tmp_path))
    reg = ToolRegistry()
    register_filesystem_tools(reg, ws)
    register_shell_tool(reg, ws)
    model_holder = {"model": orch_model}
    swarm = SwarmManager(
        client=client,
        get_orchestrator_model=lambda: model_holder["model"],
        base_registry=reg,
        workspace=ws,
        console=Console(quiet=True),
        get_debug=lambda: False,
        get_show_thinking=lambda: False,
    )
    swarm.register_delegate_tool(reg)
    return ws, reg, swarm, model_holder


def test_swarm_worker_tool_isolation(tmp_path):
    client = FakeOllamaClient([])
    _ws, reg, swarm, _ = _make_swarm(client, tmp_path)

    assert reg.get_tool("delegate_task") is not None

    researcher_tools = {t.name for t in swarm.build_worker_registry("researcher").list_tools()}
    assert researcher_tools == {"list_dir", "read_file", "grep_search"}
    assert "delegate_task" not in researcher_tools
    assert "write_file" not in researcher_tools
    assert "edit_file" not in researcher_tools
    assert "run_command" not in researcher_tools

    coder_tools = {t.name for t in swarm.build_worker_registry("coder").list_tools()}
    assert coder_tools == {"list_dir", "read_file", "grep_search", "edit_file", "write_file", "run_command"}
    assert "delegate_task" not in coder_tools

    for role in ("researcher", "coder", "security", "reviewer"):
        role_tools = {t.name for t in swarm.build_worker_registry(role).list_tools()}
        assert "delegate_task" not in role_tools


def test_swarm_orchestrator_delegates_and_undo_works(tmp_path):
    client = FakeOllamaClient(
        [
            # 1. Orchestrateur délègue au worker coder
            [_chunk(tool_calls=[_tool_call("delegate_task", {"role": "coder", "task": "Crée demo.py"})], done=True)],
            # 2. Worker coder appelle write_file
            [_chunk(tool_calls=[_tool_call("write_file", {"path": "demo.py", "content": "print('ok')\n"})], done=True)],
            # 3. Worker coder termine son rapport
            [_chunk(content="Fichier demo.py créé.", done=True)],
            # 4. Orchestrateur synthétise pour l'utilisateur
            [_chunk(content="Le worker coder a créé demo.py.", done=True)],
        ]
    )
    ws, reg, _swarm, _ = _make_swarm(client, tmp_path)
    ctx = ConversationContext("SYS")
    loop = AgentLoop(client, "huihui_ai/qwen3-abliterated:14b", ctx, reg, ws, console=Console(quiet=True))

    reply = loop.run_turn("Crée un script demo.py")
    assert reply == "Le worker coder a créé demo.py."
    assert (tmp_path / "demo.py").exists()

    # Le contexte du worker (appel #2 et #3) est isolé de celui de l'orchestrateur.
    assert len(client.calls) == 4
    assert "delegate_task" not in [t["function"]["name"] for t in client.calls[1]["tools"]]

    undo_msg = ws.undo()
    assert "supprimé demo.py" in undo_msg
    assert not (tmp_path / "demo.py").exists()


def test_swarm_role_model_override(tmp_path):
    client = FakeOllamaClient([])
    _ws, _reg, swarm, model_holder = _make_swarm(client, tmp_path)

    assert swarm.get_model_for_role("coder") == "huihui_ai/qwen3-abliterated:14b"

    msg_override = swarm.set_role_model("coder", "qwen2.5-coder:14b")
    assert "qwen2.5-coder:14b" in msg_override
    assert swarm.get_model_for_role("coder") == "qwen2.5-coder:14b"
    assert swarm.get_model_for_role("security") == "huihui_ai/qwen3-abliterated:14b"

    msg_reset = swarm.set_role_model("coder", "inherit")
    assert "Zero-Swap" in msg_reset
    assert swarm.get_model_for_role("coder") == "huihui_ai/qwen3-abliterated:14b"

    model_holder["model"] = "qwen3:14b"
    assert swarm.get_model_for_role("coder") == "qwen3:14b"
