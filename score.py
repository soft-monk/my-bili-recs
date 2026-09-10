#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
score.py —— 双轴打分入口

用法：
    python score.py --bvid BV1xx4y1z7Ab --title "视频标题" --tags "科技,科普" --author "某UP主" --interest 4 --value 5
    python score.py --list
    python score.py --delete BV1xx4y1z7Ab      # 撤销某条打分

- interest：兴趣分 1~5（我喜不喜欢 → 个性化排序）
- value   ：价值分 1~5（值不值得看 → 垃圾过滤）
- author  ：UP 主（可选，但强烈建议填——创作者是最强的推荐信号）
- 同一 bvid 只会保留一条记录（重复打分自动覆盖，不会重复计入训练）
- 设计原则：只为"明显超出或低于预期"的视频打分；没打分的视频不进训练样本
"""

import argparse
import os
import sys
from datetime import datetime

# Windows 控制台默认 GBK，强制 UTF-8 输出避免中文乱码
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import storage  # noqa: E402


def add_score(bvid, title, tags, author, interest, value):
    if not bvid:
        print("错误：--bvid 不能为空（例如 BV1xx4y1z7Ab）")
        sys.exit(1)
    for name, v in (("interest", interest), ("value", value)):
        if v is None or not 1 <= int(v) <= 5:
            print(f"错误：{name} 必须是 1~5 的整数")
            sys.exit(1)

    storage.upsert_score({
        "bvid": bvid.strip(),
        "title": (title or "").strip(),
        "tags": (tags or "").strip(),
        "author": (author or "").strip(),
        "interest": int(interest),
        "value": int(value),
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    print(f"已记录：{title or bvid}  兴趣={interest} 价值={value}"
          + (f"  UP主={author}" if author else ""))


def list_scores():
    rows = storage.load_scores()
    if not rows:
        print("还没有任何打分。先执行：python score.py --bvid BVxxx --title ... --interest 4 --value 5")
        return
    print(f"共 {len(rows)} 条打分：")
    for r in rows:
        author = f" · {r.get('author')}" if r.get("author") else ""
        print(f"  兴趣={r.get('interest')} 价值={r.get('value')}  "
              f"{r.get('title') or r.get('bvid', '?')}{author}")


def main():
    p = argparse.ArgumentParser(description="双轴打分（兴趣/价值）入口")
    p.add_argument("--bvid", help="视频 BV 号")
    p.add_argument("--title", help="视频标题")
    p.add_argument("--tags", help="标签，分隔符任意（建议用「、」）")
    p.add_argument("--author", help="UP 主名称（强烈建议填）")
    p.add_argument("--interest", type=int, help="兴趣分 1~5")
    p.add_argument("--value", type=int, help="价值分 1~5")
    p.add_argument("--list", action="store_true", help="列出已有打分")
    p.add_argument("--delete", metavar="BVID", help="删除某条打分（撤销）")
    args = p.parse_args()

    if args.list:
        list_scores()
    elif args.delete:
        ok = storage.delete_score(args.delete)
        print("已删除该打分。" if ok else "没有找到该 bvid 的打分记录。")
    elif args.bvid and args.interest and args.value:
        add_score(args.bvid, args.title, args.tags, args.author, args.interest, args.value)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
