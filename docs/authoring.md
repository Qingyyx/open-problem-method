# 版本产出流程

本文件回答一个问题：下一个版本怎么产出。运行时入口是 [SKILL.md](../SKILL.md)，它才是唯一事实源；设计理由在 [design.md](design.md)，门禁细节在 [verification.md](verification.md)，发布动作在 [releasing.md](releasing.md)。

改任何行为前，先在本文件里找到对应的变更类型，再动手。

## 版本语义

| 版本位 | 触发条件 | 例子 |
|---|---|---|
| patch | 只改措辞、示例、错别字；门禁、探针、输出契约都不变 | 换一个反例的措辞 |
| minor | 新增门禁、探针或参考文件；输出契约与触发方式不变 | 加一条 P0 探针判据 |
| major | 触发方式、分类、输出契约、步骤顺序任一变化 | 六段模板改为缺口台账 |

判定顺序：输出契约变了就是 major；契约没变但门禁或探针有增删就是 minor；两者都没变才是 patch。版本号写进 [VERSION](../VERSION)，与 [CHANGELOG.md](../CHANGELOG.md) 的条目、`SKILL.md` 的 `metadata.version` 三者必须一致，由 `version` gate 检查。

**版本授权**：`major` 位只在用户明确要求「升大版本」时使用；日常维护只升 `patch` 或 `minor`。如果变更按上表属于 major 而用户未授权，不得用 minor 伪装：先做向后兼容，或停下来向用户确认。

## 六步流程

以"新增一条探针成本上限"为例。每一步都写明改哪个文件、跑哪条命令。

| 步 | 动作 | 文件 | 命令 |
|---|---|---|---|
| 1 | 写失败案例：一个具体输入，加上期望的可观测输出 | 草稿，放 `/tmp` | 无 |
| 2 | 先加用例：写入 `input` `expect` `must_match` `must_not_match` `why`；文档型用例加 `artifact_glob`，此时应失败 | [evals/cases.yaml](../evals/cases.yaml) | `python3 scripts/run_evals.py --plan` 校验 YAML；`python3 scripts/run_evals.py --run --only <新 id>` 确认失败 |
| 3 | 改承重件：门禁表、输出契约、探针回路三选一 | [SKILL.md](../SKILL.md) | `make check` |
| 4 | 细节搬迁：判据写进参考文件，新术语先进表 | `references/*.md`、[docs/glossary.md](glossary.md)、[scripts/terms.json](../scripts/terms.json) | `make check` |
| 5 | 跑结构门禁与行为评测，把结果写进变更记录 | [CHANGELOG.md](../CHANGELOG.md) | `make check && make eval` |
| 6 | 升版本，按发布序列打 tag 与打包 | [VERSION](../VERSION)、[CHANGELOG.md](../CHANGELOG.md) | `git tag v<version> && make release`，见 [releasing.md](releasing.md) |

### 步 1-2：用例必须先失败

先写用例，再改提示词。用例一写就通过，说明断言没抓住行为：换一个能从输出直接 grep 的观察量，或者把输入改得更接近真实误用。

`must_match` 至少一条。负向断言只在禁用短语不会出现在合法警告里时使用，否则留空。用例只测可观察量：标准号、数值加单位、表头、字段名、动作动词、被禁止的并列模板。不写"应该更有洞察力"这类判断。

### 步 3：只动承重件

承重件三处：

| 承重件 | 位置 | 改它的后果 |
|---|---|---|
| 门禁表 | `SKILL.md` §2 | 判定标准变化，必须同步参考文件与用例 |
| 输出契约 | `SKILL.md` §5 | 下游解析变化，必须同步 ADR 与全部 `must_match` |
| 探针回路 | `SKILL.md` §1、§4 | 执行顺序变化，通常升 major |

解释性文字不是承重件。理由进 [design.md](design.md) 或 [docs/decisions/](decisions/)，示例进 `references/`。

### 步 4：入口只留承重件

`SKILL.md` 的每个二级标题下只保留能被执行或被检查的内容。判据细节、反例、领域素材放 `references/`，按 `SKILL.md` §7 的加载表引用。每个 `references/*.md` 必须在 `SKILL.md` 中恰好链接一次，由 `refs` gate 检查。

新增术语的顺序固定：先写 [docs/glossary.md](glossary.md) 的定义与"不要写成"列，再加 [scripts/terms.json](../scripts/terms.json)，最后才在 `SKILL.md` 或 `references/` 使用。反序会让 `glossary` gate 失败。

### 步 5：两个结果都要记录

`make check` 记录通过的 gate 数，`make eval` 记录 PASS/FAIL 计数。只写"已通过"不算记录：下次维护者需要知道当时跑的是几条用例。

### 步 6：版本与发布

`VERSION` 只写三段数字加换行。`CHANGELOG.md` 在顶部加 `## [<version>] - <日期>`，分 Added / Changed / Removed / Migration 四节。破坏性变更必须写 Migration，读者只看这一节就知道要改什么。

## 变更影响矩阵

