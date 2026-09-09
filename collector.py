#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collector.py —— 候选池收集（M2 版）：拉取 B站分区排行榜作为候选

- 不依赖登录 cookie，只用公开的排行榜接口（每分区 top N）
- 已打过分数的视频自动排除（不重复推荐）
- 候选写入 data/candidates.csv（UTF-8，bvid,title,tags 三列，tags 用分区名）
- 默认分区对应你的兴趣画像，可在 RIDS 里增删（rid: 分区名）

用法：
    python collector.py            # 拉全部默认分区
    python collector.py --top 30   # 每分区取前 30

后续规划：订阅 UP 主新投稿（需登录 cookie）、搜索词定向拉取
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.request

# Windows 控制台默认 GBK，强制 UTF-8 输出避免中文乱码
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SCORES_FILE = os.path.join(DATA_DIR, "scores.csv")
CANDIDATES_FILE = os.path.join(DATA_DIR, "candidates.csv")

# 分区 id -> 分区名（默认集合对应兴趣画像：知识/科技/纪录片/音乐/鬼畜/游戏/动画/生活）
RIDS = {36: "知识", 188: "科技", 177: "纪录片", 3: "音乐", 119: "鬼畜", 4: "游戏", 1: "动画", 160: "生活"}

# 显式禁用一切代理（本机 IE 代理 127.0.0.1:7897 会破坏 python 网络）
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def http_get_json(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.bilibili.com/",
    })
    with OPENER.open(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def load_scored_bvids():
    if not os.path.exists(SCORES_FILE):
        return set()
    with open(SCORES_FILE, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return {r.get("bvid", "").strip() for r in rows}


def main():
    p = argparse.ArgumentParser(description="B站分区排行榜候选收集")
    p.add_argument("--top", type=int, default=30, help="每分区取前 N 条")
    args = p.parse_args()

    scored = load_scored_bvids()
    print(f"已打分视频 {len(scored)} 个（自动排除）\n")

    cands = {}
    for rid, name in RIDS.items():
        url = f"https://api.bilibili.com/x/web-interface/ranking/v2?rid={rid}&type=all"
        try:
            data = http_get_json(url)
        except Exception as e:
            print(f"[{name}] 拉取失败：{e}")
            continue
        if data.get("code") != 0:
            print(f"[{name}] 接口返回异常 code={data.get('code')}：{data.get('message')}")
            continue
        items = data.get("data", {}).get("list", [])
        added = 0
        for it in items[:args.top]:
            bvid = it.get("bvid", "")
            if not bvid or bvid in scored or bvid in cands:
                continue
            title = it.get("title", "").strip().replace("\n", " ")
            tname = it.get("tname", name)
            cands[bvid] = (title, tname)
            added += 1
        print(f"[{name}] top{args.top} → 新增候选 {added}")
        time.sleep(0.5)

    if not cands:
        print("\n没有拉到任何候选。")
        sys.exit(1)

    with open(CANDIDATES_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["bvid", "title", "tags"])
        for bvid, (title, tname) in cands.items():
            w.writerow([bvid, title, tname])

    print(f"\n候选池已写入 {CANDIDATES_FILE}，共 {len(cands)} 个")
    print("下一步：python recommend.py --top 15")


if __name__ == "__main__":
    main()
