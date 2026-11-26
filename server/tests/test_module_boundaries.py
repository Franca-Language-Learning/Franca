"""Module boundaries (story E01-003).

The layers contract in pyproject.toml (checked by lint-imports) keeps franca.api above the twelve modules and
franca.platform below them. These tests add the rules that import-linter cannot express: a module imports
another module's package root only, and every module is listed in the layers contract.
"""

import tomllib
from pathlib import Path

import grimp

SERVER = Path(__file__).resolve().parents[1]
MODULES = sorted(
    p.name
    for p in (SERVER / "src" / "franca").iterdir()
    if p.is_dir() and (p / "__init__.py").exists() and p.name not in {"api", "platform"}
)


def module_of(name: str) -> str | None:
    parts = name.split(".")
    return parts[1] if len(parts) > 1 and parts[1] in MODULES else None


def test_there_are_twelve_modules() -> None:
    assert len(MODULES) == 12, MODULES


def test_every_module_is_in_the_layers_contract() -> None:
    config = tomllib.loads((SERVER / "pyproject.toml").read_text(encoding="utf-8"))
    layers = config["tool"]["importlinter"]["contracts"][0]["layers"]
    listed = {name.strip().removeprefix("franca.") for name in layers[1].split(":")}
    assert listed == set(MODULES)


def breaches(graph: grimp.ImportGraph) -> list[str]:
    found = []
    for importer in graph.modules:
        source = module_of(importer)
        if source is None:
            continue
        for imported in graph.find_modules_directly_imported_by(importer):
            target = module_of(imported)
            if target is not None and target != source and imported != f"franca.{target}":
                found.append(f"{importer} imports {imported}; import franca.{target} instead")
    return found


def test_modules_import_each_others_package_root_only() -> None:
    assert breaches(grimp.build_graph("franca")) == []


def test_an_import_of_another_modules_submodule_is_found() -> None:
    graph = grimp.ImportGraph()
    for name in ["franca", "franca.memory", "franca.memory.scheduler", "franca.study", "franca.study.planner_rules"]:
        graph.add_module(name)
    graph.add_import(importer="franca.memory.scheduler", imported="franca.study.planner_rules")
    graph.add_import(importer="franca.memory.scheduler", imported="franca.study")
    graph.add_import(importer="franca.study", imported="franca.study.planner_rules")
    assert breaches(graph) == ["franca.memory.scheduler imports franca.study.planner_rules; import franca.study instead"]
