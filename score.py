#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
score.py —— 双轴打分入口（M1 版，纯本地）

用法：
    python score.py --bvid BV1xx4y1z7Ab --title "视频标题" --tags "科技,科普" --interest 4 --value 5
    python score.py --list

- interest：兴趣分 1~5（我喜不喜欢 → 个性化排序）
- value   ：价值分 1~5（值不值得看 → 垃圾过滤）
- 分数写入 data/scores.csv（随私有仓库同步，多台设备共享打分）
- 设计原则：只为"明显超出或低于预期"的视频打分；没打分的视频不进训练样本
"""

import argparse
import csv
import os
import sys
from datetime import datetime

# Windows 控制台默认 GBK，强制 UTF-8 输出避免中文乱码
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SCORES_FILE = os.path.join(DATA_DIR, "scores.csv")
HEADER = ["bvid", "title", "tags", "interest", "value", "ts"]


def ensure_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(SCORES_FILE):
        with open(SCORES_FILE, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(HEADER)


def add_score(bvid, title, tags, interest, value):
    if not bvid:
        print("错误：--bvid 不能为空（例如 BV1xx4y1z7Ab）")
        sys.exit(1)
    for name, v in [("interest", interest), ("value", value)]:
        if v is None or not 1 <= int(v) <= 5:
            print(f"错误：{name} 必须是 1~5 的整数")
            sys.exit(1)
    ensure_file()
    row = [bvid, title or "", tags or "", int(interest), int(value),
           datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    with open(SCORES_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)
    print(f"已记录：{title or bvid}  兴趣={interest} 价值={value}")


def list_scores():
    if not os.path.exists(SCORES_FILE):
        print("还没有任何打分。先执行：python score.py --bvid ... --interest 4 --value 5")
        return
    with open(SCORES_FILE, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("还没有任何打分。先执行：python score.py --bvid ... --interest 4 --value 5")
        return
    print(f"共 {len(rows)} 条打分：")
    for r in rows:
        title = r.get("title") or r.get("bvid", "?")
        print(f"  兴趣={r['interest']} 价值={r['value']}  {title}")


def main():
    p = argparse.ArgumentParser(description="双轴打分（兴趣/价值）入口")
    p.add_argument("--bvid", help="视频 BV 号")
    p.add_argument("--title", help="视频标题（M1 手动填，M2 起自动抓取）")
    p.add_argument("--tags", help="标签，逗号分隔")
    p.add_argument("--interest", type=int, help="兴趣分 1~5")
    p.add_argument("--value", type=int, help="价值分 1~5")
    p.add_argument("--list", action="store_true", help="列出已有打分")
    args = p.parse_args()

    if args.list:
        list_scores()
    elif args.bvid and args.interest and args.value:
        add_score(args.bvid, args.title, args.tags, args.interest, args.value)
    else:
        p.print_help()


if __name__ == "__main__":
    main()
