---
name: parse-pst
description: >-
  Parse and analyze Outlook PST (.pst) files on Linux using pypff. Trigger this skill
  whenever the user asks to analyze, inspect, read, parse, summarize, or extract emails,
  folders, calendar, contacts, or attachments from an Outlook PST file (e.g., "请帮我分析下这个pst文件",
  "帮我解析pst", "读取Outlook pst", "查看pst文件内容", "parse pst file", "extract pst").
compatibility: Linux only
allowed-tools:
  - bash
metadata:
  version: "1.0.0"
  platform: "linux"
---

# Outlook PST 文件分析流程指引 (Hermes Agent 指南)

当检测到用户需要分析、查看或提取 Outlook PST 文件时，Hermes 会根据渐进式披露（Progressive Disclosure）加载本指南。作为 Hermes Agent，请严格按照以下标准操作流程（SOP）调用底层工具并向用户输出结果。

---

## 阶段一：提取目标路径与环境检查 (Phase 1)

1. **确定 PST 文件路径**：
   从用户的输入（如 `请帮我分析下这个pst文件 /home/user/mail.pst`）中提取目标文件路径。
   - 如果用户未给出明确路径，通过简短提问请用户提供 PST 文件在 Linux 服务器上的绝对路径或相对路径。
   - 确认文件是否存在：
     ```bash
     test -f "<pst_path>" && echo "EXISTS" || echo "NOT_FOUND"
     ```

2. **验证 Python 依赖**：
   解析器依赖 `pypff` 模块，运行时镜像内已预装（Debian 包 `python3-pypff`）。先确认可用：
   ```bash
   python3 -c "import pypff; print('pypff', pypff.get_version())"
   ```

   - **不要用 pip 安装**。PyPI 上的 `libpff-python` 没有 Linux wheel，装不上；而 PyPI 上另一个同名包 `pypff` 是完全无关的 PANOSETI 文件格式库，装上后 `import pypff` 会成功，但报错会推迟到调用 `pypff.file()` 时才以 AttributeError 出现，极难排查。
   - 若上面报 `ModuleNotFoundError`，说明当前运行时镜像缺少该依赖。直接告知用户需要重建运行时镜像（`hermes-agent/Dockerfile.bridge` 已包含 `python3-pypff`），不要在容器内自行安装。

---

## 阶段二：执行解析脚本 (Phase 2)

调用本 Skill 内置的 Linux 解析脚本 `scripts/parse_pst.py`（通常位于 `/opt/data/skills/parse-pst/scripts/parse_pst.py`）。

通过 `bash` 工具执行以下命令：

```bash
# 自动定位本 skill 目录并执行脚本
SKILL_DIR="$(dirname "$(find "${HERMES_HOME:-/opt/data}/skills" /workspace/skills -name "parse_pst.py" 2>/dev/null | head -n 1)")"
[ -z "$SKILL_DIR" ] && SKILL_DIR="./scripts"

python3 "$SKILL_DIR/parse_pst.py" "<pst_path>"
```

### 附加功能参数（根据用户具体要求选用）：
- **提取附件**：若用户要求导出附件，添加 `--export-attachments "<导出目录>"`（例如 `--export-attachments ./attachments`）。
- **保存 JSON**：若用户要求保存结构化数据，添加 `--json "<输出路径.json>"`.
- **完整正文**：若用户要求查看完整正文不截断，添加 `--verbose`.

---

## 阶段三：向用户呈现结果 (Phase 3)

脚本执行完毕后，控制台会输出纯正中文的结构化报告。请将输出内容结构清晰地呈现给用户：

1. **基本概况**：展示目标文件绝对路径及大小（MB）。
2. **【一、PST 文件夹层级结构】**：树状展示所有文件夹、中文映射（如 `Inbox [收件箱]`、`Sent Items [已发送邮件]`、`Calendar [日历/日程]` 等）及各自包含的条目数。
3. **【二、总体统计】**：扫描出的条目与邮件总数。
4. **【三、条目与邮件详细清单】**：逐条列出：
   - 所在目录
   - 邮件主题
   - 发件人 / 收件人
   - 日期时间戳
   - 附件列表（名称、文件大小）
   - 正文摘要
5. **后续引导**：询问用户是否需要进一步搜索特定发件人的邮件、导出特定邮件的全部正文，或提取其中的附件。
