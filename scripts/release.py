#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check import parse_frontmatter

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
PAYLOAD_FIXED = ("SKILL.md", "VERSION", "CHANGELOG.md")


def fail(message: str, fix: str) -> None:
    print(f"FAIL release: {message}", file=sys.stderr)
    print(f"  修复: {fix}", file=sys.stderr)


def read_version(root: Path) -> tuple[str | None, list[tuple[str, str]]]:
    path = root / "VERSION"
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None, [("VERSION:1 文件不存在", "写入 VERSION 后运行 python3 scripts/release.py --check")]
    if not SEMVER_RE.match(raw):
        return None, [
            (
                f"VERSION:1 内容 {raw!r} 不是 semver（X.Y.Z）",
                "改成 X.Y.Z 后运行 python3 scripts/release.py --check",
            )
        ]
    return raw, []


def check(root: Path) -> tuple[str | None, list[tuple[str, str]]]:
    version, errors = read_version(root)
    if errors:
        return version, errors
    assert version is not None
    try:
        changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        errors.append(
            (
                "CHANGELOG.md:1 不存在",
                "创建 CHANGELOG.md 后运行 python3 scripts/release.py --check",
            )
        )
    else:
        if f"## [{version}]" not in changelog:
            errors.append(
                (
                    f"CHANGELOG.md:1 缺少 ## [{version}] 条目",
                    "补该版本条目后运行 python3 scripts/release.py --check",
                )
            )
    try:
        skill = (root / "SKILL.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        errors.append(
            (
                "SKILL.md:1 不存在",
                "创建 SKILL.md 后运行 python3 scripts/release.py --check",
            )
        )
    else:
        meta, _, error = parse_frontmatter(skill)
        if error is not None or meta is None:
            errors.append(
                (
                    f"SKILL.md:1 frontmatter 无法解析: {error}",
                    "修正 frontmatter 后运行 python3 scripts/release.py --check",
                )
            )
        else:
            metadata = meta.get("metadata")
            embedded = metadata.get("version") if isinstance(metadata, dict) else None
            if embedded != version:
                errors.append(
                    (
                        f"SKILL.md:1 metadata.version={embedded!r} 与 VERSION={version!r} 不一致",
                        "同步版本号后运行 python3 scripts/release.py --check",
                    )
                )
    return version, errors


def payload_files(root: Path) -> tuple[list[Path], list[tuple[str, str]]]:
    errors: list[tuple[str, str]] = []
    files: list[Path] = []
    for rel in PAYLOAD_FIXED:
        path = root / rel
        if path.is_file():
            files.append(path)
        else:
            errors.append(
                (
                    f"发布产物缺少 {rel}",
                    f"创建 {rel} 后运行 python3 scripts/release.py --pack",
                )
            )
    references = root / "references"
    if not references.is_dir():
        errors.append(
            (
                "发布产物缺少 references/ 目录",
                "补齐 references/ 后运行 python3 scripts/release.py --pack",
            )
        )
    else:
        ref_files = sorted(
            path
            for path in references.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and not path.name.startswith(".")
        )
        if not ref_files:
            errors.append(
                (
                    "references/ 下没有文件",
                    "补齐 references/*.md 后运行 python3 scripts/release.py --pack",
                )
            )
        files.extend(ref_files)
    payload = sorted({path.resolve() for path in files}, key=lambda p: p.as_posix())
    return payload, errors


def add_bytes(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    archive.writestr(info, data)


def pack(root: Path, version: str) -> tuple[Path | None, list[tuple[str, str]]]:
    payload, errors = payload_files(root)
    if errors:
        return None, errors
    dist = root / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    target = dist / f"open-problem-method-v{version}.zip"
    manifest_files: dict[str, str] = {}
    blobs: list[tuple[str, bytes]] = []
    for path in payload:
        rel = path.relative_to(root).as_posix()
        data = path.read_bytes()
        manifest_files[rel] = hashlib.sha256(data).hexdigest()
        blobs.append((rel, data))
    manifest = {
        "name": "open-problem-method",
        "version": version,
        "files": dict(sorted(manifest_files.items())),
    }
    manifest_bytes = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, "w") as archive:
        for rel, data in blobs:
            add_bytes(archive, rel, data)
        add_bytes(archive, "manifest.json", manifest_bytes)
    (dist / "manifest.json").write_bytes(manifest_bytes)
    print(
        f"PACK {target.relative_to(root).as_posix()} "
        f"({len(blobs)} files + manifest.json)"
    )
    return target, []


