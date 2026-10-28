#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

try:
    import yaml
except ImportError:
    yaml = None


EXCLUDED_DIR_NAMES = {"node_modules", "dist", "__pycache__", ".venv", "venv", ".git"}
LOCAL_EVAL_DIRS = {
    ("evals", "reference"),
    ("evals", "runs"),
}
REQUIRED_CORPUS_FILES = (
    "SKILL.md",
    "AGENTS.md",
    "docs/design.md",
    "docs/authoring.md",
    "docs/releasing.md",
    "docs/verification.md",
    "docs/glossary.md",
)
ALLOWED_FRONTMATTER_KEYS = {"name", "description", "allowed-tools", "metadata"}
ALLOWED_TOOLS = {"Read", "Grep", "Glob", "Bash", "Write", "Edit"}
EXPECTED_H2 = (
    "交付物",
    "1｜入口：默认「未判」",
    "2｜三种缺口，三道门禁",
    "3｜实例化（每条路径的强制步骤）",
    "4｜代价与排序",
    "5｜输出契约",
    "6｜硬性禁止",
    "7｜按需加载",
)
EXPECTED_H1 = "Open Problem Method"
DECISION_FILENAME_RE = re.compile(r"^\d{4}-[a-z0-9-]+\.md$")
DECISION_HEADING_RE = re.compile(r"^#\s+(\d{4})\s+\S")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
GLOSSARY_HEADER_RE = re.compile(
    r"^\|\s*术语\s*\|\s*定义\s*\|\s*不要写成\s*\|\s*$", re.MULTILINE
)
PATH_MENTION_RE = re.compile(r"(?<![\w./-])((?:references|docs)/[A-Za-z0-9_.\-/]+)")
INLINE_LINK_RE = re.compile(
    r"!?\[[^\]]*\]\(\s*(<[^>]*>|[^)\s]+)(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)"
)
REF_DEF_RE = re.compile(r"^\s{0,3}\[(?!\^)([^\]]+)\]:\s*(<[^>]*>|\S+)", re.MULTILINE)
HTML_ANCHOR_RE = re.compile(r"<a\s+[^>]*\bid\s*=\s*[\"']([^\"']+)[\"'][^>]*>", re.I)


@dataclass(frozen=True)
class Failure:
    message: str
    fix: str


class Repo:

    def __init__(self, root: Path) -> None:
        self.root = root
        self._md_files: list[str] | None = None
        self._text: dict[str, str | None] = {}

    def text(self, rel: str) -> str | None:
        if rel not in self._text:
            try:
                self._text[rel] = (self.root / rel).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                self._text[rel] = None
        return self._text[rel]

    def abs(self, rel: str) -> Path:
        return (self.root / rel).resolve()

    @property
    def md_files(self) -> list[str]:
        if self._md_files is not None:
            return self._md_files
        found: list[str] = []
        try:
            candidates = sorted(self.root.rglob("*.md"))
        except OSError:
            candidates = []
        for path in candidates:
            try:
                rel = path.relative_to(self.root).as_posix()
            except ValueError:
                continue
            if self._is_excluded(rel):
                continue
            found.append(rel)
        self._md_files = found
        return found

    @staticmethod
    def _is_excluded(rel: str) -> bool:
        parts = rel.split("/")
        if parts[:2] == ["docs", "archive"]:
            return True
        if tuple(parts[:2]) in LOCAL_EVAL_DIRS:
            return True
        for part in parts[:-1]:
            if part in EXCLUDED_DIR_NAMES:
                return True
        return False


def read_yaml_file(path: Path) -> tuple[object | None, str, str | None]:
    if yaml is None:
        return None, "", "PyYAML 未安装"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, "", f"文件不存在或不可读: {exc}"
    try:
        return yaml.safe_load(text), text, None
    except yaml.YAMLError as exc:
        return None, text, f"YAML 解析失败: {exc}"


def parse_frontmatter(text: str) -> tuple[dict | None, str, str | None]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, text, "文件不以 --- 开头"
    end = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end = idx
            break
    if end is None:
        return None, text, "frontmatter 没有结束的 ---"
    if yaml is None:
        return None, text, "PyYAML 未安装"
    raw = "\n".join(lines[1:end])
    try:
        meta = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return None, "\n".join(lines[end + 1 :]), f"YAML 解析失败: {exc}"
    if not isinstance(meta, dict):
        return None, "\n".join(lines[end + 1 :]), "frontmatter 必须是 YAML 映射"
    return meta, "\n".join(lines[end + 1 :]), None


def blank_non_newline(text: str) -> str:
    return re.sub(r"[^\n]", " ", text)


def mask_inline_code(line: str) -> str:
    chars = list(line)
    i = 0
    while i < len(line):
        if line[i] != "`":
            i += 1
            continue
        j = i
        while j < len(line) and line[j] == "`":
            j += 1
        ticks = line[i:j]
        close = line.find(ticks, j)
        if close == -1:
            i = j
            continue
        for pos in range(i, close + len(ticks)):
            if chars[pos] != "\n":
                chars[pos] = " "
        i = close + len(ticks)
    return "".join(chars)


def fence_marker(line: str) -> tuple[str, int, str] | None:
    stripped = line.lstrip(" ")
    if len(line) - len(stripped) > 3:
        return None
    match = re.match(r"^(`{3,}|~{3,})(.*)$", stripped.rstrip("\r\n"))
    if not match:
        return None
    marker = match.group(1)
    rest = match.group(2)
    if marker[0] == "`" and "`" in rest:
        return None
    return marker[0], len(marker), rest


