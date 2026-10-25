#!/usr/bin/env python3
"""Verify that every structural gate still fails when its rule is violated.

The gates protect a prompt file, so a gate that silently passes is worse than no
gate. Each case copies the repository, breaks exactly one rule, and asserts that
the matching gate exits non-zero.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IGNORE = shutil.ignore_patterns(".git", "dist", "__pycache__", "*.pyc")


def copy_repo(target: Path) -> None:
    shutil.copytree(ROOT, target, ignore=IGNORE, dirs_exist_ok=True)


def run_gate(root: Path, gate: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "scripts/check.py", "--only", gate],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"{path.name}: 找不到要替换的文本: {old[:40]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def drop_decision_bullets(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(## 备选方案\n+)(?:- .*\n)+", r"\1", text, count=1)
    path.write_text(text, encoding="utf-8")


MUTATIONS: dict[str, Callable[[Path], object]] = {
    "frontmatter": lambda root: replace(
        root / "SKILL.md", "name: open-problem-method", "name: wrong-name"
    ),
    "structure": lambda root: replace(
        root / "SKILL.md", "## 5｜输出契约", "## 5｜输出"
    ),
    "budget": lambda root: (root / "AGENTS.md").write_text(
        (root / "AGENTS.md").read_text(encoding="utf-8") + "\n" + ("x" * 80 + "\n") * 60,
        encoding="utf-8",
    ),
    "links": lambda root: (root / "docs/design.md").write_text(
        (root / "docs/design.md").read_text(encoding="utf-8") + "\n[bad](missing.md)\n",
        encoding="utf-8",
    ),
    "refs": lambda root: (root / "references/transfer.md").rename(
        root / "references/transfer-renamed.md"
    ),
    "decisions": lambda root: drop_decision_bullets(
        root / "docs/decisions/0001-probe-first-classification.md"
    ),
    "version": lambda root: (root / "VERSION").write_text("9.9.9\n", encoding="utf-8"),
    "glossary": lambda root: replace(
        root / "docs/glossary.md",
        "| 止损线 |",
        "| 止损阈值 |",
    ),
    "evals": lambda root: replace(
        root / "evals/cases.yaml",
        "'(GB\\s*55038|GB\\s*55016|GB\\s*50118)'",
        "'(GB\\s*55038|GB\\s*55016|GB\\s*50118)['",
    ),
    "corpus": lambda root: (root / "AGENTS.md").unlink(),
}


def main() -> int:
    failures: list[str] = []

    with tempfile.TemporaryDirectory(prefix="opm-gate-test-") as tmp:
        base = Path(tmp) / ROOT.name
        copy_repo(base)
        baseline = subprocess.run(
            [sys.executable, "scripts/check.py", "--all"],
            cwd=base,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if baseline.returncode != 0:
            print("FAIL baseline: 原始仓库没有通过 check.py --all")
            print(baseline.stderr[-1000:])
            return 1
        print("PASS baseline")

    for gate, mutate in MUTATIONS.items():
        with tempfile.TemporaryDirectory(prefix=f"opm-gate-{gate}-") as tmp:
            target = Path(tmp) / ROOT.name
            copy_repo(target)
            try:
                mutate(target)
            except Exception as exc:  # noqa: BLE001 - report and keep testing
                failures.append(f"{gate}: 无法构造破坏: {exc}")
                print(f"FAIL {gate}: 无法构造破坏")
                continue
            result = run_gate(target, gate)
            if result.returncode == 0:
                failures.append(gate)
                print(f"FAIL {gate}: 破坏后 gate 仍然通过")
            elif f"FAIL {gate}" not in result.stderr:
                failures.append(gate)
                print(f"FAIL {gate}: 退出码非零但没有 FAIL {gate} 输出")
                print(result.stderr[-500:])
            else:
                print(f"PASS {gate}")

    if failures:
        print(f"\n{len(failures)}/{len(MUTATIONS)} 个破坏未被正确拦截")
        return 1
    print(f"\n{len(MUTATIONS)}/{len(MUTATIONS)} 个破坏全部被拦截")
    return 0


if __name__ == "__main__":
    sys.exit(main())
