# AGENTS.md

本仓库把 skill 提示词当作生产代码维护：运行时入口是 [SKILL.md](SKILL.md)，理由与诊断在 [docs/design.md](docs/design.md)，可检查的规则由 `scripts/check.py` 执行。改任何行为前先读 [docs/authoring.md](docs/authoring.md)。

## 命令

| 命令 | 作用 |
|---|---|
| `make check` | 运行全部 9 个结构门禁，即 `python3 scripts/check.py --all`；提交前必须通过 |
| `make test-gates` | 破坏每条规则，确认对应 gate 会失败；改过门禁后必须跑 |
| `make ci` | `make check` 加 `make test-gates`，与 CI 一致 |
| `make list` | 列出 gate id 与一行说明 |
| `make eval-plan` | 校验本机用例并打印将执行的命令，不调用模型；人工使用 |
| `make eval` | 运行本机行为用例并保存原始输出/思维链到 `evals/runs/`；需要 `opencode` CLI 与模型额度；只由人工运行，AI 不自动触发 |
| `make release` | 校验版本、打包 `dist/` 并做安装 smoke |
| `make hooks` | 安装 `.githooks/pre-commit` |

## 唯一事实源

| 事实 | 家 |
|---|---|
| 运行时指令、门禁表、输出契约 | [SKILL.md](SKILL.md) |
| 理由、v1 诊断、五条设计原则 | [docs/design.md](docs/design.md) |
| 版本产出流程、变更影响矩阵 | [docs/authoring.md](docs/authoring.md) |
| 发布步骤、产物、回滚 | [docs/releasing.md](docs/releasing.md) |
| gate 清单、预算、CI | [docs/verification.md](docs/verification.md) |
| 术语定义与禁用替代词 | [docs/glossary.md](docs/glossary.md) |
| 决策与被否决的备选方案 | [docs/decisions/](docs/decisions/) |

同一事实只写一处，其他位置只链接。

## 硬规则

1. 行为变更必须在本机 `evals/cases.yaml` 用例上手工验证；该文件含真实客户信息，已 gitignore，永不提交（流程见 [docs/authoring.md](docs/authoring.md)）。
2. 改门禁、步骤顺序或输出契约时，先在本机加或改用例并跑一次，再改 [SKILL.md](SKILL.md)，最后改文档与脚本。
3. eval 用例、历史存档 `evals/reference/` 与运行记录 `evals/runs/` 只在本机维护，AI 不自动运行 `make eval`，结果由人工逐条审查。
4. 新术语先写进 [docs/glossary.md](docs/glossary.md) 并同步 `scripts/terms.json`，再在正文使用。
5. 入口状态永远是「未判」，类型只能是探针的输出（[SKILL.md](SKILL.md) §1）。
6. 不引入并列路径模板，每条路径必须收敛到一个下一步（[SKILL.md](SKILL.md) §5）。
7. 预算超限按 搬迁 → 压缩 → 提上限 的顺序处理，提上限必须在 PR 写明理由（[docs/verification.md](docs/verification.md)）。
8. 破坏性变更必须在 [CHANGELOG.md](CHANGELOG.md) 的 Migration 段说明旧版如何迁移（[docs/releasing.md](docs/releasing.md)）。
9. `make check` 未通过不提交（[docs/verification.md](docs/verification.md)）。
10. [docs/archive/](docs/archive/) 冻结，不修改，也不作为当前事实源（[docs/authoring.md](docs/authoring.md)）。
11. 发布产物只含 [SKILL.md](SKILL.md)、[references/](references/)、[VERSION](VERSION)、[CHANGELOG.md](CHANGELOG.md) 与 `manifest.json`（[docs/releasing.md](docs/releasing.md)）。
12. 版本号：`major` 只在用户明确要求时升，其余变更只升 `patch`/`minor`；属 major 的变更未获授权时先做兼容或询问，不得用 minor 伪装（[docs/authoring.md](docs/authoring.md#版本语义)）。

## 编辑本文件

只放每次会话都必须知道的常驻规则，每条 1 到 3 行，细节链接到唯一 home。超限时先搬迁，再压缩，最后才提上限并在 PR 说明。

## 机器检查与人工评审

| 检查方式 | 覆盖 |
|---|---|
| `make check`（每次提交） | frontmatter、结构、预算、链接、引用、ADR 格式、版本、术语、语料，共 9 个 gate |
| `make test-gates`（门禁改动、CI） | 破坏每条规则，确认对应 gate 会失败，防止静默通过 |
| `make eval`（发布前，仅人工） | 本机用例输出由人工逐条审查；AI 不触发，结果不回写仓库 |
| 人工评审 | 语义质量、评测结果的解释、description 是否会在普通问题误触发 |