| 改了什么 | 必须同时更新 | 由什么检查 |
|---|---|---|
| `SKILL.md` 的某道门禁 | `references/` 对应文件 + 至少 1 条 eval 用例 | `structure`、`refs`、`evals` |
| 任一术语（新增、改名、退役） | [docs/glossary.md](glossary.md) + [scripts/terms.json](../scripts/terms.json) | `glossary` |
| 输出契约（台账列、下一步字段、停止条件） | 对应 ADR + [evals/cases.yaml](../evals/cases.yaml) 每条的 `must_match` | `decisions`、`evals`、`make eval` |
| `description` 或触发条件 | [evals/router_cases.yaml](../evals/router_cases.yaml) | `evals` + 人工判断 |
| 增删参考文件 | `SKILL.md` §7 加载表，保证恰好链接一次 | `refs` |
| 新增决策 | [docs/decisions/](decisions/) 的新 ADR + [design.md](design.md) 的链接 | `decisions`、`refs` |
| 调整预算 | [scripts/budget.json](../scripts/budget.json)，且先搬迁内容 | `budget` |
| 新增或修改用例 | `expect` 用规范术语，正则单引号包裹 | `evals` |

矩阵里的"至少 1 条 eval"是下限。改门禁却没有能观察该门禁的用例，这条规则就不可测；不可测的规则会在下一次改动时静默失效。

### 矩阵的三种连锁

- 改门禁 → 先加或改用例，再改 `SKILL.md` 的门禁表，最后同步参考文件；顺序反了，参考文件与入口会各说一套。
- 改术语 → 旧词残留在 `references/` 或 `terms.json`。`glossary` gate 会同时查表内术语与运行时禁用词。
- 改输出契约 → 下游读的是表头与"下一步"字段。所有用例的 `must_match` 必须能命中新契约，否则评测测的是旧契约。

## 写作规则

| 规则 | 判据 |
|---|---|
| 一条规则一个动作 | 读者能直接执行；"要严谨"不行，"先跑 P0 再贴标签"可以 |
| 能用表格不用段落 | 判据、映射、代价、失败签名一律表格 |
| 禁止模糊词 | 不写"视情况""酌情""尽量""根据需要" |
| 理由不进 `SKILL.md` | 理由写 [design.md](design.md) 或 ADR，入口只写动作 |
| 同一事实只写一处 | 其它位置只链接，不复述 |
| 每条新规则可观察 | 至少被一个 gate 或一条 eval 命中 |
| 术语逐字使用 | 缺口、未判、探针、门禁、缺口台账、实例化、定位缺失、生成缺失、证据缺失、参照类、可逆化、止损线、承重件、过程文档 |
| 不写计划句 | 只写当前事实，不写"我们将""计划中" |
| 例子最多两个 | 第三个例子说明该进 `references/` |
| 结尾不写总结段 | 最后一节就是最后一条规则 |

## 评审清单

逐条勾选，全部为"是"才提交。

- [ ] 1. 新行为有对应的 eval 用例，且在改提示词之前失败过。
- [ ] 2. `make check` 全绿，通过的 gate 数没有减少；改过 gate 时 `make test-gates` 全过。
- [ ] 3. `make eval` 全部 PASS，退步项为 0；连跑三次仍稳定。
- [ ] 4. `SKILL.md` 只增删了承重件，行数与字符数在预算内。
- [ ] 5. 新术语已进 [docs/glossary.md](glossary.md) 与 [scripts/terms.json](../scripts/terms.json)。
- [ ] 6. 每个 `references/*.md` 在 `SKILL.md` 中恰好被链接一次。
- [ ] 7. 输出契约若变化，ADR 与全部 `must_match` 已同步。
- [ ] 8. `description` 若变化，[evals/router_cases.yaml](../evals/router_cases.yaml) 已同步。
- [ ] 9. `CHANGELOG.md` 有对应版本条目；破坏性变更写了 Migration。
- [ ] 10. 同一事实没有被复制到第二个位置。

## 失败处理

| 现象 | 判断 | 动作 |
|---|---|---|
| 新用例失败，旧用例全过 | 正常：新用例抓住了缺口 | 继续步 3，改提示词直到新用例通过 |
| 新用例通过，旧用例退步 | 提示词改动引入回归 | 回滚本次改动；先修退步项，再重放新用例 |
| 新旧用例都不动 | 断言没有观察行为 | 重写 `must_match`，换成可 grep 的观察量；不要改提示词 |
| 连续两次修不好 | 方案假设不成立 | 停手，写 ADR 记录被否决的方案、失败证据、下次尝试的判据 |
| gate 与人工判断冲突 | 规则与实现不一致 | 以 gate 为准改内容；确认 gate 本身错时，先改 `scripts/check.py` 与其测试，再改内容 |
| 预算接近上限 | 内容仍在增长 | 先搬迁到 `references/`，再压缩，最后才提上限并在变更记录说明 |

回滚用 `git revert` 保留证据，不要 `reset --hard`。被否决的方案写进 ADR 的"备选方案"，同时写清它为什么会失败：这是下一次维护者唯一能复用的信息。
