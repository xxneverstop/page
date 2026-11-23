from pathlib import Path

import page
import page as page_pkg
from page import (
    FakeModelClient,
    OllamaModelClient,
    Page,
    SessionStore,
    WorkspaceContext,
    build_agent,
    build_arg_parser,
    build_welcome,
    main,
)


def test_public_api_exports_current_names_only():
    assert Page is not None
    assert SessionStore is not None
    assert WorkspaceContext is not None
    assert callable(build_agent)
    assert callable(build_arg_parser)
    assert callable(build_welcome)
    assert callable(main)
    assert not hasattr(page, "MiniAgent")
    assert "MiniAgent" not in page.__all__


def test_build_agent_returns_pico(tmp_path):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    args = build_arg_parser().parse_args(["--cwd", str(tmp_path), "--approval", "auto"])

    agent = build_agent(args)

    assert isinstance(agent, Page)


def test_lightweight_package_split_uses_package_paths_without_legacy_shims():
    from page.evaluation.evaluator import BenchmarkEvaluator
    from page.evaluation.metrics import run_context_ablation_v2
    from page.features.memory import LayeredMemory
    from page.providers.clients import FakeModelClient as ProviderFakeModelClient

    assert BenchmarkEvaluator is not None
    assert LayeredMemory is not None
    assert ProviderFakeModelClient is not None
    assert callable(run_context_ablation_v2)
    for legacy_module in ("evaluator.py", "metrics.py", "models.py", "memory.py"):
        assert not (Path("page") / legacy_module).exists()


def test_packaging_discovers_pico_subpackages():
    pyproject_text = Path("pyproject.toml").read_text(encoding="utf-8")

    assert "[tool.setuptools.packages.find]" in pyproject_text
    assert 'include = ["page*"]' in pyproject_text


def test_public_api_exports_resolve_through_package_path():
    assert callable(build_welcome)
    assert FakeModelClient is not None
    assert Page is not None
    assert OllamaModelClient is not None
    assert SessionStore is not None
    assert WorkspaceContext is not None
    assert Path(page_pkg.__file__).as_posix().endswith("/page/__init__.py")


def test_reviewer_skeleton_docs_exist():
    review_pack = Path("docs/review-pack/README.md")
    architecture = Path("docs/architecture/agent-harness-v1-overview.md")

    assert review_pack.exists()
    assert architecture.exists()

    review_text = review_pack.read_text(encoding="utf-8")
    assert "Project pitch" in review_text
    assert "Architecture map" in review_text
    assert "Benchmark evidence" in review_text
    assert "Sample run artifact list" in review_text

    architecture_text = architecture.read_text(encoding="utf-8")
    assert "Agent Harness v1" in architecture_text
    assert "task state" in architecture_text.lower()


def test_package_import_surface_includes_cli_entrypoints():
    assert callable(page_pkg.main)
    assert callable(page_pkg.build_agent)
    assert callable(page_pkg.build_arg_parser)
