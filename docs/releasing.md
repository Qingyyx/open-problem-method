# 发布流程

本文件只写发布动作。版本语义与产出流程在 [authoring.md](authoring.md)，门禁细节在 [verification.md](verification.md)。

## semver

| 位 | 发布含义 | 例子 |
|---|---|---|
| patch | 措辞、示例、错别字；门禁、探针、输出契约不变 | 2.0.0 → 2.0.1 |
| minor | 新增门禁、探针或参考文件；输出契约与触发方式不变 | 2.0.0 → 2.1.0 |
| major | 触发方式、分类、输出契约、步骤顺序任一变化 | 2.0.0 → 3.0.0 |

版本只升不降。已发布的版本号不复用，即使该版本已被撤回。

版本授权：`major` 只在用户明确要求时升，其余只升 `patch`/`minor`；规则与例外见 [authoring.md 的「版本语义」](authoring.md#版本语义)。

## 版本三元组

三处必须一致，不一致则 `version` gate 与 `release.py --check` 同时失败：

| 位置 | 内容 |
|---|---|
| [VERSION](../VERSION) | 单行 `X.Y.Z` 加换行 |
| [CHANGELOG.md](../CHANGELOG.md) | 顶部含 `## [X.Y.Z] - YYYY-MM-DD` |
| [SKILL.md](../SKILL.md) | `metadata.version` 等于同一字符串 |

## 发布序列

按顺序执行，任一步失败就停在该步，不进入下一步。

| 步 | 命令或动作 | 通过标准 |
|---|---|---|
| 1 | 编辑 `VERSION`、`CHANGELOG.md`、`SKILL.md` 的 `metadata.version` | 三者一致 |
| 2 | `make check` | `OK 9 gates, N files` |
| 3 | 人工运行 `make eval` | 人工用例的 `review` 清单逐条勾选；自动用例失败项为 0；本机 `router_cases.yaml` 无新增误触发 |
| 4 | `git tag v<version>` 并 `git push origin v<version>` | tag 指向第 3 步通过的提交 |
| 5 | `make release` | 产出 `dist/open-problem-method-v<version>.zip`，包内含 `manifest.json` |
| 6 | 发布 zip；需要单独附 manifest 时从包内取出 | 附件与本地 `sha256sum` 一致 |
| 7 | 安装 smoke | 解压后 frontmatter 的 `name`、`description`、`version` 正确 |

第 4 步在第 3 步之后：tag 一旦推送就代表"这个提交通过人工评测"，顺序反了就要撤 tag。评测用例只在本机，不随提交推送。

第 7 步的 smoke 在发布物上做，不在工作树上做。工作树通过不代表 zip 完整。

## make release 做什么

`make release` 先跑 `make check`，再调用 `python3 scripts/release.py --all`，后者等于三步：

| 子命令 | 动作 | 失败意味着 |
|---|---|---|
| `--check` | 校验 `VERSION` 是 semver、`CHANGELOG.md` 有对应条目、frontmatter 的 `version` 一致 | 版本三元组不完整 |
| `--pack` | 生成 `dist/open-problem-method-v<version>.zip`，并在包内写 `manifest.json` | 打包输入缺失或被忽略规则挡住 |
| `--smoke` | 解压到临时目录，解析 `SKILL.md` frontmatter，断言 `name`、`description`、`version` | 包内入口损坏或版本不一致 |

三步可以分开跑，用于定位：`python3 scripts/release.py --check`、`--pack`、`--smoke`。

## 产物内容

zip 只含五类条目：

| 条目 | 作用 |
|---|---|
| `SKILL.md` | 运行时入口 |
| `references/**` | 按需加载的参考层 |
| `VERSION` | 版本号 |
| `CHANGELOG.md` | 变更记录，安装者可读 |
| `manifest.json` | 每个文件的 sha256 |

不打包 `docs/`、`scripts/`、`evals/`、`.github/`、`.githooks/`、`dist/`。维护文档与评测是仓库资产，不是安装物；把它们打进包会让使用者误以为需要运行门禁。本机 `evals/` 含真实客户信息，同样不进入发布包。

发布后核对：

```sh
unzip -l dist/open-problem-method-v<version>.zip
sha256sum dist/open-problem-method-v<version>.zip
```

`manifest.json` 里的哈希与包内文件逐条对应；发布说明里附 zip 的 sha256，安装者下载后可自行核对。

## 破坏性变更的 Migration

`CHANGELOG.md` 的 `## Migration` 是唯一面向升级者的段落。必须写三件事：

| 写什么 | 判据 |
|---|---|
| 旧行为与新行为各是什么 | 读者能判断自己是否受影响 |
| 读者要改什么 | 点名文件、字段、调用方式；不写"相应调整" |
| 怎么确认改完 | 一条可执行的检查，例如读输出表头、跑一次 smoke |

Migration 只写读者动作。理由写 ADR，链接放在条目末尾；不复述决策过程。

破坏性变更必须在同一次提交里完成：`SKILL.md` 改动、ADR、Migration 段，以及本机手工用例的验证记录。用例本身不入库；分成两次提交会让中间状态既不可测也不可发布。

## 回滚

| 阶段 | 动作 | 约束 |
|---|---|---|
| tag 之前 | 修文件，重跑第 2、3 步 | 不产生 tag，不改版本号 |
| 已 tag，未发布 | `git tag -d v<version>` 与 `git push origin :refs/tags/v<version>`，删除 `dist/` 下产物 | 修复后用同一版本号重新 tag |
| 已发布 | 重新发布上一版 zip；`CHANGELOG.md` 顶部加一条撤回记录，写明撤回原因与替代版本 | 不删除、不移动已发布的历史 tag |
| 安装后发现 | 回退到上一版 zip，重跑 `release.py --smoke` 确认 | 修复版用新的 patch 号，不复用被撤回的号 |

撤回记录写在对应版本条目下，格式一行：`已撤回：<原因>；请使用 <替代版本>。` 不修改该版本原有的 Added / Changed / Removed / Migration 内容，历史保持可追溯。

## 发布前检查

- [ ] `VERSION`、`CHANGELOG.md`、`metadata.version` 三者一致。
- [ ] `CHANGELOG.md` 有 Added / Changed / Removed / Migration 四节，空节写"无"。
- [ ] `make check` 输出 `OK 9 gates`。
- [ ] 人工运行 `make eval`，人工清单逐条勾选，自动用例无退步。
- [ ] 破坏性变更的 Migration 点名了文件与字段。
- [ ] zip 清单只有五类条目。
- [ ] `manifest.json` 的哈希与包内文件一致。
- [ ] smoke 在解压目录通过。
