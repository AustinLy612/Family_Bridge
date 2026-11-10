# FamilyBridge 管理员指南

面向站点管理员。English: [ADMIN_GUIDE.en.md](ADMIN_GUIDE.en.md)。

FamilyBridge 是临床医生主导的 DBT-A 小组的辅助工具。它**不会被实时查看**，也不会发送短信、
电话或电子邮件。第一阶段只使用虚构的演示数据。任何真实使用之前，请先阅读
[KNOWN_LIMITATIONS.zh-CN.md](KNOWN_LIMITATIONS.zh-CN.md)。

管理员负责账号和站点设置。管理员**不能**查看参与者的日记卡、课程、反思或共同活动内容；系统没有
"紧急越权访问"。

## 1. 首次设置

1. 将 `.env.example` 复制为 `.env`，把每个占位值（`change-me…`）换成足够强且互不相同的值。
   切勿提交 `.env`。
   - `SECRET_KEY`：随机字符串，至少 32 个字符。
   - `FIELD_ENCRYPTION_KEY`：32 个随机字节的 base64 编码，例如
     `python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"`。
   - `POSTGRES_PASSWORD`（数据库所有者，只用于迁移）和 `APP_DB_PASSWORD`（API 自己的受限角色
     `familybridge_app`）。两者使用不同的值。
   - 除开发者本机外，一律设置 `APP_ENV=production`。生产模式会拒绝无效的加密密钥、拒绝演示数据，
     并发送 HSTS。
   - `LLM_PROVIDER` 与 `DEEPSEEK_API_KEY`：见第 5 节。
2. 启动：`docker compose up -d --build`。API 先以所有者身份执行迁移，创建或更新
   `familybridge_app` 角色，然后以该角色提供服务。
3. 创建第一个管理员（在 `backend/` 下运行，会提示输入密码）：

   ```bash
   .venv/Scripts/python -m app.cli create-admin --username site-admin
   ```

4. 登录网页，先填写**站点设置**（第 2 节），再邀请任何人。

## 2. 站点设置

**站点设置**包含站点名称、时区、求助联系方式和有人值守的时段。

- 每个求助联系方式都需要中文和英文两个标签。
- 时区决定日记卡中的"今天"，也决定研究数据导出中的日期。
- 在您将联系方式标记为**已由医院确认**之前，参与者的帮助页面会说明这些联系方式是占位内容。
  请在医院核对每个号码和时段之后再确认（待办事项 O4）。
- 每次修改都会写入审计日志。

## 3. 治疗师账号

**治疗师**页面列出治疗师账号的状态、最近登录时间和小组数量。

- **邀请：**生成一次性代码，当面或通过医院渠道交给治疗师。代码只显示一次、只能使用一次，并在
  `INVITATION_TTL_DAYS`（14 天）后失效。治疗师在 `/redeem` 兑换。
- **重置密码：**生成重置代码（`RESET_CODE_TTL_HOURS`，48 小时后失效）。兑换后该治疗师在所有设备上
  退出登录。参与者的密码由其治疗师重置。
- **停用：**立即退出登录并禁止登录。重新启用即可恢复。
- **内容审批人：**允许治疗师批准或停用共同活动剧集版本（见内容编写指南）。

## 4. 安全监督

**安全监督**以只读方式显示全部安全事件。治疗师处理自己小组的队列（新建 → 已确认 → 处理中 →
已解决）。管理员的每次查看都会被审计。系统没有自动升级机制（D38）：请与临床负责人约定人工复查
流程。

## 5. 知识库与 AI 层

- **知识库**显示当前手册索引版本、数量、标题检查和最近一次检索评估。它从不显示手册原文。
  导入是开发者任务（README 的 "Knowledge base" 一节）。
- **AI 层**显示提供方、熔断器、各功能的调用和兜底次数、拒绝代码、提示词审批和评估记录。只有
  计数和代码，没有参与者的文字。
