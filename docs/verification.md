# 门禁与验证

单一入口：`python3 scripts/check.py --all`。`make check` 等于这条命令。`--list` 列 id 与一行说明，`--only <id>` 只跑一个 gate。

## 三层

| 层 | 何时跑 | 覆盖什么 | 入口 |
|---|---|---|---|
| 结构 | 每次提交 | 10 个 gate：文件形态、链接、术语、用例可解析 | `make check`、pre-commit、CI |
| 行为 | 发布前 | [evals/cases.yaml](../evals/cases.yaml) 的 8 条用例 | `make eval` |
| 人工 | 发布前 | 语义质量、评测差异解释、触发判断 | 评审清单，见 [authoring.md](authoring.md) |

结构层必须快：`make check` 在 1 秒内跑完，所以能挂在每次提交。行为层每条用例一次模型调用，只在发布前跑。人工评审不替代前两层，前两层也不替代人工评审。

## 十个 gate

所有 gate 独立执行，收集全部失败后统一输出，不 fail-fast。失败格式：

```
FAIL <id>: <文件:行号与原因>
  修复: <可复制的命令或动作>
```

| id | 检查什么 | 失败修复 |
|---|---|---|
| `frontmatter` | `SKILL.md` 以 `---` 开头；YAML 可解析；顶层字段仅 `name` `description` `allowed-tools` `metadata`；`name` 等于目录名；`description` 40-400 字符；`allowed-tools` 逗号分隔且都在允许集内；`metadata.category` 非空；`metadata.tags` 非空字符串列表；`metadata.version` 等于 `VERSION` | `python3 scripts/check.py --only frontmatter`，按 FAIL 行改字段；版本不一致时同步 `VERSION` 与 `metadata.version` |
| `structure` | 一级标题为 `# Open Problem Method`；8 个二级标题按序出现且各含至少 1 行内容 | `python3 scripts/check.py --only structure`，按缺失、多余、乱序三类分别补齐 |
| `budget` | 按 [scripts/budget.json](../scripts/budget.json) 检查行数与字符数；达到上限 90% 输出 `WARN budget` | `python3 scripts/check.py --only budget`；先搬迁到 `references/`，再压缩 |
| `links` | 除 `docs/archive/**` 外所有 `.md`；相对链接目标存在；`#fragment` 命中真实标题 slug；忽略 `http(s)://`、`mailto:` 与代码围栏 | `python3 scripts/check.py --only links`，按 FAIL 的 `文件:行号` 改路径或锚点 |
| `refs` | 每个 `references/*.md` 被 `SKILL.md` 恰好链接一次；`SKILL.md` 与 `AGENTS.md` 里的 `references/`、`docs/` 路径存在；每个 ADR 被 `docs/design.md` 链接 | `python3 scripts/check.py --only refs`，补链接或删死链 |
| `decisions` | 文件名 `NNNN-kebab.md`；编号从 0001 连续唯一；首行 `# <编号> <标题>`；前 6 行含 `- 状态：已接受`；含 `## 问题` `## 决策` `## 备选方案` `## 后果`；备选 ≥2 条 | `python3 scripts/check.py --only decisions`，按 FAIL 补齐结构或改编号 |
| `version` | `VERSION` 匹配 `^\d+\.\d+\.\d+$`；`CHANGELOG.md` 含 `## [<version>]`；`metadata.version` 一致 | `python3 scripts/check.py --only version`，三处对齐后重跑 |
| `glossary` | `docs/glossary.md` 含表头 `\| 术语 \| 定义 \| 不要写成 \|`；14 个规范术语都在表中，且至少出现在 `SKILL.md` 或 `references/` 之一；运行时文件不含禁用词 | `python3 scripts/check.py --only glossary`；缺术语补表，禁用词改规范词 |
| `evals` | `cases.yaml` 顶层 `cases:` 7-20 条；每条含 6 个必需字段，可选 `artifact_glob`；id 唯一；`must_match` 非空；正则全部可编译；`router_cases.yaml` 正负各 ≥3 且字段齐全 | `python3 scripts/check.py --only evals`；正则错误按 FAIL 给的行号修 |
| `corpus` | 参与扫描的 Markdown ≥8；`SKILL.md`、`AGENTS.md`、`docs/design.md`、`docs/authoring.md`、`docs/releasing.md`、`docs/verification.md`、`docs/glossary.md` 都存在 | `python3 scripts/check.py --only corpus`，补缺失文件；文件数不足时检查是否误删 |

### 语料守卫

`corpus` 兼作守卫：扫描到的 Markdown 少于 8 个直接失败。文件被误删、glob 写错、或从错误的根目录运行时，其余 gate 可能"全绿"，因为它们检查的是空集合。守卫把这种情况变成硬失败。

