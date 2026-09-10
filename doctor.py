#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
doctor.py —— 数据体检与修复

检查并自动修复：
1. 编码：GBK/ANSI 文件自动转 UTF-8（用 Excel 编辑过 CSV 就会变成这样）
2. 表头：缺少 author 列时自动补齐（旧 schema 迁移）
3. 重复：同一 bvid 只保留最后一条
4. 分数：interest / value 必须是 1~5 的整数（越界只报告，不擅自改）
5. --enrich：给缺少 UP 主/标题的打分记录补抓 B站元数据（需联网）

用法：
    python doctor.py             # 体检 + 自动修复
    python doctor.py --enrich    # 顺便补齐缺失的 UP 主 / 标题
"""

import argparse
import csv
import io
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import storage  # noqa: E402


def read_text_any(path):
    """尝试 UTF-8 读取；失败则按 GBK 读取。返回 (text, encoding, repaired)。"""
    with open(path, "rb") as f:
        raw = f.read()
    try:
        return raw.decode("utf-8"), "utf-8", False
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace"), "gbk", True


def parse_rows(text):
    return [{(k or ""): (v or "") for k, v in row.items()} for row in csv.DictReader(io.StringIO(text))]


def check_file(path, header, label, enrich=False):
    """体检 + 修复一个 CSV。返回修复后的 rows。"""
    if not os.path.exists(path):
        print(f"[{label}] 文件不存在：{path}")
        return []

    text, enc, repaired = read_text_any(path)
    notes = []
    if repaired:
        notes.append(f"编码修复 {enc} → utf-8")
    if "\r\n" in text:
        text = text.replace("\r\n", "\n")

    rows = parse_rows(text)
    if not rows:
        print(f"[{label}] 空文件（只有表头或无内容）")
        return rows

    # 表头迁移：补 author 列
    fieldnames = list(rows[0].keys())
    if "author" not in fieldnames:
        notes.append("表头迁移：新增 author 列")
        for r in rows:
            r["author"] = ""

    # 去重（同一 bvid 保留最后一条）
    before = len(rows)
    seen = {}
    for r in rows:
        seen[r.get("bvid", "").strip()] = r
    rows = list(seen.values())
    if before != len(rows):
        notes.append(f"去重：{before} → {len(rows)} 行")

    # 分数合法性（只报告）
    bad = []
    if label == "打分":
        for r in rows:
            for key in ("interest", "value"):
                try:
                    if not 1 <= int(str(r.get(key, "")).strip()) <= 5:
                        bad.append((r.get("bvid"), key, r.get(key)))
                except ValueError:
                    bad.append((r.get("bvid"), key, r.get(key)))
        if bad:
            notes.append(f"分数异常 {len(bad)} 处（未改动，请人工确认）")
            for bvid, key, val in bad[:5]:
                print(f"    ! {bvid} 的 {key} = {val!r}")

    # 补齐元数据
    if enrich:
        missing = [r for r in rows if not str(r.get("author", "")).strip()]
        if missing:
            import bili_meta
            print(f"[{label}] 补抓元数据：{len(missing)} 条…")
            for i, r in enumerate(missing, 1):
                bvid = r.get("bvid", "").strip()
                if not bvid:
                    continue
                info = bili_meta.fetch_video(bvid)
                if info.get("author"):
                    r["author"] = info["author"]
                if info.get("title") and not str(r.get("title", "")).strip():
                    r["title"] = info["title"]
                if info.get("tags") and not str(r.get("tags", "")).strip():
                    r["tags"] = info["tags"]
                print(f"    [{i}/{len(missing)}] {bvid} → {r.get('author') or '（未取到）'}")
                time.sleep(0.3)
            notes.append(f"补抓元数据 {len(missing)} 条")

    storage.write_rows(path, rows, header)
    status = "；".join(notes) if notes else "无需修复"
    print(f"[{label}] {len(rows)} 行 · {status}")
    return rows


def main():
    p = argparse.ArgumentParser(description="数据体检与修复")
    p.add_argument("--enrich", action="store_true", help="给缺少 UP 主的记录补抓 B站元数据")
    args = p.parse_args()

    print("=== doctor：数据体检 ===")
    scores = check_file(storage.SCORES_FILE, storage.SCORES_HEADER, "打分", enrich=args.enrich)
    check_file(storage.CANDIDATES_FILE, storage.CANDIDATES_HEADER, "候选", enrich=False)

    if scores:
        likes = sum(1 for r in scores if str(r.get("interest", "")).strip() == "5")
        authors = sorted({r.get("author", "").strip() for r in scores if r.get("author", "").strip()})
        print(f"\n统计：打分 {len(scores)} 条 · 兴趣=5 的 {likes} 条 · 覆盖 UP 主 {len(authors)} 个")
        if authors:
            print("    " + "、".join(authors[:12]) + ("…" if len(authors) > 12 else ""))
    print("体检完成。")


if __name__ == "__main__":
    main()
