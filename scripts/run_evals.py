#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check import (
    read_yaml_file,
    validate_cases_data,
    yaml_section_lines,
)

PROMPT_PREFIX = "读取当前目录的 SKILL.md 并严格按其执行。用户请求："
TIMEOUT_SECONDS = 600


def load_cases(root: Path) -> tuple[list[dict], list[str]]:
    data, text, error = read_yaml_file(root / "evals/cases.yaml")
    if error is not None:
        return [], [error]
    lines = yaml_section_lines(text, "cases")
    issues = validate_cases_data(data, lines)
    if issues:
        return [], [f"evals/cases.yaml:{line} {message}" for line, message in issues]
    assert isinstance(data, dict)
    return data["cases"], []


def build_command(case: dict, directory: str, model: str | None) -> list[str]:
    prompt = PROMPT_PREFIX + case["input"]
    command = ["opencode", "run", "--dir", directory]
    if model:
        command += ["-m", model]
    command.append(prompt)
    return command


def compile_patterns(case: dict) -> tuple[list[re.Pattern], list[re.Pattern]]:
    flags = re.UNICODE | re.MULTILINE
    return (
        [re.compile(pattern, flags) for pattern in case["must_match"]],
        [re.compile(pattern, flags) for pattern in case["must_not_match"]],
    )


def plan(cases: list[dict], model: str | None, as_json: bool) -> int:
    rows = []
    for case in cases:
        command = build_command(case, "<临时目录>", model)
        rows.append(
            {
                "id": case["id"],
                "input": case["input"],
                "command": command,
                "display": shlex.join(command),
            }
        )
    if as_json:
        print(json.dumps({"model": model, "cases": rows}, ensure_ascii=False, indent=2))
        return 0
    for row in rows:
        print(f"{row['id']}: {row['display']}")
    print(f"\n共 {len(rows)} 条；--plan 不调用模型。")
    return 0


def prepare_workspace(root: Path) -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory(prefix="opm-eval-")
    target = Path(tmp.name)
    shutil.copy2(root / "SKILL.md", target / "SKILL.md")
    references = root / "references"
    if references.is_dir():
        shutil.copytree(references, target / "references")
    return tmp


def collect_artifacts(directory: Path, pattern: str) -> tuple[list[Path], str | None]:
    try:
        files = sorted(path for path in directory.rglob(pattern) if path.is_file())
    except (OSError, ValueError) as exc:
        return [], f"无法展开 artifact_glob {pattern!r}: {exc}"
    return files, None


def failure(
    case: dict,
    must: list[re.Pattern],
    error: str,
    *,
    returncode: int = 1,
    stdout: str = "",
    stderr: str = "",
) -> dict:
    return {
        "id": case["id"],
        "passed": False,
        "returncode": returncode,
        "missing": [pattern.pattern for pattern in must],
        "unexpected": [],
        "error": error,
        "stderr": stderr[-2000:],
        "stdout": stdout[-2000:],
        "artifact": None,
    }


def execute(case: dict, root: Path, model: str | None) -> dict:
    tmp = prepare_workspace(root)
    must, must_not = compile_patterns(case)
    try:
        command = build_command(case, tmp.name, model)
        try:
            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return failure(
                case, must, f"opencode 超时（>{TIMEOUT_SECONDS}s）", returncode=124
            )
        stdout = process.stdout or ""
        stderr = process.stderr or ""
        if process.returncode != 0:
            return failure(
                case,
                must,
                f"opencode 退出码 {process.returncode}",
                returncode=process.returncode,
                stdout=stdout,
                stderr=stderr,
            )

        content = stdout
        artifact = None
        glob = case.get("artifact_glob")
        if glob:
            files, error = collect_artifacts(Path(tmp.name), glob)
            if error is not None:
                return failure(case, must, error, stdout=stdout, stderr=stderr)
            if not files:
                return failure(
                    case,
                    must,
                    f"未生成匹配 {glob!r} 的文档",
                    stdout=stdout,
                    stderr=stderr,
                )
            try:
                content = "\n\n".join(
                    path.read_text(encoding="utf-8") for path in files
                )
            except (OSError, UnicodeDecodeError) as exc:
                return failure(
                    case, must, f"读取产物失败: {exc}", stdout=stdout, stderr=stderr
                )
            artifact = files[0].relative_to(Path(tmp.name)).as_posix()

        missing = [pattern.pattern for pattern in must if not pattern.search(content)]
        unexpected = [
            pattern.pattern for pattern in must_not if pattern.search(content)
        ]
        return {
            "id": case["id"],
            "passed": not missing and not unexpected,
            "returncode": process.returncode,
            "missing": missing,
            "unexpected": unexpected,
            "error": None,
            "stderr": "",
            "stdout": stdout[-2000:],
            "artifact": artifact,
        }
    finally:
        tmp.cleanup()


def print_result(result: dict) -> None:
    if result["passed"]:
        suffix = f" -> {result['artifact']}" if result.get("artifact") else ""
        print(f"PASS {result['id']}{suffix}")
        return
    print(f"FAIL {result['id']}")
    if result.get("error"):
        print(f"  错误: {result['error']}")
    if result["missing"]:
        print("  未命中 must_match:")
        for pattern in result["missing"]:
            print(f"    {pattern}")
    if result["unexpected"]:
        print("  命中 must_not_match:")
        for pattern in result["unexpected"]:
            print(f"    {pattern}")
    if result.get("stderr"):
        print("  stderr:")
        print("    " + result["stderr"].replace("\n", "\n    "))
    if result.get("stdout"):
        print("  stdout 末尾:")
        print("    " + result["stdout"].replace("\n", "\n    "))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="open-problem-method 行为评测")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="校验 YAML 并打印命令（默认）")
    mode.add_argument("--run", action="store_true", help="调用 opencode 执行用例")
    parser.add_argument("--only", metavar="ID", help="只运行指定 case id")
    parser.add_argument("--model", metavar="PROVIDER/MODEL", help="传给 opencode 的 -m")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument(
        "--root",
        metavar="PATH",
        default=str(Path(__file__).resolve().parent.parent),
        help="仓库根目录（默认取脚本所在仓库）",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"FAIL setup: --root 不是目录: {root}", file=sys.stderr)
        return 2

    cases, errors = load_cases(root)
    if errors:
        for message in errors:
            print(f"FAIL evals: {message}", file=sys.stderr)
        print(
            "  修复: 按上面的行号修正 evals/cases.yaml；然后运行 "
            "python3 scripts/run_evals.py --plan",
            file=sys.stderr,
        )
        return 1

    if args.only:
        cases = [case for case in cases if case["id"] == args.only]
        if not cases:
            print(f"FAIL setup: 未知 case id {args.only!r}", file=sys.stderr)
            return 2

    if not args.run:
        return plan(cases, args.model, args.json)

    if shutil.which("opencode") is None:
        print(
            "FAIL setup: 找不到 opencode CLI；行为评测需要它。\n"
            "  修复: 安装 opencode 并确保它在 PATH 中，然后重跑 "
            "python3 scripts/run_evals.py --run",
            file=sys.stderr,
        )
        return 2

    results = []
    for index, case in enumerate(cases, 1):
        if not args.json:
            print(f"RUN {index}/{len(cases)} {case['id']}", flush=True)
        result = execute(case, root, args.model)
        results.append(result)
        if not args.json:
            print_result(result)
            sys.stdout.flush()
    if args.json:
        print(json.dumps({"model": args.model, "results": results}, ensure_ascii=False, indent=2))
    else:
        passed = sum(1 for result in results if result["passed"])
        print(f"\n{passed}/{len(results)} PASS")
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
