from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def git_check_ignore(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", path],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def test_sec01_t5_gitignore_boundaries():
    assert git_check_ignore(".env")
    assert not git_check_ignore(".env.example")
    assert git_check_ignore("data/x")
    assert git_check_ignore(".pytest_cache/x")
    assert git_check_ignore("verification/a_report.json")
    assert git_check_ignore("x.mst")
