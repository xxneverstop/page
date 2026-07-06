import subprocess
import sys
from pathlib import Path

import mini_page


def test_mini_page_module_and_public_exports():
    assert mini_page.Page is not None
    assert mini_page.FakeModelClient is not None
    assert not hasattr(mini_page, "MiniAgent")
    result = subprocess.run([sys.executable, "-m", "mini_page", "--help"], capture_output=True, text=True, check=True)
    assert "Teaching-sized Page agent harness" in result.stdout


def test_readme_main_mapping_points_to_existing_files():
    repo_root = Path(__file__).resolve().parents[3]
    main_files = [
        "page/cli.py",
        "page/runtime.py",
        "page/agent_loop.py",
        "page/context_manager.py",
        "page/providers/clients.py",
        "page/tool_executor.py",
        "page/tools.py",
        "page/task_state.py",
        "page/run_store.py",
        "page/workspace.py",
    ]
    for path in main_files:
        assert (repo_root / path).exists()
