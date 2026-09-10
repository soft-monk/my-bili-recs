#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
storage.py —— 数据文件读写（schema 的唯一定义处）

所有模块统一从这里读写 data/，避免各处 schema 不一致导致列错位。
"""

import csv
import os

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE, "data")
SCORES_FILE = os.path.join(DATA_DIR, "scores.csv")
CANDIDATES_FILE = os.path.join(DATA_DIR, "candidates.csv")
DAILY_DIR = os.path.join(DATA_DIR, "daily")

# 打分表：author 是第 1 批新增的 UP 主字段（旧文件由 doctor.py 迁移）
SCORES_HEADER = ["bvid", "title", "tags", "author", "interest", "value", "ts"]
CANDIDATES_HEADER = ["bvid", "title", "tags", "author"]


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_rows(path):
    """读取 CSV，返回 list[dict]；文件不存在返回 []。"""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return [{(k or ""): (v or "") for k, v in row.items()} for row in csv.DictReader(f)]


def write_rows(path, rows, header):
    ensure_data_dir()
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in header})


def load_scores():
    return load_rows(SCORES_FILE)


def scored_bvids():
    return {r.get("bvid", "").strip() for r in load_scores() if r.get("bvid", "").strip()}


def upsert_score(entry):
    """按 bvid 覆盖写入一条打分（同一视频永远只有一行，避免重复计入训练）。"""
    bvid = str(entry.get("bvid", "")).strip()
    rows = [r for r in load_scores() if r.get("bvid", "").strip() != bvid]
    rows.append(entry)
    write_rows(SCORES_FILE, rows, SCORES_HEADER)


def delete_score(bvid):
    """删除某视频的打分记录；返回是否真的删掉了。"""
    bvid = str(bvid).strip()
    rows = load_scores()
    kept = [r for r in rows if r.get("bvid", "").strip() != bvid]
    if len(kept) == len(rows):
        return False
    write_rows(SCORES_FILE, kept, SCORES_HEADER)
    return True