def mask_code(text: str) -> str:
    out: list[str] = []
    fence: tuple[str, int] | None = None
    for line in text.splitlines(keepends=True):
        marker = fence_marker(line)
        if fence is not None:
            out.append(blank_non_newline(line))
            if (
                marker is not None
                and marker[0] == fence[0]
                and marker[1] >= fence[1]
                and marker[2].strip() == ""
            ):
                fence = None
            continue
        if marker is not None:
            fence = (marker[0], marker[1])
            out.append(blank_non_newline(line))
            continue
        out.append(mask_inline_code(line))
    text = "".join(out)
    return re.sub(
        r"<!--.*?-->", lambda m: blank_non_newline(m.group(0)), text, flags=re.DOTALL
    )


def iter_headings(text: str):
    fence: tuple[str, int] | None = None
    for lineno, line in enumerate(text.splitlines(), 1):
        marker = fence_marker(line)
        if fence is not None:
            if (
                marker is not None
                and marker[0] == fence[0]
                and marker[1] >= fence[1]
                and marker[2].strip() == ""
            ):
                fence = None
            continue
        if marker is not None:
            fence = (marker[0], marker[1])
            continue
        match = re.match(r"^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if match:
            yield lineno, len(match.group(1)), match.group(2).strip()


def render_heading_text(heading: str) -> str:
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\[[^\]]*\]", r"\1", text)
    text = re.sub(r"`+([^`]*)`+", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"~~(.*?)~~", r"\1", text)
    text = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"\\(.)", r"\1", text)
    return text.strip()


def github_slug(heading: str) -> str:
    text = render_heading_text(heading).lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return text.replace(" ", "-")


def document_anchors(text: str) -> set[str]:
    anchors: set[str] = set()
    for _, _, heading in iter_headings(text):
        base = github_slug(heading)
        candidate = base
        bump = 0
        while candidate in anchors:
            bump += 1
            candidate = f"{base}-{bump}"
        anchors.add(candidate)
    masked = mask_code(text)
    masked = re.sub(
        r"<!--.*?-->", lambda m: blank_non_newline(m.group(0)), masked, flags=re.DOTALL
    )
    for match in HTML_ANCHOR_RE.finditer(masked):
        anchors.add(match.group(1))
    return anchors


def iter_links(masked: str):
    for match in INLINE_LINK_RE.finditer(masked):
        target = match.group(1)
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        line = masked.count("\n", 0, match.start()) + 1
        yield target, line
    for match in REF_DEF_RE.finditer(masked):
        target = match.group(1)
        if target.startswith("<") and target.endswith(">"):
            target = target[1:-1]
        line = masked.count("\n", 0, match.start()) + 1
        yield target, line


def is_external_target(target: str) -> bool:
    if not target:
        return False
    if target.startswith("//") or target.startswith("/"):
        return True
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target))


def split_link_target(target: str) -> tuple[str, str | None]:
    path_part = target
    fragment: str | None = None
    if "#" in path_part:
        path_part, raw_fragment = path_part.split("#", 1)
        fragment = unquote(raw_fragment)
    path_part = path_part.split("?", 1)[0]
    return unquote(path_part), fragment


def first_line_with(text: str, needle: str) -> int:
    index = text.find(needle)
    return text.count("\n", 0, index) + 1 if index >= 0 else 1


def load_terms(repo: Repo) -> tuple[dict | None, Failure | None]:
    path = repo.root / "scripts/terms.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return None, Failure(
            "scripts/terms.json:1 不存在",
            "恢复 scripts/terms.json（术语清单的唯一事实源）；然后运行 "
            "python3 scripts/check.py --only glossary",
        )
    except json.JSONDecodeError as exc:
        return None, Failure(
            f"scripts/terms.json:1 JSON 解析失败: {exc}",
            "修复 scripts/terms.json 后运行 python3 scripts/check.py --only glossary",
        )
    if not isinstance(data, dict):
        return None, Failure(
            "scripts/terms.json:1 顶层必须是对象",
            "修复 scripts/terms.json 后运行 python3 scripts/check.py --only glossary",
        )
    for key in ("canonical", "banned_in_runtime", "banned_in_skill"):
        value = data.get(key)
        if (
            not isinstance(value, list)
            or not value
            or not all(isinstance(x, str) and x for x in value)
        ):
            return None, Failure(
                f"scripts/terms.json:1 的 {key} 必须是非空字符串列表",
                "修复 scripts/terms.json 后运行 python3 scripts/check.py --only glossary",
            )
    return data, None


def yaml_section_lines(text: str, section: str) -> list[int]:
    if yaml is None:
        return []
    try:
        node = yaml.compose(text)
    except yaml.YAMLError:
        return []
    from yaml.nodes import MappingNode, SequenceNode

    if not isinstance(node, MappingNode):
        return []
    for key, value in node.value:
        if getattr(key, "value", None) == section and isinstance(value, SequenceNode):
            return [item.start_mark.line + 1 for item in value.value]
    return []


