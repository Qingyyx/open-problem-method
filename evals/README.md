# 评测

评测要回答的问题：输出到底是执行了方法，还是只长得像执行。结构门禁管形态，行为评测管行为，两者不互相替代。

## 两层

| 层 | 文件 | 何时 | 判什么 |
|---|---|---|---|
| 结构 | [cases.yaml](cases.yaml) 的 YAML 合法性；[router_cases.yaml](router_cases.yaml) 的字段与正负计数 | 每次提交，`make check` | 用例能否被解析、正则能否编译、每条是否含 `id` `input` `expect` `must_match` `must_not_match` `why`，可选的 `artifact_glob` 是否是相对 glob |
| 行为 | [cases.yaml](cases.yaml) | 发布前，`make eval` | 对每个输入跑模型，输出是否命中全部 `must_match`、是否避开全部 `must_not_match` |

[router_cases.yaml](router_cases.yaml) 是触发样本，不自动跑。它的结构由 `evals` gate 检查；真实触发判断是人工评审：抽样真实调用，看该激活时是否激活、不该激活时是否误触发。原因见 [verification.md](../docs/verification.md) 的"不自动化的部分"。

## 如何新增用例

1. 先写一个具体输入，和它期望的可观测行为。`expect` 用规范术语，例如 `定位缺失 + 实例化`。
2. 在 [cases.yaml](cases.yaml) 追加一条，六个必需字段齐全，`id` 顺延且唯一；文档型用例加 `artifact_glob`。
3. `must_match` 至少一条。`must_not_match` 只在禁用短语不可能出现在合法警告里时使用；否则留空，改用正向证据。
4. 跑 `python3 scripts/run_evals.py --plan`，确认 YAML 可解析、正则可编译。
5. 跑 `python3 scripts/run_evals.py --run --only <新 id>`，在改提示词之前确认它失败。
6. 改 `SKILL.md`，直到该用例通过；再跑全量 `make eval` 确认没有退步。

第 5 步不能跳过。用例一写就通过，说明断言没抓住行为，要换观察量或换输入。

触发样本按同样方式进 [router_cases.yaml](router_cases.yaml)：正例必须显式点名本方法，负例覆盖技术问答、调试、选型、推荐四类。负例少于两类时，触发评测就测不出"因为问题开放而误触发"。

## 断言风格

只写能从输出文本直接 grep 的观察量。

| 可以写 | 例子 |
|---|---|
| 标准号、规范编号 | `GB\s*50118` |
| 数值加单位 | `\d+\s*dB`、`\d+\s*%` |
| 字段名、表头、动作词 | `缺口`、`下一步`、`停止`、`约束` |
| 结构性禁项 | 台账表头 `\|\s*#\s*\|\s*缺口`；并列模板 `路径一\|路径二` |
| 必现的结构成分 | `(可逆|参照类|base rate|基准)` |

不要写：

- 主观判断："回答应有洞察力""分析要专业"。
- 长句整抄：会把提示词锁死在某一版措辞上，正常改写就误报。
- 只出现一次的词：模型换个同义词就漏，断言应该覆盖同义集合。

正则一律单引号包裹，反斜杠按字面保留。`must_match` 全部命中才算 PASS；`must_not_match` 任一命中即 FAIL。一条用例 2-3 条 `must_match` 足够，条目越多越容易测到措辞而不是行为。

负向断言容易假阳性：正确输出常写"不要直接辞职"、"不能只说各有优劣"，这些句子包含禁用短语。因此负向断言优先选结构特征（表头、编号模板），不要选会被合法警告引用的措辞。

## 文档型用例

在用例里加 `artifact_glob: 'open-problem-*.md'`，评测会先在临时目录里找匹配文件：找不到直接 FAIL，断言改为对文件内容执行；找不到时不会回退到 stdout。没有 `artifact_glob` 的用例仍断言 stdout。case-08 用这一层检查过程文档的 7 个二级标题。

## 成本与凭据

| 命令 | 调模型 | 成本 | 用途 |
|---|---|---|---|
| `make eval-plan` | 否 | 零 | 校验 YAML，打印将要执行的命令 |
| `make eval` | 是 | 每条用例一次调用 | 发布前行为门禁 |
| `python3 scripts/run_evals.py --run --only <id>` | 是 | 一次调用 | 单条调试 |

`make eval` 需要 opencode CLI 与模型额度。未安装 `opencode` 时 `run_evals.py` 以退出码 2 结束并给出安装提示。默认不写死模型：不传 `--model` 时不加 `-m`，由环境决定；发布评测应固定模型，避免跨版本比较时混入模型差异。

`make eval` 不进默认 CI：CI 没有模型凭据，也不该为每次提交付费。行为评测是发布前本地门禁，见 [releasing.md](../docs/releasing.md)。

## 失败诊断

先拿完整输出，再看断言。

```sh
python3 scripts/run_evals.py --run --only case-03
python3 scripts/run_evals.py --run --only case-03 --json
```

| 现象 | 可能原因 | 动作 |
|---|---|---|
| `must_match` 未命中 | 输出没有该观察量：提示词没要求，或用例过严 | 读原始输出；确属退步改 `SKILL.md`，只是措辞差异改用例 |
| `must_not_match` 命中 | 输出出现典型错解，或警告句里引用了禁用短语 | 先看命中位置：若是"不要……"式警告，改用例；若是真推荐，改 `SKILL.md` 的硬性禁止或门禁 |
| 同一用例偶发失败 | 模型波动 | 连跑 3 次；≥2 次失败才算退步 |
| 全部用例同时失败 | 环境问题：模型不可用、CLI 版本、临时目录拷贝不完整 | 先 `--plan`，再单跑一条；检查临时目录里是否有 `SKILL.md` 与 `references/` |
| 新用例通过但旧用例退步 | 提示词改动引入回归 | 回滚，按 [authoring.md](../docs/authoring.md) 的失败处理重来 |

修改断言前先问一句：这次失败是模型没执行方法，还是断言写得太窄。前者改提示词，后者改用例。两种情况都改，会同时丢失信号和基准。