### 门禁自身的测试

门禁保护的是一个提示词文件，静默通过的 gate 比没有 gate 更危险。`python3 scripts/test_gates.py` 复制仓库，逐个破坏 10 条规则，断言对应 gate 退出非零且输出 `FAIL <id>`。

| 项 | 内容 |
|---|---|
| 覆盖 | 10 个 gate 各一条破坏：改名、删标题、超预算、断链、重命名参考文件、删 ADR 备选、改版本、删术语、坏正则、删必需文件 |
| 入口 | `make test-gates`；`make ci` 等于 `make check` 加它 |
| 不放进 pre-commit | 每次复制仓库并跑 11 次 gate，耗时高于单次 check；CI 与门禁改动时跑即可 |

它只证明 gate 会失败，不证明 gate 的判据正确。判据的正确性由 [authoring.md](authoring.md) 的影响矩阵与人工评审保证。

### 常用单跑

```sh
python3 scripts/check.py --list
python3 scripts/check.py --only links
python3 scripts/check.py --only version
python3 scripts/check.py --all
```

## 预算与 headroom

| 对象 | 行上限 | 字符上限 | 90% 预警线 |
|---|---|---|---|
| `SKILL.md` | 140 | 12000 | 126 行 / 10800 字符 |
| `AGENTS.md` | 90 | 7000 | 81 行 / 6300 字符 |
| `references/*.md` | 160 | 14000 | 144 行 / 12600 字符 |
| `docs/*.md` | 320 | 22000 | 288 行 / 19800 字符 |
| `docs/decisions/*.md` | 220 | 14000 | 198 行 / 12600 字符 |

预算不含 `docs/archive/**` 与 `CHANGELOG.md`：前者是冻结素材，后者按版本累积，都不该挤压当前内容。

规则：

- 达到上限 90% 只警告，不失败；发布时必须把用量压到 95% 以下，至少留 5% headroom 给下一个 patch。
- 连续两个版本在同一对象上出现 `WARN budget`，下一个 minor 必须先搬迁，不允许再提上限。
- 提上限是最后手段，且在变更记录里写明为什么搬迁和压缩都不够。
- 行数与字符数同时受限：只拆行不删字过不了字符检查，只删字不拆行过不了行数检查。

## 不自动化的部分

| 项 | 为什么机器判不了 | 谁来做 |
|---|---|---|
| 语义质量 | `must_match` 能证明某个词出现，不能证明台账真的可判定、下一步真的可执行 | 人工逐条读输出，对照 `SKILL.md` 的门禁 |
| 评测差异的解释 | 未命中可能是模型波动、提示词退步、或用例过严；机器只报哪条正则没命中 | 人工看原始输出后决定改提示词还是改用例 |
| 触发判断 | 真实用户措辞无穷，`router_cases.yaml` 只是样本；"该不该激活"本身是语义判断 | 人工抽样真实调用记录，检查漏触发与误触发 |

机器门禁通过只代表形态正确。把上面三项也写成 gate，会让门禁依赖主观打分，最终变成"看起来通过"。

## CI

[.github/workflows/check.yml](../.github/workflows/check.yml) 只有一个 job：

| 项 | 值 |
|---|---|
| 触发 | `pull_request`，以及 `push` 到 `main` |
| 运行环境 | Ubuntu，Python 3.12 |
| 依赖 | `pip install pyyaml` |
| 命令 | `python3 scripts/check.py --all` 与 `python3 scripts/test_gates.py` |
| 矩阵 | 无 |

`make eval` 不在默认 CI 里。它需要 opencode CLI 与模型额度，凭据不进 CI；行为评测是发布前本地门禁，由 [releasing.md](releasing.md) 的发布序列保证执行。CI 只回答一个问题：这次提交的结构是否仍然成立。

## 失败时的定位顺序

| 顺序 | 动作 | 目的 |
|---|---|---|
| 1 | `python3 scripts/check.py --only <id>` | 把范围缩到一个 gate，拿到具体文件行号 |
| 2 | 读 FAIL 行的"修复"提示 | 多数失败是路径、字段、编号这类机械问题 |
| 3 | `git diff` 对照 [authoring.md](authoring.md) 的影响矩阵 | 确认是否漏改了连锁文件 |
| 4 | `make check` 全量重跑 | 单 gate 通过不代表其它 gate 不受同一改动影响 |
| 5 | 行为用例失败时 `python3 scripts/run_evals.py --run --only <id>` | 拿到完整输出，区分模型波动与真实退步 |
