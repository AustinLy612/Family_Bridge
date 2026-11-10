# FamilyBridge 内容编写指南

面向临床人员和内容编辑。English: [CONTENT_AUTHORING.en.md](CONTENT_AUTHORING.en.md)。

参与者看到的所有内容——帮助文字、知情同意、日记卡模板、提示词、兜底内容、剧集、安全词表——都是
[`content/`](../../content/README.md) 中带版本号的文件，而不是写在代码里。API 启动时会检查每个文件，
只要有一个文件无效就**拒绝启动**。

## 1. 唯一的硬性规则：不要复制手册

DBT-A 手册受版权保护，只在后台用于为 AI 回答提供依据。参与者只会看到**原创表述**（D7）。

- 请用自己的话写。不要粘贴、逐句翻译或稍加改写手册原文。
- 自动检查会将每个可提交的文件与手册的指纹进行比对，只要有连续 20 个或以上字符与手册相同就会失败
  （`scripts/scan_repo.py`）。
- 切勿把手册 PDF 或摘录放进代码仓库。

## 2. 文件位置

| 文件夹 | 编辑内容 |
|---|---|
| `help/{zh,en}.md` | 帮助页面文字。联系方式和时段来自站点设置，而不是这个文件。 |
| `consent/` | 各角色、各语言的知情同意文件。 |
| `diary/{role}/` | 日记卡模板（条目、量表、措辞）。 |
| `episodes/` | 共同活动剧集：`catalog.yaml` 和 `{id}/vN.yaml`。 |
| `prompts/{function}/{role}/{lang}/vN.md` | AI 指令。 |
| `fallbacks/` | AI 不可用或未通过检查时显示的、经过审核的静态文字。 |
| `safety/` | 风险关键词、禁用表达、输出规则。 |
| `skills/taxonomy.yaml` | 技能名称和讲义索引。 |
| `eval/` | 检索和 AI 的测试问题（不会显示给参与者）。 |

参与者看到的每段文字都必须**同时有 zh-CN 和 en 两个版本**。

## 3. 审批状态

每个文件都有一个审批块：

```yaml
approval: { status: draft, approved_by: null, approved_at: null }
```

| 状态 | 含义 |
|---|---|
| `demo` | 仅用于演示和测试的虚构示例。 |
| `draft` | 正在编写或审核，只能用于演示/测试家庭。 |
| `approved` | 已通过临床审核，需要填写 `approved_by` 和 `approved_at`，可用于真实家庭。 |
| `retired` | 不再提供，保留作记录。 |

未处于 `approved` 状态的内容永远不会提供给真实家庭。

## 4. 修改文件

1. **不要直接修改已批准的版本。**将其复制为下一个版本（`v2.yaml`、`v2.md`），设置
   `status: draft`，然后修改副本。旧版本会保留，以便过去的记录仍然有意义。
2. 保持语气：温和、平实、不评判；不责备、不施压，不出现"逾期"或"失败"；没有分数、连续打卡或徽章。
3. **绝不承诺监控、联系或救助**（例如"我们会给你打电话""有人在看着"）。
   `safety/forbidden_phrases.yaml` 会拦截帮助和知情同意文件中的这类文字，测试也会检查应用中的
   每一条文字。
4. 检查文件（在 `backend/` 下运行）：

   ```bash
   .venv/Scripts/python -m app.cli check-content
   ```

   输出 `content OK`，或指出出错的文件和字段。
5. 请开发人员运行完整检查（`bash scripts/check.sh`）并部署。
6. 临床审核通过后，设置 `status: approved`、`approved_by`（姓名或角色）和 `approved_at`（日期）。

## 5. 剧集

剧集版本还需要在应用内审批：管理员，或拥有**内容审批人**权限的治疗师，在**内容审核**中批准或停用
某个版本。未批准的版本只能安排给演示家庭。每一步都应说明其目的（练习哪项技能），以便治疗师解释。

## 6. 提示词与安全词表

- 修改提示词会改变 AI 的行为。修改后，开发人员需要重新运行对抗性基准测试
  （`python -m app.cli ai eval`）和抽样检查，并记录结果（`docs/dev/ADVERSARIAL_RESULTS.md`）。
- 修改风险关键词需要临床签字。漏掉关键词可能导致有风险的消息没有打开帮助页面；关键词过宽则会
  中断本来没有问题的课程。
- 日记卡的冲动阈值属于配置（`DIARY_URGE_THRESHOLD` 或 `safety.diary_urge_threshold` 设置），
  而不是内容文件。目前是占位值（O3）。