def validate_cases_data(
    data: object, case_lines: list[int]
) -> list[tuple[int, str]]:
    issues: list[tuple[int, str]] = []
    if not isinstance(data, dict):
        return [(1, "顶层必须是 YAML 映射")]
    cases = data.get("cases")
    if not isinstance(cases, list):
        return [(1, "顶层必须含 cases 列表")]
    if not 1 <= len(cases) <= 20:
        issues.append((1, f"cases 数量 {len(cases)} 不在 1–20 条"))

    required = ("id", "input", "expect", "why")
    seen: set[str] = set()
    for index, case in enumerate(cases):
        line = case_lines[index] if index < len(case_lines) else 1
        if not isinstance(case, dict):
            issues.append((line, f"第 {index + 1} 条 case 必须是映射"))
            continue
        for key in required:
            if key not in case:
                issues.append((line, f"第 {index + 1} 条 case 缺少字段 {key}"))
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id.strip():
            issues.append((line, f"第 {index + 1} 条 case 的 id 必须是非空字符串"))
        elif case_id in seen:
            issues.append((line, f"id 重复: {case_id}"))
        else:
            seen.add(case_id)
        for key in ("input", "expect", "why"):
            value = case.get(key)
            if not isinstance(value, str) or not value.strip():
                issues.append((line, f"第 {index + 1} 条 case 的 {key} 必须是非空字符串"))
        background = case.get("bg")
        if background is not None and (
            not isinstance(background, str) or not background.strip()
        ):
            issues.append((line, f"第 {index + 1} 条 case 的 bg 必须是非空字符串"))
        review = case.get("review")
        if review is not None:
            if not isinstance(review, list) or not all(
                isinstance(item, str) and item.strip() for item in review
            ):
                issues.append(
                    (line, f"第 {index + 1} 条 case 的 review 必须是非空字符串列表")
                )
        reference = case.get("reference")
        if reference is not None:
            if not isinstance(reference, dict) or not reference:
                issues.append(
                    (line, f"第 {index + 1} 条 case 的 reference 必须是非空映射")
                )
            else:
                for key, value in reference.items():
                    if not isinstance(key, str) or not key.strip():
                        issues.append(
                            (line, f"第 {index + 1} 条 case 的 reference 键必须是非空字符串")
                        )
                    if not isinstance(value, str) or not value.strip():
                        issues.append(
                            (line, f"第 {index + 1} 条 case 的 reference[{key}] 必须是非空字符串")
                        )
                    elif value.startswith("/") or ".." in value.split("/"):
                        issues.append(
                            (line, f"第 {index + 1} 条 case 的 reference[{key}] 必须是相对路径")
                        )
        for key in ("must_match", "must_not_match"):
            patterns = case.get(key, [])
            if not isinstance(patterns, list) or not all(
                isinstance(p, str) for p in patterns
            ):
                issues.append((line, f"第 {index + 1} 条 case 的 {key} 必须是字符串列表"))
                continue
            for pattern in patterns:
                try:
                    re.compile(pattern, re.UNICODE)
                except re.error as exc:
                    issues.append((line, f"正则无法编译 {pattern!r}: {exc}"))
        if (
            not case.get("must_match")
            and not case.get("must_not_match")
            and not review
        ):
            issues.append(
                (line, f"第 {index + 1} 条 case 至少要有 must_match 或 review")
            )
        artifact_glob = case.get("artifact_glob")
        if artifact_glob is not None:
            if not isinstance(artifact_glob, str) or not artifact_glob.strip():
                issues.append(
                    (line, f"第 {index + 1} 条 case 的 artifact_glob 必须是非空字符串")
                )
            elif artifact_glob.startswith("/") or ".." in artifact_glob.split("/"):
                issues.append(
                    (line, f"第 {index + 1} 条 case 的 artifact_glob 必须是相对 glob")
                )
    return issues


