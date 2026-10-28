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
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check import (
    read_yaml_file,
    validate_cases_data,
    yaml_section_lines,
)

PROMPT_PREFIX = "读取当前目录的 SKILL.md 并严格按其执行。"
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


def is_manual(case: dict) -> bool:
    return not case.get("must_match") and not case.get("must_not_match")


def build_prompt(case: dict) -> str:
    parts = []
    background = case.get("bg")
    if isinstance(background, str) and background.strip():
        parts.append("背景：\n" + background.strip())
    parts.append("用户请求：\n" + case["input"].strip())
    return PROMPT_PREFIX + "\n\n" + "\n\n".join(parts)


def build_command(
    case: dict, directory: str, model: str | None, thinking: bool = False
) -> list[str]:
    command = ["opencode", "run", "--dir", directory]
    if model:
        command += ["-m", model]
    if thinking:
        command.append("--thinking")
    command.append(build_prompt(case))
    return command


def compile_patterns(case: dict) -> tuple[list[re.Pattern], list[re.Pattern]]:
    flags = re.UNICODE | re.MULTILINE
    return (
        [re.compile(pattern, flags) for pattern in case.get("must_match") or []],
        [re.compile(pattern, flags) for pattern in case.get("must_not_match") or []],
    )


def plan(cases: list[dict], model: str | None, as_json: bool) -> int:
    rows = []
    for case in cases:
        command = build_command(case, "<临时目录>", model)
        rows.append(
            {
                "id": case["id"],
                "bg": case.get("bg"),
                "input": case["input"],
                "review": case.get("review") or [],
                "reference": case.get("reference") or {},
                "manual": is_manual(case),
                "command": command,
                "display": shlex.join(command),
            }
        )
    if as_json:
        print(json.dumps({"model": model, "cases": rows}, ensure_ascii=False, indent=2))
        return 0
    for row in rows:
        mode = "人工审查" if row["manual"] else "正则判定"
        print(f"{row['id']}（{mode}）: {row['display']}")
        if row["reference"]:
            print("  参考（本机，gitignore）:")
            for key, value in row["reference"].items():
                print(f"    {key}: {value}")
        if row["manual"]:
            for item in row["review"]:
                print(f"  - {item}")
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


def save_capture(
    root: Path,
    case: dict,
    command: list[str],
    stdout: str,
    stderr: str,
    returncode: int,
    model: str | None,
) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    run_dir = root / "evals/runs" / f"{stamp}-{case['id']}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "stdout.txt").write_text(stdout, encoding="utf-8")
    (run_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
    (run_dir / "command.txt").write_text(shlex.join(command), encoding="utf-8")
    (run_dir / "prompt.txt").write_text(build_prompt(case), encoding="utf-8")
    meta = {
        "case": case["id"],
        "model": model,
        "returncode": returncode,
        "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "reference": case.get("reference") or {},
        "stdout_chars": len(stdout),
        "stderr_chars": len(stderr),
    }
    (run_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return run_dir.relative_to(root).as_posix()


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
    run_dir: str | None = None,
) -> dict:
    return {
        "id": case["id"],
        "passed": False,
        "manual": is_manual(case),
        "review": case.get("review") or [],
        "reference": case.get("reference") or {},
        "run_dir": run_dir,
        "returncode": returncode,
        "missing": [pattern.pattern for pattern in must],
        "unexpected": [],
        "error": error,
        "stderr": stderr[-2000:],
        "stdout": stdout[-2000:],
        "artifact": None,
    }


def execute(case: dict, root: Path, model: str | None, capture: bool = False) -> dict:
    tmp = prepare_workspace(root)
    must, must_not = compile_patterns(case)
    manual = is_manual(case)
    try:
        command = build_command(case, tmp.name, model, thinking=capture and manual)
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
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            run_dir = (
                save_capture(root, case, command, stdout, stderr, 124, model)
                if capture
                else None
            )
            return failure(
                case,
                must,
                f"opencode 超时（>{TIMEOUT_SECONDS}s）",
                returncode=124,
                stdout=stdout,
                stderr=stderr,
                run_dir=run_dir,
            )
        stdout = process.stdout or ""
        stderr = process.stderr or ""
        run_dir = (
            save_capture(
                root, case, command, stdout, stderr, process.returncode, model
            )
            if capture
            else None
        )
        if process.returncode != 0:
            return failure(
                case,
                must,
                f"opencode 退出码 {process.returncode}",
                returncode=process.returncode,
                stdout=stdout,
                stderr=stderr,
                run_dir=run_dir,
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
            "manual": manual,
            "review": case.get("review") or [],
            "reference": case.get("reference") or {},
            "run_dir": run_dir,
            "returncode": process.returncode,
            "missing": missing,
            "unexpected": unexpected,
            "error": None,
            "stderr": "",
            "stdout": stdout if manual else stdout[-2000:],
            "artifact": artifact,
        }
    finally:
        tmp.cleanup()


def print_result(result: dict) -> None:
    if result.get("manual"):
        print(f"MANUAL {result['id']}（人工审查）")
        if result.get("error"):
            print(f"  运行失败: {result['error']}")
        for item in result.get("review") or []:
            print(f"  - {item}")
        if result.get("reference"):
            print("  历史参考（本机）:")
            for key, value in result["reference"].items():
                print(f"    {key}: {value}")
        if result.get("run_dir"):
            print(f"  本次记录: {result['run_dir']}")
        if result.get("artifact"):
            print(f"  产物: {result['artifact']}")
        output = result.get("stdout") or ""
        if output:
            print("  输出:")
            print("    " + output.replace("\n", "\n    "))
        if result.get("stderr"):
            print("  stderr:")
            print("    " + result["stderr"].replace("\n", "\n    "))
        return
    if result["passed"]:
        suffix = f" -> {result['artifact']}" if result.get("artifact") else ""
        print(f"PASS {result['id']}{suffix}")
        if result.get("run_dir"):
            print(f"  记录: {result['run_dir']}")
        return
    print(f"FAIL {result['id']}")
    if result.get("run_dir"):
        print(f"  记录: {result['run_dir']}")
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
        "--capture",
        action="store_true",
        help="把本次原始输出（含 --thinking）写入 evals/runs/<时间>-<id>/",
    )
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
            "  修复: 本机维护 evals/cases.yaml（已 gitignore）；按上面的行号修正后运行 "
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
        result = execute(case, root, args.model, capture=args.capture)
        results.append(result)
        if not args.json:
            print_result(result)
            sys.stdout.flush()
    if args.json:
        print(json.dumps({"model": args.model, "results": results}, ensure_ascii=False, indent=2))
    else:
        automatic = [result for result in results if not result.get("manual")]
        manual = [result for result in results if result.get("manual")]
        if automatic:
            passed = sum(1 for result in automatic if result["passed"])
            print(f"\n{passed}/{len(automatic)} PASS（自动用例）")
        if manual:
            print(f"{len(manual)} 条人工用例已运行，请按审查清单逐条判断。")
        if args.capture:
            print("本次原始输出已写入 evals/runs/（gitignore）。")
    failed = any(
        (not result.get("manual") and not result["passed"])
        or (result.get("manual") and result.get("error"))
        for result in results
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
