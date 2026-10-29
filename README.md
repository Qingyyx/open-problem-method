# open-problem-method

把开放性问题拆成**可执行探针**，用证据决定下一步，而不是直接给一段看起来有道理的分析。

本 skill 只在显式调用时生效：点名 `open-problem` / `开放性问题方法论`，或明确要求「先拆解再回答」。普通问答、检索、调试、选型直接回答。

## 输出什么

复杂问题输出一份固定 7 节的过程文档：

1. 问题与结论
2. P0 探针（≤15 分钟，先检索再分类）
3. 缺口台账（定位缺失 / 生成缺失 / 证据缺失）
4. 实例化（≤5 条会翻转结论的私有条件）
5. 下一步（只一个动作，含执行者、耗时、花费上限、失败信号）
6. 停止与翻转
7. 执行记录（用了什么、读了什么、哪些没验证）

如果 P0 一次闭合、且没有会翻转结论的私有条件，直接回答，不生成文档。当前目录可写时，同时落盘 `open-problem-<slug>.md`。

## 安装

克隆到 agent 的 skills 目录：

```sh
git clone https://github.com/Qingyyx/open-problem-method.git \
  ~/.agents/skills/open-problem-method
```

或者只复制运行所需文件：

```sh
mkdir -p ~/.agents/skills/open-problem-method
cp -r SKILL.md references VERSION CHANGELOG.md ~/.agents/skills/open-problem-method/
```

也可以先运行 `make release` 生成 `dist/open-problem-method-v<version>.zip`，再解压到同一位置。安装包只含 `SKILL.md`、`references/`、`VERSION`、`CHANGELOG.md` 与 `manifest.json`。

## 用法

```text
用 open-problem 帮我拆解：我们团队该不该把单体拆成微服务？
```

```text
按 open-problem 分析：怎么判断一套房子的隔音好不好？
```

下面这种不会触发，按普通问答直接回答：

```text
帮我分析一下这个问题
```

## 仓库结构

| 路径 | 内容 |
|---|---|
| `SKILL.md` | 运行时入口；改行为先改这里 |
| `references/` | 按需加载的判据与反例 |
| `docs/` | 设计理由、产出流程、发布、门禁、术语、ADR |
| `evals/` | 本机手工用例与触发样本；含真实客户信息，已 gitignore，不入库 |
| `scripts/` | 结构门禁、评测运行器、发布脚本 |

## 维护

```sh
make check        # 结构门禁，提交前必须通过
make test-gates   # 破坏每条规则，确认门禁会失败
make eval         # 本机手工评测，仅人工运行；保存输出/思维链到 evals/runs/
make release      # 校验版本、打包、安装 smoke
```

`evals/cases.yaml`、`evals/router_cases.yaml`、历史存档 `evals/reference/` 与运行记录 `evals/runs/` 含真实客户信息，只在本机维护，已被 `.gitignore` 排除；`make eval` 只由人工运行，AI 与 CI 都不触发。

产出流程见 [docs/authoring.md](docs/authoring.md)，门禁清单见 [docs/verification.md](docs/verification.md)，发布步骤见 [docs/releasing.md](docs/releasing.md)。

## 版本策略

版本号遵循 semver，但 `major` 位只在维护者明确要求「升大版本」时使用；日常维护只升 `patch` 或 `minor`。如果变更按 semver 属于 major 而尚未获得授权，先做向后兼容或停下来确认，不用 minor 伪装。

版本三元组：`VERSION`、`CHANGELOG.md` 顶部条目、`SKILL.md` 的 `metadata.version`，三者必须一致。