def smoke(root: Path, version: str) -> list[tuple[str, str]]:
    archive_path = root / "dist" / f"open-problem-method-v{version}.zip"
    if not archive_path.is_file():
        return [
            (
                f"找不到 {archive_path.relative_to(root).as_posix()}",
                "先运行 python3 scripts/release.py --pack，再运行 --smoke",
            )
        ]
    errors: list[tuple[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="opm-smoke-") as tmp:
        with zipfile.ZipFile(archive_path) as archive:
            names = set(archive.namelist())
            for required in ("SKILL.md", "VERSION", "CHANGELOG.md", "manifest.json"):
                if required not in names:
                    errors.append(
                        (
                            f"zip 缺少 {required}",
                            "重新运行 python3 scripts/release.py --pack",
                        )
                    )
            if "SKILL.md" not in names:
                return errors
            archive.extractall(tmp)
        root_dir = Path(tmp)
        if "manifest.json" in names:
            try:
                manifest = json.loads(
                    (root_dir / "manifest.json").read_text(encoding="utf-8")
                )
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                errors.append(
                    (
                        f"manifest.json 无法解析: {exc}",
                        "重新运行 python3 scripts/release.py --pack",
                    )
                )
            else:
                files = manifest.get("files") if isinstance(manifest, dict) else None
                if not isinstance(files, dict):
                    errors.append(
                        (
                            "manifest.json 缺少 files 映射",
                            "重新运行 python3 scripts/release.py --pack",
                        )
                    )
                else:
                    for rel, digest in files.items():
                        path = root_dir / rel
                        if not path.is_file():
                            errors.append(
                                (
                                    f"manifest.json 列出的 {rel} 不在 zip 中",
                                    "重新运行 python3 scripts/release.py --pack",
                                )
                            )
                            continue
                        actual = hashlib.sha256(path.read_bytes()).hexdigest()
                        if actual != digest:
                            errors.append(
                                (
                                    f"manifest.json 中 {rel} 的 sha256 不匹配",
                                    "重新运行 python3 scripts/release.py --pack",
                                )
                            )
        skill = (root_dir / "SKILL.md").read_text(encoding="utf-8")
        meta, _, error = parse_frontmatter(skill)
        if error is not None or meta is None:
            errors.append(
                (
                    f"解压后的 SKILL.md frontmatter 无法解析: {error}",
                    "修正源 SKILL.md 后重新 pack 与 smoke",
                )
            )
            return errors
        if meta.get("name") != "open-problem-method":
            errors.append(
                (
                    f"解压后的 name={meta.get('name')!r} 不是 open-problem-method",
                    "修正 SKILL.md 的 name 后重新 pack 与 smoke",
                )
            )
        description = meta.get("description")
        if not isinstance(description, str) or not description.strip():
            errors.append(
                (
                    "解压后的 description 为空",
                    "修正 SKILL.md 的 description 后重新 pack 与 smoke",
                )
            )
        metadata = meta.get("metadata")
        embedded = metadata.get("version") if isinstance(metadata, dict) else None
        if embedded != version:
            errors.append(
                (
                    f"解压后的 metadata.version={embedded!r} 与 VERSION={version!r} 不一致",
                    "同步版本号后重新 pack 与 smoke",
                )
            )
    if not errors:
        print(f"SMOKE dist/open-problem-method-v{version}.zip frontmatter OK")
    return errors


def report(errors: list[tuple[str, str]]) -> None:
    for message, fix in errors:
        fail(message, fix)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="open-problem-method 发布工具")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="校验版本一致性（默认）")
    mode.add_argument("--pack", action="store_true", help="打包 dist zip 与 manifest")
    mode.add_argument("--smoke", action="store_true", help="解压并检查 frontmatter")
    mode.add_argument("--all", action="store_true", help="check + pack + smoke")
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

    if args.pack or args.all:
        version, errors = check(root) if args.all else read_version(root)
        if errors:
            report(errors)
            return 1
        assert version is not None
        _, pack_errors = pack(root, version)
        if pack_errors:
            report(pack_errors)
            return 1
        if args.pack:
            return 0
        smoke_errors = smoke(root, version)
        if smoke_errors:
            report(smoke_errors)
            return 1
        print(f"OK release v{version}: check, pack, smoke")
        return 0

    if args.smoke:
        version, errors = read_version(root)
        if errors:
            report(errors)
            return 1
        assert version is not None
        smoke_errors = smoke(root, version)
        if smoke_errors:
            report(smoke_errors)
            return 1
        return 0

    version, errors = check(root)
    if errors:
        report(errors)
        return 1
    print(f"OK release-check: v{version}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
