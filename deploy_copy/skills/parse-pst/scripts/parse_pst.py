#!/usr/bin/env python3
"""
Outlook PST 文件解析脚本 (Linux 专用版 - Hermes Agent Skill)
依赖: libpff-python 或 python3-pypff
"""

import os
import sys
import json
import argparse

# 常见 Outlook 文件夹中文对照映射
FOLDER_CN_MAP = {
    "Top of Personal Folders": "个人文件夹根目录",
    "Inbox": "收件箱",
    "SubInbox": "子收件箱",
    "Sent Items": "已发送邮件",
    "Deleted Items": "已删除邮件",
    "Drafts": "草稿箱",
    "Outbox": "发件箱",
    "Junk E-mail": "垃圾邮件",
    "Calendar": "日历/日程",
    "Contacts": "联系人通讯录",
    "Tasks": "任务清单",
    "Notes": "便签/便条",
    "Journal": "日记",
    "RSS Feeds": "RSS 订阅",
    "Search Root": "搜索根目录",
    "All Messages": "所有邮件视图",
    "Freebusy Data": "忙闲数据",
    "Reminders": "提醒事项",
    "To-Do Search": "待办搜索",
    "ItemProcSearch": "条目处理搜索",
    "Tracked Mail Processing": "跟踪邮件处理",
    "SPAM Search Folder 2": "垃圾邮件搜索文件夹 2",
    "IPM_VIEWS": "视图定义",
    "IPM_COMMON_VIEWS": "通用视图定义",
}


def safe_call(fn, default=None):
    """安全调用 pypff 属性方法，规避底层描述符异常。"""
    try:
        val = fn()
        return val if val is not None else default
    except Exception:
        return default


def get_attachment_filename(att):
    """从 MAPI Record Set 中读取原始长文件名 (0x3707) 或短文件名 (0x3704)。"""
    try:
        num_rs = att.get_number_of_record_sets()
    except Exception:
        return "未命名附件"

    long_name = None
    short_name = None
    for rs_idx in range(num_rs):
        try:
            rs = att.get_record_set(rs_idx)
            for e_idx in range(rs.get_number_of_entries()):
                entry = rs.get_entry(e_idx)
                entry_type = entry.get_entry_type() if hasattr(entry, "get_entry_type") else None
                if entry_type == 0x3707:
                    try:
                        long_name = entry.get_data_as_string()
                    except Exception:
                        pass
                elif entry_type == 0x3704 and not short_name:
                    try:
                        short_name = entry.get_data_as_string()
                    except Exception:
                        pass
        except Exception:
            continue

    return long_name or short_name or "未命名附件"


def parse_headers(headers_text):
    """提取常见邮件头 (From, To, Cc, Subject, Date)。"""
    if not headers_text:
        return {}
    results = {}
    lines = headers_text.replace("\r\n", "\n").split("\n")
    current_key = None
    for line in lines:
        if line.startswith((" ", "\t")) and current_key:
            results[current_key] += " " + line.strip()
        elif ":" in line:
            parts = line.split(":", 1)
            key = parts[0].strip().title()
            val = parts[1].strip()
            current_key = key
            if key in ["From", "To", "Cc", "Bcc", "Subject", "Date"]:
                results[key] = val
    return results


def parse_message_item(msg, msg_idx, folder_path, export_dir=None):
    """解析单条消息、联系人或日程条目。"""
    subject = safe_call(msg.get_subject, "(无主题)")
    sender = safe_call(msg.get_sender_name, "(未知发件人)")
    delivery_time = safe_call(msg.get_delivery_time)
    creation_time = safe_call(msg.get_creation_time)
    transport_headers = safe_call(msg.get_transport_headers, "")
    parsed_headers = parse_headers(transport_headers)

    num_att = safe_call(msg.get_number_of_attachments, 0)
    attachments = []

    for att_idx in range(num_att):
        try:
            att = msg.get_attachment(att_idx)
            fname = get_attachment_filename(att)
            size = safe_call(att.get_size, 0)
            att_info = {
                "index": att_idx + 1,
                "filename": fname,
                "size_bytes": size,
            }

            if export_dir and size > 0:
                clean_folder = "".join(c if c.isalnum() or c in "-_" else "_" for c in folder_path)
                item_prefix = f"{clean_folder}_msg{msg_idx+1}_att{att_idx+1}"
                safe_fname = "".join(c if c.isalnum() or c in ".-_" else "_" for c in fname)
                out_path = os.path.join(export_dir, f"{item_prefix}_{safe_fname}")
                try:
                    data = att.read_buffer(size)
                    with open(out_path, "wb") as f:
                        f.write(data)
                    att_info["saved_path"] = out_path
                except Exception as e:
                    att_info["export_error"] = str(e)

            attachments.append(att_info)
        except Exception as e:
            attachments.append({"index": att_idx + 1, "error": str(e)})

    plain_body = safe_call(msg.get_plain_text_body)
    plain_body_str = plain_body.decode("utf-8", errors="replace").strip() if plain_body else ""

    html_body = safe_call(msg.get_html_body)
    html_body_str = html_body.decode("utf-8", errors="replace").strip() if html_body else ""

    body_preview = plain_body_str if plain_body_str else html_body_str

    return {
        "index": msg_idx + 1,
        "folder": folder_path,
        "subject": subject,
        "sender": sender,
        "recipient": parsed_headers.get("To", ""),
        "date": str(delivery_time or creation_time or parsed_headers.get("Date", "")),
        "headers": parsed_headers,
        "attachment_count": len(attachments),
        "attachments": attachments,
        "body_preview": body_preview[:300] if body_preview else "",
        "has_plain_body": bool(plain_body_str),
        "has_html_body": bool(html_body_str),
    }