def gate_frontmatter(repo: Repo) -> list[Failure]:
    failures: list[Failure] = []
    text = repo.text("SKILL.md")
    if text is None:
        return [
            Failure(
                "SKILL.md:1 不存在或不是 UTF-8",
                "创建 SKILL.md 后运行 python3 scripts/check.py --only frontmatter",
            )
        ]
    meta, _, error = parse_frontmatter(text)
    if error is not None or meta is None:
        return [
            Failure(
                f"SKILL.md:1 frontmatter 无法解析: {error}",
                "修正 SKILL.md 开头由 --- 包围的 YAML；然后运行 "
                "python3 scripts/check.py --only frontmatter",
            )
        ]
    fix_cmd = "python3 scripts/check.py --only frontmatter"

    extras = sorted(set(meta) - ALLOWED_FRONTMATTER_KEYS)
    if extras:
        failures.append(
            Failure(
                f"SKILL.md:1 顶层字段不在允许集合内: {', '.join(extras)}",
                f"删除多余字段或改用 metadata；然后运行 {fix_cmd}",
            )
        )
    missing = sorted(ALLOWED_FRONTMATTER_KEYS - set(meta))
    if missing:
        failures.append(
            Failure(
                f"SKILL.md:1 缺少顶层字段: {', '.join(missing)}",
                f"补齐字段；然后运行 {fix_cmd}",
            )
        )

    name = meta.get("name")
    expected_name = repo.root.name
    if name != expected_name:
        failures.append(
            Failure(
                f"SKILL.md:{first_line_with(text, 'name:')} name={name!r} "
                f"不等于目录名 {expected_name!r}",
                f"把 name 改为 {expected_name}；然后运行 {fix_cmd}",
            )
        )

    description = meta.get("description")
    desc_line = first_line_with(text, "description:")
    if not isinstance(description, str):
        failures.append(
            Failure(
                f"SKILL.md:{desc_line} description 必须是字符串",
                f"写入 40–400 字符的 description；然后运行 {fix_cmd}",
            )
        )
    elif not 40 <= len(description) <= 400:
        failures.append(
            Failure(
                f"SKILL.md:{desc_line} description 长度 {len(description)} 不在 40–400 字符",
                f"压缩或补足 description；然后运行 {fix_cmd}",
            )
        )

    allowed = meta.get("allowed-tools")
    tools_line = first_line_with(text, "allowed-tools:")
    if not isinstance(allowed, str):
        failures.append(
            Failure(
                f"SKILL.md:{tools_line} allowed-tools 必须是逗号分隔字符串",
                f"改成 Read,Grep,Glob,Bash 之一集合；然后运行 {fix_cmd}",
            )
        )
    else:
        tools = [item.strip() for item in allowed.split(",")]
        if any(not item for item in tools):
            failures.append(
                Failure(
                    f"SKILL.md:{tools_line} allowed-tools 含空项",
                    f"去掉多余逗号；然后运行 {fix_cmd}",
                )
            )
        unknown = sorted(set(tools) - ALLOWED_TOOLS - {""})
        if unknown:
            failures.append(
                Failure(
                    f"SKILL.md:{tools_line} allowed-tools 含未知工具: {', '.join(unknown)}",
                    f"只保留 {', '.join(sorted(ALLOWED_TOOLS))}；然后运行 {fix_cmd}",
                )
            )

    metadata = meta.get("metadata")
    if not isinstance(metadata, dict):
        failures.append(
            Failure(
                "SKILL.md:1 metadata 必须是映射",
                f"补齐 metadata.category/tags/version；然后运行 {fix_cmd}",
            )
        )
        metadata = {}

    category = metadata.get("category")
    if not isinstance(category, str) or not category.strip():
        failures.append(
            Failure(
                "SKILL.md:1 metadata.category 必须是非空字符串",
                f"写入 category；然后运行 {fix_cmd}",
            )
        )

    tags = metadata.get("tags")
    if (
        not isinstance(tags, list)
        or not tags
        or not all(isinstance(tag, str) and tag.strip() for tag in tags)
    ):
        failures.append(
            Failure(
                "SKILL.md:1 metadata.tags 必须是非空字符串列表",
                f"补齐 tags；然后运行 {fix_cmd}",
            )
        )

    version = metadata.get("version")
    version_text = repo.text("VERSION")
    if version_text is None:
        failures.append(
            Failure(
                "VERSION:1 文件不存在",
                f"写入版本号；然后运行 {fix_cmd}",
            )
        )
    elif version != version_text.strip():
        failures.append(
            Failure(
                f"SKILL.md:1 metadata.version={version!r} 与 VERSION={version_text.strip()!r} 不一致",
                f"同步两处版本号；然后运行 {fix_cmd}",
            )
        )
    return failures


def gate_structure(repo: Repo) -> list[Failure]:
    text = repo.text("SKILL.md")
    if text is None:
        return [
            Failure(
                "SKILL.md:1 不存在或不是 UTF-8",
                "创建 SKILL.md 后运行 python3 scripts/check.py --only structure",
            )
        ]
    fix_cmd = "python3 scripts/check.py --only structure"
    headings = list(iter_headings(text))
    h1 = [(line, value) for line, level, value in headings if level == 1]
    h2 = [(line, value) for line, level, value in headings if level == 2]
    failures: list[Failure] = []

    if [value for _, value in h1] != [EXPECTED_H1]:
        actual = ", ".join(value for _, value in h1) or "无"
        failures.append(
            Failure(
                f"SKILL.md:{h1[0][0] if h1 else 1} 一级标题必须是 # {EXPECTED_H1}，实际: {actual}",
                f"修正一级标题；然后运行 {fix_cmd}",
            )
        )

    actual_h2 = [value for _, value in h2]
    missing = [value for value in EXPECTED_H2 if value not in actual_h2]
    extra = [value for value in actual_h2 if value not in EXPECTED_H2]
    for value in missing:
        failures.append(
            Failure(
                f"SKILL.md:1 缺少二级标题: ## {value}",
                f"按顺序补上 ## {value}；然后运行 {fix_cmd}",
            )
        )
    for value in extra:
        line = next(line for line, heading in h2 if heading == value)
        failures.append(
            Failure(
                f"SKILL.md:{line} 出现未允许的二级标题: ## {value}",
                f"删除或降级该标题；然后运行 {fix_cmd}",
            )
        )
    if not missing and not extra and actual_h2 != list(EXPECTED_H2):
        failures.append(
            Failure(
                "SKILL.md:1 二级标题顺序与规定不一致",
                f"按 {' → '.join(EXPECTED_H2)} 重排；然后运行 {fix_cmd}",
            )
        )

    line_count = len(text.splitlines())
    for value in EXPECTED_H2:
        found = next(((line, idx) for idx, (line, heading) in enumerate(h2) if heading == value), None)
        if found is None:
            continue
        line, idx = found
        start = line
        end = h2[idx + 1][0] - 1 if idx + 1 < len(h2) else line_count
        has_content = any(
            text.splitlines()[pos - 1].strip() for pos in range(start + 1, end + 1)
        )
        if not has_content:
            failures.append(
                Failure(
                    f"SKILL.md:{line} 标题 ## {value} 下没有非空内容",
                    f"补一行可执行内容；然后运行 {fix_cmd}",
                )
            )
    return failures