- `LLM_PROVIDER=mock` 不进行任何外部调用。`LLM_PROVIDER=deepseek` 会把假名化的课程上下文（不含
  姓名）发送给 DeepSeek。密钥只放在 `.env` 的 `DEEPSEEK_API_KEY` 中。请勿把密钥放进代码仓库、
  聊天或工单。
- 如果提供方出错，熔断器会打开，参与者看到经过审核的静态内容。

## 6. 备份

第一阶段没有自动备份。请以数据库所有者身份使用 `pg_dump`。**备份文件包含加密字段和带密钥的哈希；
没有 `.env` 就无法读取，有了 `.env` 就能读取。请把备份文件和 `.env` 分开存放，都要加密，并只允许
指定人员访问。**切勿把备份放进代码仓库（`scripts/scan_repo.py` 会拒绝）。

备份（自定义格式，已压缩）：

```bash
docker compose exec -T db pg_dump -U familybridge -d familybridge -Fc > familybridge-YYYYMMDD.dump
```

恢复到空数据库（先停止 API）：

```bash
docker compose stop api
```
```bash
docker compose exec -T db dropdb -U familybridge --if-exists familybridge
```
```bash
docker compose exec -T db createdb -U familybridge familybridge
```
```bash
docker compose exec -T db pg_restore -U familybridge -d familybridge --no-owner < familybridge-YYYYMMDD.dump
```
```bash
docker compose up -d api
```

API 启动时会重新为 `familybridge_app` 授权。恢复之后，请检查审计链：

```bash
docker compose exec api python -m app.cli verify-audit
```

恢复时必须使用与备份时**相同**的 `SECRET_KEY` 和 `FIELD_ENCRYPTION_KEY`。在依赖备份之前，至少在
另一台机器上完整演练一次恢复。

## 7. 加密密钥与 SECRET_KEY

- `FIELD_ENCRYPTION_KEY` 用于加密敏感的自由文本（AES-256-GCM），存储时带有 `v1:` 版本前缀。
- **数据库中已有数据时，请勿更改 `FIELD_ENCRYPTION_KEY`。**目前程序只能读取一个密钥版本，更改后
  已有内容将无法读取。轮换密钥需要一个读取 `v1:`、写入 `v2:` 的重新加密工具，尚未开发（待办事项
  O25）。在此之前，如果密钥可能泄露：停止 API，做一次备份（第 6 节），并请开发团队在监督下进行
  重新加密。
- `SECRET_KEY` 用于一次性代码和会话令牌的哈希，以及研究导出中的假名代码。更改它会让所有人退出
  登录、使未使用的代码失效，并生成新的导出代码（之前的导出将无法关联）。只在两轮研究之间更改，
  并记录日期。
- 两个密钥都不要出现在聊天、邮件或工单中，请存放在医院的密钥管理系统里。

## 8. 研究数据导出

**研究数据导出**预览每个 CSV 文件及其行数，并下载一个包含 `data_dictionary.csv` 的 zip。导出不含
自由文本和直接身份信息；青少年和照护者的文件分开；只包括本人研究同意开启期间产生的记录；只有
日期和研究日，没有具体时间。每次下载都会被审计。导出文件只能保存在研究项目的安全存储中，不能放进
代码仓库。除非在命令行中明确要求，否则不包含演示数据。

## 9. 审计日志

所有账号、设置、导出和敏感查看都会写入只追加、带哈希链的审计日志。API 使用的数据库角色无法修改
或删除它。请定期以及每次恢复后检查哈希链：

```bash
docker compose exec api python -m app.cli verify-audit
```

如果退出码不为零，说明有记录被修改或删除：请停止操作并联系安全负责人。

## 10. 日常检查表

| 时间 | 任务 |
|---|---|
| 每周 | 与临床负责人一起查看安全监督；查看 AI 层的兜底次数 |
| 每周 | 做一次备份（第 6 节）；运行 `verify-audit` |
| 每月 | 停用已离开人员的账号；检查未使用的代码 |
| 每轮研究 | 运行研究数据导出；记录导出日期 |
| 真实使用前 | 确认求助联系方式；设置生产环境密钥 |
