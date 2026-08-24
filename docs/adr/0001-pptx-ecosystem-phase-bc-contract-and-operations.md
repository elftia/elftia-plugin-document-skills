# ADR 0001：PPTX 生态 B/C 契约 pin 与 operation 命名

状态：Accepted
日期：2026-08-24
分支：feat/pptx-ecosystem-phase-bc

## 基线

Document Skills 复用既有 worktree，并从已验证的明确集成基线
12d7a7f34e4e057a9005d320d46216ada95b5940 建立本分支。该基线的
feat/unified-plugin-packaging PR 尚因 GitHub Actions 账户计费门禁未合并，但工作树干净，
main 已同步，完整 npm test、build、dist 与 reproducibility 证据已绑定同一内容树。

Design Studio 只做了只读前置审计：HEAD 为
167b33376381fa862b60b949b89c307cc921e03c，现有 worktree 含未跟踪 docs/，
本切片不修改、不清理也不提交该工作树。

## A-Contract pin

Presentation contract 的唯一 owner 保持为 @elftia/presentation-contracts，不在
Document Skills 私建或复制同名 schema。当前 consumer pin 为：

- package：@elftia/presentation-contracts
- package version：1.0.0
- Deck IR / Semantic Slot / Template Contract schema：1.0.0
- migration：explicit-only
- artifact：7 个
- schemas/schema-manifest.json SHA-256：
  78989d9891c80a3f89ad25d7d31e4a431737131226df4494fc14dee1bfe3215a
- owner commit：fbcedc452c3d377e7e278a15a761ca702792cd28

Python consumer 读取 owner 发布包里的 manifest、JSON Schema 和 golden，先验证整个 pin，
再向 B/C module 暴露 schema validation、stable ID 和 content-hash 语义。未知版本、manifest
漂移、artifact 集合或 hash 漂移、路径别名和 golden 不一致均 fail closed。

@elftia/presentation-contracts 尚未发布到 npm。因此 B0C 的 producer conformance 使用显式
package root；后续 runtime adapter 必须消费正式发布包或审查过的本地安装，不能静默回退到
Host 私有路径，也不能把 schema 复制进本 producer。

## Operation 命名决定

对当前 capability registry、PPTX contracts、public supervisor、Skill 和 tests 的扫描没有发现
下列名称冲突。B/C 保留任务书名称，不建立同义 alias：

| Owner | 名称 |
|---|---|
| Document Skills | pptx.template.sanitize |
| Document Skills | pptx.template.inspect |
| Document Skills | pptx.create.from-template |
| Document Skills | pptx.create.from-svg |
| Document Skills | pptx.scene.export |
| Document Skills | pptx.reconstruct.from-image |
| Document Skills | pptx.beautify.strict |
| Document Skills | pptx.presenter.validate |
| Document Skills | pptx.narration.create |
| Document Skills | pptx.convert.video |
| Document Skills | pptx.delivery.inspect |
| Design Studio seam | design.deck.materialize-pptx |
| Design Studio seam | design.deck.build-companion |
| Design Studio seam | design.deck.apply-annotations |

equation block 与 equation_upsert 分别扩展既有 pptx.create 和 pptx.edit，不注册 raw OMML
operation。structured notes 同样扩展现有 create/edit；只有 presenter validator 是新 operation。

## Module 与 seam

PresentationContractConsumer 是深 module：调用方只需要 open、validate 与 stable-ID interface，
manifest pin、路径安全、schema 装载、golden、hash 和跨字段不变量都留在 implementation。

依赖分类如下：

- PPTX package、scene、template graph 和 lint：in-process；
- owner contract 安装：local-substitutable，通过发布包路径注入；
- Design Studio materialized bundle：owned cross-producer seam，生产使用只读 bundle adapter，
  测试使用自制 fixture adapter；
- LibreOffice、PowerPoint、TTS、OCR/vision 和 browser：true external adapter，缺失时
  unavailable，不允许占位成功。

每个 B/C slice 仍按 contract→implementation→validation→Skill/reference→public truth tests
纵向完成。只在实现和验收一起落地时注册 operation，B0 不批量注册 stub。

## Fixture 规则

plugin/tests/fixtures/pptx/ecosystem_bc 是唯一 B/C fixture 根。公共 writer 负责：

- POSIX relative path、NFKC 与 case-fold 唯一性；
- payload SHA-256 与邻接 manifest；
- author/origin、license、recipe、expected operation/consumer、resource limit、安全分类和
  不变量；
- redistributable fail closed 与确定性 UTF-8 JSON。

禁止把 Gorden 非商业模板、Guizang 当前 AGPL 内容、来源不明 deck、品牌 logo/照片或外部评测
制品放入 fixture。A-Governance 前只用自制 decision manifest，licenseStatus 未评估时始终保持
not_evaluated。

## 前置证据

以下命令在本 ADR 建立前通过，且两个 producer 输出相同 stable IDs、Deck IR content hash 和
not_evaluated 状态：

~~~text
uv run --project plugin --frozen python plugin/tools/presentation_contract_conformance.py <contract-root>
npm run check:presentation-contracts -- <contract-root>
~~~

Document Skills B0 后续将这组证据固定到确定性 fixture，并由 focused tests 检查 tamper、未知版本、
stable semantic key 与 fixture manifest 不变量。