def gate_budget(repo: Repo) -> list[Failure]:
    path = repo.root / "scripts/budget.json"
    try:
        budgets = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return [
            Failure(
                "scripts/budget.json:1 不存在",
                "恢复 scripts/budget.json 后运行 python3 scripts/check.py --only budget",
            )
        ]
    except json.JSONDecodeError as exc:
        return [
            Failure(
                f"scripts/budget.json:1 JSON 解析失败: {exc}",
                "修复 budget.json 后运行 python3 scripts/check.py --only budget",
            )
        ]
    if not isinstance(budgets, dict) or not budgets:
        return [
            Failure(
                "scripts/budget.json:1 未配置任何预算",
                "写入预算 glob 后运行 python3 scripts/check.py --only budget",
            )
        ]

    fix_cmd = "python3 scripts/check.py --only budget"
    failures: list[Failure] = []
    checked: set[str] = set()
    total_files = 0

    for pattern, limits in budgets.items():
        if not isinstance(limits, dict):
            failures.append(
                Failure(
                    f"scripts/budget.json:1 的 {pattern} 必须是 {{lines, chars}} 对象",
                    f"修正预算配置后运行 {fix_cmd}",
                )
            )
            continue
        line_limit = limits.get("lines")
        char_limit = limits.get("chars")
        if (
            not isinstance(line_limit, int)
            or line_limit <= 0
            or not isinstance(char_limit, int)
            or char_limit <= 0
        ):
            failures.append(
                Failure(
                    f"scripts/budget.json:1 的 {pattern} 上限必须是正整数",
                    f"修正预算配置后运行 {fix_cmd}",
                )
            )
            continue

        matches = sorted(
            (p for p in repo.root.glob(pattern) if p.is_file()),
            key=lambda p: p.as_posix(),
        )
        matches = [
            p
            for p in matches
            if p.relative_to(repo.root).as_posix() not in {"CHANGELOG.md"}
            and not p.relative_to(repo.root).as_posix().startswith("docs/archive/")
        ]
        if not matches and not any(ch in pattern for ch in "*?["):
            failures.append(
                Failure(
                    f"{pattern}:1 预算文件不存在",
                    f"创建 {pattern} 或修正 budget.json；然后运行 {fix_cmd}",
                )
            )
        for match in matches:
            rel = match.relative_to(repo.root).as_posix()
            if rel in checked:
                continue
            checked.add(rel)
            total_files += 1
            try:
                text = match.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                failures.append(
                    Failure(
                        f"{rel} 无法读取: {exc}",
                        f"确认文件为 UTF-8；然后运行 {fix_cmd}",
                    )
                )
                continue
            lines = len(text.splitlines())
            chars = len(text)
            over = lines > line_limit or chars > char_limit
            if over:
                failures.append(
                    Failure(
                        f"{rel}:1 {lines} 行 / {chars} 字符，超过上限 "
                        f"{line_limit} 行 / {char_limit} 字符",
                        "把细节搬到 references/ 或压缩；提上限需在 PR 说明理由；然后运行 "
                        f"{fix_cmd}",
                    )
                )
                continue
            for label, value, limit in (
                ("lines", lines, line_limit),
                ("chars", chars, char_limit),
            ):
                if value * 10 >= limit * 9:
                    percent = value * 100 / limit
                    print(
                        f"WARN budget: {rel} {label} {value}/{limit} ({percent:.1f}%)",
                        file=sys.stderr,
                    )

    if total_files == 0:
        failures.append(
            Failure(
                "预算 gate 未扫描到任何文件，拒绝通过",
                f"补齐预算文件后运行 {fix_cmd}",
            )
        )
    return failures


def gate_links(repo: Repo) -> list[Failure]:
    files = repo.md_files
    if not files:
        return [
            Failure(
                "扫描到 0 个 Markdown 文件，链接 gate 拒绝通过",
                "补齐 Markdown 语料后运行 python3 scripts/check.py --only links",
            )
        ]
    fix_cmd = "python3 scripts/check.py --only links"
    failures: list[Failure] = []
    anchor_cache: dict[Path, set[str]] = {}

    for rel in files:
        text = repo.text(rel)
        if text is None:
            failures.append(
                Failure(
                    f"{rel}:1 无法读取或不是 UTF-8",
                    f"确认文件编码后运行 {fix_cmd}",
                )
            )
            continue
        source = repo.abs(rel)
        masked = mask_code(text)
        for raw_target, line in iter_links(masked):
            target = raw_target.strip()
            if not target or is_external_target(target):
                continue
            path_part, fragment = split_link_target(target)
            if path_part == "":
                target_path = source
            else:
                target_path = (source.parent / path_part).resolve()
            if not target_path.exists():
                shown = (
                    target_path.relative_to(repo.root).as_posix()
                    if target_path.is_relative_to(repo.root)
                    else str(target_path)
                )
                failures.append(
                    Failure(
                        f"{rel}:{line} 链接目标不存在: {target}（解析为 {shown}）",
                        f"创建 {shown}，或修正 {rel}:{line} 的链接；然后运行 {fix_cmd}",
                    )
                )
                continue
            if not fragment:
                continue
            if target_path.suffix.lower() != ".md":
                continue
            if target_path not in anchor_cache:
                try:
                    target_text = target_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError) as exc:
                    failures.append(
                        Failure(
                            f"{rel}:{line} 锚点目标无法读取: {target}（{exc}）",
                            f"确认目标文件为 UTF-8；然后运行 {fix_cmd}",
                        )
                    )
                    continue
                anchor_cache[target_path] = document_anchors(target_text)
            if fragment not in anchor_cache[target_path]:
                failures.append(
                    Failure(
                        f"{rel}:{line} 锚点不存在: {target}（目标文档没有 slug "
                        f"{fragment!r} 或 <a id>）",
                        "修正 fragment 或给目标标题加显式 <a id>；标题 slug 规则："
                        f"小写、去标点、空格转 -；然后运行 {fix_cmd}",
                    )
                )
    return failures


