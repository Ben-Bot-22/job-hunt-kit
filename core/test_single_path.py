"""There is exactly one generation path, as a test rather than a promise.

    every model client in this repo is built by `core/llm.py`, and by nothing else.

`core/test_layering.py` is the sibling of this file and the same idea: a rule that only lives in a
docstring is a rule that gets widened by one convenient line in a diff nobody reads closely. This one
is the rule stage 3 exists for — the spec's governing sentence is *"LangChain owns new code. It also
becomes the single generation path. It never leaves two paths behind."* Two paths is not a style
complaint: it is every prompt, retry and failure mode maintained twice and drifting apart, and it is
also the thing that makes `llm.provider` in `config/settings.yaml` a lie for whichever call site
forgot.

Parsed with `ast`, like the layering check, so it needs nothing installed and reports every violation
at once. It looks for the two shapes a second path arrives as: **constructing a client** (any of the
provider classes, or a bare `Anthropic()`), and **calling one** (`.messages.parse` / `.messages.create`,
the native SDK surface all three call sites used before stage 3).

Three exemptions, all deliberate and all named below rather than pattern-matched away — an exemption
you cannot see is how this test quietly stops meaning anything. There used to be a fourth, a whole
package. The original Sheets pipeline was frozen, unmigrated, and the one place a second path still
lived; stage 5 · 01 deleted it, so the rule now holds over every line of Python in the repo with no
escape hatch.
"""
from __future__ import annotations


#: One line for the rule index — see `core/rules.py`.
RULE = "There is exactly one generation path — `core/llm.py` is the only place a model client is built or called."
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ("core", "triage", "research", "cv", "scripts")

# The class names that mean "a model client is being constructed here".
CLIENT_CONSTRUCTORS = frozenset({
    "Anthropic", "AsyncAnthropic", "ChatAnthropic",
    "OpenAI", "AsyncOpenAI", "ChatOpenAI",
    "ChatGoogleGenerativeAI", "ChatOllama",
})

# The native SDK call the three migrated call sites used to make.
CLIENT_CALLS = ("messages.parse", "messages.create")

EXEMPT: dict[str, str] = {
    # The single path itself. This is the file the rule points *at*.
    "core/llm.py": "the single generation path",
    # Both exist to compare the two paths against each other, which cannot be done through one of
    # them. `core/test_structured_output.py` is what pins the LangChain request byte-for-byte
    # against the native `messages.parse` it replaced; the script is the spike that produced it.
    "core/test_structured_output.py": "pins the single path's request against the native SDK call",
    "scripts/probe_structured_output.py": "the structured-output spike, which builds both by design",
}

# No package-wide exemptions. Keep it that way: an exempt *directory* is an exemption nobody reads,
# because it never appears at the line that breaks the rule.
EXEMPT_PACKAGES: tuple[str, ...] = ()


def _dotted(node: ast.AST) -> str:
    """`config.client().messages.parse` -> `messages.parse`; `anthropic.Anthropic` -> `Anthropic`.

    Only the attribute tail is reconstructed. What the client was fetched *from* varies (a module
    global, a function call, `self`), and none of that changes whether this is a second path.
    """
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _violations_in(source: str, filename: str = "<test>") -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if not isinstance(node, ast.Call):
            continue
        name = _dotted(node.func)
        if name.split(".")[-1] in CLIENT_CONSTRUCTORS:
            found.append(f"constructs {name}()")
        elif any(name.endswith(call) for call in CLIENT_CALLS):
            found.append(f"calls .{name.split('.')[-2]}.{name.split('.')[-1]}()")
    return found


def _modules() -> list[Path]:
    return sorted(
        p for package in PACKAGES if (ROOT / package).exists()
        for p in (ROOT / package).rglob("*.py")
        if "__pycache__" not in p.parts and p.relative_to(ROOT).parts[0] not in EXEMPT_PACKAGES
    )


def test_only_core_llm_builds_a_model_client() -> None:
    """The end state of stage 3: `analyze.py` was the last call site, and nothing is left behind it."""
    violations = [
        f"{rel}: {', '.join(bad)}"
        for module in _modules()
        for rel in [str(module.relative_to(ROOT))]
        if rel not in EXEMPT
        for bad in [_violations_in(module.read_text(encoding="utf-8"), rel)]
        if bad
    ]
    assert not violations, (
        "every model client must be built by core/llm.py — a second generation path is back:\n"
        + "\n".join(violations)
    )


def test_the_detector_sees_the_shapes_a_second_path_arrives_as() -> None:
    """Guard the guard. These are the exact three lines this repo had before stage 3."""
    source = (
        "_client = anthropic.Anthropic(api_key=KEY)\n"
        "resp = config.client().messages.parse(model=M, output_format=Analysis)\n"
        "llm = ChatAnthropic(model=M, max_tokens=8000)\n"
    )
    assert _violations_in(source) == [
        "constructs anthropic.Anthropic()", "calls .messages.parse()", "constructs ChatAnthropic()"]


def test_the_detector_passes_the_migrated_call_site() -> None:
    """And it must not fire on the thing that replaced them, or it would just be noise."""
    assert _violations_in("out = llm.structured(Analysis, M, max_tokens=8000).invoke(msgs)\n") == []
