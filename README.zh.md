# jev-dingtalk

用 [Jev](https://docs.typesafe.ai) 给**钉钉邮箱**分诊：通过 `dws` 拉取未读邮件，用 `jev mail` 分类，交回一张「谁在等回复、谁需要人看一眼」的清单。

[English](README.md)

## 功能

- 经 `dws`（dingtalk-workspace-cli）拉取钉钉未读邮件与正文，转成 `jev mail` 读取的 JSON。
- 交给 Jev 分类：`needs_reply` / `updates` / `promotional` / `sales` / `spam`，附紧急度与需要人看的标记（`needs_attention`、`low_confidence`、`injection`）。
- **分类结果即成品**——链路里没有第二次模型调用；只有被标记的行才需要人或模型介入。
- 机械渲染 markdown 报告；脚本只用 Python 标准库。

配套 [`jev-mailbox`](https://github.com/kerpopule/hermes-jev-skills)：它给已经导出的邮件分拣，这里补上钉钉的「取数 + 转换」和对应的字段坑。

## 使用

```bash
# 前置：python3、Node.js（装 dws）、一个 Jev API key
npm install -g dingtalk-workspace-cli     # dws CLI
dws auth login -y                         # 扫码登录，约 30 天
jev setup-key                             # 一次性

# 拉取 + 分诊
python3 scripts/dws_unread_to_jev.py --email you@example.com --size 50 --out inbox.json
jev mail --file inbox.json > triage.json

# 出报告
python3 scripts/render_triage.py --in triage.json --md report.md
```

装到 Agent 里用：把整个文件夹拷进技能目录（Hermes：`$HERMES_HOME/skills/`）。完整流程与钉钉专属的坑看 `SKILL.md`；`examples/` 是合成样张，可直接干跑脚本。

## 许可

MIT