def gate_refs(repo: Repo) -> list[Failure]:
    fix_cmd = "python3 scripts/check.py --only refs"
    failures: list[Failure] = []
    skill = repo.text("SKILL.md")
    if skill is None:
        failures.append(
            Failure(
                "SKILL.md:1 不存在或不是 UTF-8",
                f"创建 SKILL.md 后运行 {fix_cmd}",
            )
        )

    ref_paths = sorted((repo.root / "references").glob("*.md"))
    if not ref_paths:
        failures.append(
            Failure(
                "references/:1 下没有 Markdown 文件，无法验证引用关系",
                f"补齐 references/*.md 后运行 {fix_cmd}",
            )
        )
    if skill is not None:
        for path in ref_paths:
            rel = path.relative_to(repo.root).as_posix()
            count = skill.count(rel)
            if count != 1:
                failures.append(
                    Failure(
                        f"SKILL.md:1 {rel} 被引用 {count} 次，必须恰好 1 次",
                        f"在 SKILL.md §7 按需加载表中只保留一处 {rel}；然后运行 {fix_cmd}",
                    )
                )

    for rel in ("SKILL.md", "AGENTS.md"):
        text = repo.text(rel)
        if text is None:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for match in PATH_MENTION_RE.finditer(line):
                mentioned = match.group(1).rstrip(".,;:，。、")
                if mentioned.endswith("//"):
                    continue
                if not (repo.root / mentioned).exists():
                    failures.append(
                        Failure(
                            f"{rel}:{lineno} 引用的路径不存在: {mentioned}",
                            f"创建 {mentioned} 或修正引用；然后运行 {fix_cmd}",
                        )
                    )

    design = repo.text("docs/design.md")
    decision_paths = sorted((repo.root / "docs/decisions").glob("*.md"))
    if design is not None:
        masked = mask_code(design)
        design_abs = repo.abs("docs/design.md")
        resolved: set[Path] = set()
        for raw_target, _ in iter_links(masked):
            target = raw_target.strip()
            if not target or is_external_target(target):
                continue
            path_part, _ = split_link_target(target)
            if not path_part:
                continue
            resolved.add((design_abs.parent / path_part).resolve())
        for path in decision_paths:
            rel = path.relative_to(repo.root).as_posix()
            linked = path.resolve() in resolved
            if not linked:
                failures.append(
                    Failure(
                        f"docs/design.md:1 未链接 {rel}",
                        f"在 docs/design.md 加一处指向 {rel} 的链接；然后运行 {fix_cmd}",
                    )
                )
    return failures


def gate_decisions(repo: Repo) -> list[Failure]:
    fix_cmd = "python3 scripts/check.py --only decisions"
    directory = repo.root / "docs/decisions"
    paths = sorted(directory.glob("*.md")) if directory.is_dir() else []
    if not paths:
        return [
            Failure(
                "docs/decisions/:1 下没有决策记录",
                f"补齐 0001–0006 的 ADR 后运行 {fix_cmd}",
            )
        ]
    failures: list[Failure] = []
    numbers: list[int] = []
    for path in paths:
        rel = path.relative_to(repo.root).as_posix()
        match = DECISION_FILENAME_RE.match(path.name)
        if not match:
            failures.append(
                Failure(
                    f"{rel}:1 文件名不符合 ^\\d{{4}}-[a-z0-9-]+\\.md$",
                    f"重命名该文件；然后运行 {fix_cmd}",
                )
            )
            continue
        number = int(path.name[:4])
        numbers.append(number)
        text = repo.text(rel)
        if text is None:
            failures.append(
                Failure(f"{rel}:1 无法读取或不是 UTF-8", f"确认编码后运行 {fix_cmd}")
            )
            continue
        lines = text.splitlines()
        first = lines[0] if lines else ""
        heading = DECISION_HEADING_RE.match(first)
        if not heading:
            failures.append(
                Failure(
                    f"{rel}:1 首行必须是 # <编号> <标题>，实际: {first!r}",
                    f"修正首行；然后运行 {fix_cmd}",
                )
            )
        elif int(heading.group(1)) != number:
            failures.append(
                Failure(
                    f"{rel}:1 首行编号 {heading.group(1)} 与文件名编号 {number:04d} 不一致",
                    f"统一编号；然后运行 {fix_cmd}",
                )
            )
        status_line = next(
            (idx for idx, line in enumerate(lines[:6], 1) if "- 状态：已接受" in line),
            None,
        )
        if status_line is None:
            failures.append(
                Failure(
                    f"{rel}:1 前 6 行缺少 - 状态：已接受",
                    f"在标题后补状态行；然后运行 {fix_cmd}",
                )
            )
        heading_map = {
            value: (line, level) for line, level, value in iter_headings(text)
        }
        for required in ("问题", "决策", "备选方案", "后果"):
            entry = heading_map.get(required)
            if entry is None or entry[1] != 2:
                failures.append(
                    Failure(
                        f"{rel}:1 缺少 ## {required}",
                        f"补齐 ## {required}；然后运行 {fix_cmd}",
                    )
                )
        if "备选方案" in heading_map and heading_map["备选方案"][1] == 2:
            start = heading_map["备选方案"][0]
            end = len(lines)
            for line, level, value in iter_headings(text):
                if line > start and level <= 2:
                    end = line - 1
                    break
            entries = sum(
                1
                for line in lines[start:end]
                if re.match(r"^\s*-\s+", line)
            )
            if entries < 2:
                failures.append(
                    Failure(
                        f"{rel}:{start} ## 备选方案 下只有 {entries} 个条目，至少 2 个",
                        f"补足 - 条目；然后运行 {fix_cmd}",
                    )
                )

    if numbers:
        expected = list(range(1, len(numbers) + 1))
        if sorted(numbers) != expected:
            duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
            detail = (
                f"重复编号: {', '.join(f'{n:04d}' for n in duplicates)}"
                if duplicates
                else f"实际 {', '.join(f'{n:04d}' for n in sorted(numbers))}"
            )
            failures.append(
                Failure(
                    f"docs/decisions:1 决策编号必须从 0001 连续且唯一；{detail}",
                    f"重排编号为 0001–{len(numbers):04d}；然后运行 {fix_cmd}",
                )
            )
    return failures