def traverse_folders(folder, current_path="", export_dir=None):
    """递归遍历所有文件夹与子条目。"""
    raw_name = safe_call(folder.get_name) or ("Root" if not current_path else "Unnamed")
    cn_label = FOLDER_CN_MAP.get(raw_name, "")
    display_name = f"{raw_name} [{cn_label}]" if cn_label else raw_name
    folder_path = f"{current_path}/{raw_name}" if current_path else raw_name

    num_subfolders = safe_call(folder.get_number_of_sub_folders, 0)
    num_messages = safe_call(folder.get_number_of_sub_messages, 0)

    folder_data = {
        "raw_name": raw_name,
        "cn_name": cn_label,
        "display_name": display_name,
        "folder_path": folder_path,
        "total_messages": num_messages,
        "total_subfolders": num_subfolders,
        "messages": [],
        "subfolders": [],
    }

    for m_idx in range(num_messages):
        try:
            msg = folder.get_sub_message(m_idx)
            item_data = parse_message_item(msg, m_idx, folder_path, export_dir=export_dir)
            folder_data["messages"].append(item_data)
        except Exception as e:
            folder_data["messages"].append({
                "index": m_idx + 1,
                "folder": folder_path,
                "error": f"读取条目失败: {e}",
            })

    for s_idx in range(num_subfolders):
        try:
            sub = folder.get_sub_folder(s_idx)
            sub_data = traverse_folders(sub, folder_path, export_dir=export_dir)
            folder_data["subfolders"].append(sub_data)
        except Exception as e:
            folder_data["subfolders"].append({
                "error": f"访问子目录 {s_idx} 失败: {e}"
            })

    return folder_data


def print_tree(folder_data, indent=""):
    """树状打印目录。"""
    name = folder_data.get("display_name", folder_data.get("raw_name", "未知目录"))
    msg_count = folder_data.get("total_messages", 0)
    sub_count = folder_data.get("total_subfolders", 0)
    print(f"{indent}📁 {name} (条目数: {msg_count}, 子文件夹数: {sub_count})")
    for sub in folder_data.get("subfolders", []):
        print_tree(sub, indent + "  ")


def flatten_messages(folder_data):
    """平铺获取所有条目。"""
    all_msgs = list(folder_data.get("messages", []))
    for sub in folder_data.get("subfolders", []):
        all_msgs.extend(flatten_messages(sub))
    return all_msgs


def main():
    parser = argparse.ArgumentParser(description="Outlook PST 文件解析器 (Linux 版)")
    parser.add_argument("pst_file", help="PST 文件路径")
    parser.add_argument("--json", dest="json_out", help="保存为 JSON 结果文件")
    parser.add_argument("--export-attachments", dest="attach_dir", help="附件导出目录")
    parser.add_argument("--verbose", action="store_true", help="显示完整正文")

    args = parser.parse_args()

    try:
        import pypff
    except ImportError:
        print("错误: 未找到 pypff 模块。请在 Linux 上运行: pip install libpff-python 或 apt-get install python3-pypff")
        sys.exit(1)

    abs_path = os.path.abspath(args.pst_file)
    if not os.path.exists(abs_path):
        print(f"错误: PST 文件不存在: {abs_path}")
        sys.exit(1)

    file_size = os.path.getsize(abs_path)
    print("=" * 70)
    print(f"Outlook PST 文件解析器 (基于 pypff v{pypff.get_version()})")
    print(f"目标文件 : {abs_path}")
    print(f"文件大小 : {file_size:,} 字节 ({file_size / 1024 / 1024:.2f} MB)")
    print("=" * 70)

    if args.attach_dir:
        os.makedirs(args.attach_dir, exist_ok=True)
        print(f"附件导出目录: {args.attach_dir}\n")

    pst = pypff.file()
    try:
        pst.open(abs_path)
    except Exception as e:
        print(f"打开 PST 文件失败: {e}")
        sys.exit(1)

    root = pst.get_root_folder()
    data = traverse_folders(root, export_dir=args.attach_dir)

    print("\n【一、PST 文件夹层级结构】")
    print_tree(data)

    all_messages = flatten_messages(data)
    print("\n【二、总体统计】")
    print(f"各文件夹累计发现条目总数: {len(all_messages)} 条")

    print("\n【三、条目与邮件详细清单】")
    for idx, item in enumerate(all_messages, 1):
        if "error" in item:
            print(f"[{idx}] {item['folder']} - 读取错误: {item['error']}")
            continue

        print(f"\n[{idx}] 所在目录 : {item['folder']}")
        print(f"    邮件主题 : {item['subject']}")
        print(f"    发件人　 : {item['sender']}")
        if item.get("recipient"):
            print(f"    收件人　 : {item['recipient']}")
        print(f"    日期时间 : {item['date']}")

        att_list = item.get("attachments", [])
        if att_list:
            att_desc = [f"{a.get('filename')} ({a.get('size_bytes', 0):,} 字节)" for a in att_list]
            print(f"    附件数量 : {len(att_list)} 个 ({', '.join(att_desc)})")

        if item.get("body_preview"):
            clean_body = item["body_preview"].replace("\n", " ").replace("\r", " ")
            if not args.verbose and len(clean_body) > 100:
                clean_body = clean_body[:100] + "..."
            print(f"    正文摘要 : {clean_body}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n已将完整解析结果保存至 JSON: {args.json_out}")

    pst.close()
    print("\n解析执行完成。")


if __name__ == "__main__":
    main()
