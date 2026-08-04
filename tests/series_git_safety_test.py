"""系列模板和参考图只能保存在本地，不能进入 Git。"""

import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_SERIES_PATHS = (
    "series_templates.json",
    "series_projects.json",
    "series/template-private/references/sensitive-reference.png",
)


def run_git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("relative_path", LOCAL_SERIES_PATHS)
def test_local_series_runtime_files_are_gitignored(relative_path):
    result = run_git("check-ignore", "--no-index", "-q", relative_path)

    assert result.returncode == 0, (
        f"{relative_path} 包含本地系列模板、项目状态或敏感参考图，"
        "必须由 .gitignore 明确排除"
    )


def test_no_local_series_runtime_file_is_already_tracked():
    result = run_git(
        "ls-files",
        "--",
        "series_templates.json",
        "series_projects.json",
        "series/*/references/*",
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "", (
        "检测到系列模板、系列项目状态或敏感参考图已进入 Git：\n"
        f"{result.stdout}"
    )