def gate_version(repo: Repo) -> list[Failure]:
    fix_cmd = "python3 scripts/check.py --only version"
    failures: list[Failure] = []
    version_text = repo.text("VERSION")
    version: str | None = None
    if version_text is None:
        failures.append(
            Failure("VERSION:1 文件不存在", f"写入版本号；然后运行 {fix_cmd}")
        )
    else:
        version = version_text.strip()
        if not SEMVER_RE.match(version):
            failures.append(
                Failure(
                    f"VERSION:1 内容 {version!r} 不是 semver（X.Y.Z）",
                    f"改成 X.Y.Z；然后运行 {fix_cmd}",
                )
            )
            version = None

    changelog = repo.text("CHANGELOG.md")
    if changelog is None:
        failures.append(
            Failure("CHANGELOG.md:1 不存在", f"创建 CHANGELOG.md；然后运行 {fix_cmd}")
        )
    elif version is not None and f"## [{version}]" not in changelog:
        failures.append(
            Failure(
                f"CHANGELOG.md:1 缺少 ## [{version}] 条目",
                f"补该版本条目；然后运行 {fix_cmd}",
            )
        )

    skill = repo.text("SKILL.md")
    if skill is None:
        failures.append(
            Failure("SKILL.md:1 不存在", f"创建 SKILL.md；然后运行 {fix_cmd}")
        )
    else:
        meta, _, error = parse_frontmatter(skill)
        if error is not None or meta is None:
            failures.append(
                Failure(
                    f"SKILL.md:1 frontmatter 无法解析: {error}",
                    f"修正 frontmatter；然后运行 {fix_cmd}",
                )
            )
        else:
            metadata = meta.get("metadata")
            embedded = metadata.get("version") if isinstance(metadata, dict) else None
            if version is not None and embedded != version:
                failures.append(
                    Failure(
                        f"SKILL.md:1 metadata.version={embedded!r} 与 VERSION={version!r} 不一致",
                        f"同步版本号；然后运行 {fix_cmd}",
                    )
                )
    return failures


def gate_glossary(repo: Repo) -> list[Failure]:
    fix_cmd = "python3 scripts/check.py --only glossary"
    terms, terms_error = load_terms(repo)
    if terms_error is not None:
        return [terms_error]
    assert terms is not None

    failures: list[Failure] = []
    glossary = repo.text("docs/glossary.md")
    has_glossary = glossary is not None
    if glossary is None:
        failures.append(
            Failure(
                "docs/glossary.md:1 不存在或不是 UTF-8",
                f"创建术语表；然后运行 {fix_cmd}",
            )
        )
        glossary = ""
    elif not GLOSSARY_HEADER_RE.search(glossary):
        failures.append(
            Failure(
                "docs/glossary.md:1 缺少表头 | 术语 | 定义 | 不要写成 |",
                f"补表头；然后运行 {fix_cmd}",
            )
        )

    first_cells: list[str] = []
    for line in glossary.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if cells:
            first_cells.append(cells[0])

    ref_texts = []
    for path in sorted((repo.root / "references").glob("*.md")):
        text = repo.text(path.relative_to(repo.root).as_posix())
        if text:
            ref_texts.append(text)
    runtime_text = "\n".join(filter(None, [repo.text("SKILL.md"), *ref_texts]))

    for term in terms["canonical"]:
        if has_glossary and not any(term in cell for cell in first_cells):
            failures.append(
                Failure(
                    f"docs/glossary.md:1 表格缺少规范术语「{term}」",
                    f"在表格首列加入该术语；然后运行 {fix_cmd}",
                )
            )
        if term not in runtime_text:
            failures.append(
                Failure(
                    f"SKILL.md:1 规范术语「{term}」未出现在 SKILL.md 或 references/",
                    f"在运行时文件中使用该术语，或从 terms.json 移除；然后运行 {fix_cmd}",
                )
            )

    runtime_files = ["SKILL.md", *(
        path.relative_to(repo.root).as_posix()
        for path in sorted((repo.root / "references").glob("*.md"))
    )]
    for rel in runtime_files:
        text = repo.text(rel)
        if text is None:
            continue
        for banned in terms["banned_in_runtime"]:
            if banned in text:
                line = first_line_with(text, banned)
                failures.append(
                    Failure(
                        f"{rel}:{line} 出现运行时禁用词「{banned}」",
                        f"删掉该词或改用规范术语（见 docs/glossary.md）；然后运行 {fix_cmd}",
                    )
                )

    skill = repo.text("SKILL.md")
    if skill is not None:
        for banned in terms["banned_in_skill"]:
            if banned in skill:
                line = first_line_with(skill, banned)
                failures.append(
                    Failure(
                        f"SKILL.md:{line} 出现模糊词「{banned}」",
                        f"删除该词或改成可判定表述；然后运行 {fix_cmd}",
                    )
                )
    return failures


def gate_corpus(repo: Repo) -> list[Failure]:
    fix_cmd = "python3 scripts/check.py --only corpus"
    failures: list[Failure] = []
    files = repo.md_files
    if len(files) < 8:
        failures.append(
            Failure(
                f"参与扫描的 Markdown 只有 {len(files)} 个，少于 8 个",
                f"补齐文档与引用后运行 {fix_cmd}",
            )
        )
    for rel in REQUIRED_CORPUS_FILES:
        if not (repo.root / rel).is_file():
            failures.append(
                Failure(
                    f"{rel}:1 必需文件不存在",
                    f"创建 {rel} 后运行 {fix_cmd}",
                )
            )
    return failures


GATES: tuple[tuple[str, str, object], ...] = (
    ("frontmatter", "SKILL.md frontmatter 字段、name、description、allowed-tools、metadata", gate_frontmatter),
    ("structure", "SKILL.md 一级/二级标题与各节非空", gate_structure),
    ("budget", "按 scripts/budget.json 检查行数与字符数", gate_budget),
    ("links", "全仓相对链接与标题锚点可解析", gate_links),
    ("refs", "references 恰好引用一次、路径存在、ADR 被 design 链接", gate_refs),
    ("decisions", "docs/decisions 命名、编号、状态与章节", gate_decisions),
    ("version", "VERSION、CHANGELOG、SKILL metadata.version 一致", gate_version),
    ("glossary", "术语表覆盖规范术语且运行时无禁用词", gate_glossary),
    ("corpus", "Markdown 语料 >= 8 且必需文件存在", gate_corpus),
)


def gate_by_id(gate_id: str):
    for gate in GATES:
        if gate[0] == gate_id:
            return gate
    return None


def run_gates(repo: Repo, selected: list[tuple[str, str, object]]) -> int:
    failures: list[tuple[str, Failure]] = []
    for gate_id, _, func in selected:
        try:
            found = func(repo)
        except Exception as exc:
            found = [
                Failure(
                    f"内部错误: {type(exc).__name__}: {exc}",
                    f"保留完整报错并运行 python3 scripts/check.py --only {gate_id}",
                )
            ]
        for failure in found:
            failures.append((gate_id, failure))

    for gate_id, failure in failures:
        print(f"FAIL {gate_id}: {failure.message}", file=sys.stderr)
        print(f"  修复: {failure.fix}", file=sys.stderr)

    if failures:
        print(
            f"\n{len(failures)} 个失败；修复后重跑 python3 scripts/check.py --all",
            file=sys.stderr,
        )
        return 1

    if len(selected) == 1:
        print(f"OK {selected[0][0]} gate, {len(repo.md_files)} files")
    else:
        print(f"OK {len(selected)} gates, {len(repo.md_files)} files")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="open-problem-method 结构门禁",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--all", action="store_true", help="运行全部 gate（默认）")
    mode.add_argument("--list", action="store_true", help="列出 gate id 与一行说明")
    mode.add_argument("--only", metavar="ID", help="只运行一个 gate")
    parser.add_argument(
        "--root",
        metavar="PATH",
        default=str(Path(__file__).resolve().parent.parent),
        help="仓库根目录（默认取脚本所在仓库）",
    )
    args = parser.parse_args(argv)

    if yaml is None:
        print(
            "FAIL setup: PyYAML 未安装\n  修复: python3 -m pip install pyyaml",
            file=sys.stderr,
        )
        return 2

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"FAIL setup: --root 不是目录: {root}", file=sys.stderr)
        return 2
    repo = Repo(root)

    if args.list:
        for gate_id, description, _ in GATES:
            print(f"{gate_id:<12} {description}")
        return 0

    if args.only:
        gate = gate_by_id(args.only)
        if gate is None:
            print(
                f"FAIL setup: 未知 gate id {args.only!r}\n"
                f"  修复: 运行 python3 scripts/check.py --list 查看可用 id",
                file=sys.stderr,
            )
            return 2
        return run_gates(repo, [gate])

    return run_gates(repo, list(GATES))


if __name__ == "__main__":
    sys.exit(main())
