#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
recommend.py —— 双轴推荐引擎（TF-IDF + 原型向量）

原理（详见 docs/B站个人推荐层实现方案.md 第 5 节）：
1. 把打过分数的视频转成特征向量（jieba 分词 + TF-IDF）
2. 双轴原型：
     口味原型 = Σ (兴趣分 − 3) × 向量  → 预测"我喜不喜欢"
     质量原型 = Σ (价值分 − 3) × 向量  → 预测"值不值得看"
3. 对候选视频：先按预测价值分过滤（低于 --value-floor 的淘汰），再按预测兴趣分排序

用法：
    python recommend.py --top 15                # 命令行推荐
    python recommend.py --self-check 8          # 留出法自检
    python serve.py                             # 网页版每日精选（见 serve.py）
"""

import argparse
import csv
import os
import re
import sys

# Windows 控制台默认 GBK，强制 UTF-8 输出避免中文乱码
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SCORES_FILE = os.path.join(DATA_DIR, "scores.csv")
CANDIDATES_FILE = os.path.join(DATA_DIR, "candidates.csv")


def tokenize(text):
    """中文分词；jieba 不可用时回退到按中英文片段粗分。"""
    try:
        import jieba
        return jieba.lcut(text)
    except ImportError:
        return re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+", text)


def load_rows(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def make_features(items):
    from sklearn.feature_extraction.text import TfidfVectorizer
    docs = [f"{it.get('title', '')} {it.get('tags', '')}" for it in items]
    vec = TfidfVectorizer(tokenizer=tokenize)
    return vec.fit_transform(docs).toarray(), vec


def cosine(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(a @ b / (na * nb))


def map_to_1_5(cos):
    """余弦相似度 [-1,1] 粗略映射到 1~5 分。"""
    return float(np.clip(3 + cos * 3, 1, 5))


def run_self_check(items, interest, n_holdout):
    """留出法自检：随机留出 n_holdout 条打分，用其余训练，预测留出条目的兴趣分并对比。"""
    import random

    rnd = random.Random(42)
    idx = list(range(len(items)))
    rnd.shuffle(idx)
    hold, train = idx[:n_holdout], idx[n_holdout:]
    if len(train) < 3:
        print("训练样本不足 3 条，无法自检。")
        return

    train_items = [items[i] for i in train]
    Xt, vec_t = make_features(train_items)
    proto_i = Xt.T @ (interest[train] - 3)
    pn = np.linalg.norm(proto_i)
    if pn == 0:
        print("训练集中全是中性分，无法自检。")
        return

    print(f"自检：留出 {len(hold)} 条打分，用其余 {len(train)} 条训练\n")
    print(f"{'真实兴趣':<8}{'预测兴趣':<8}{'误差':<8}标题")
    hits = 0
    diffs = []
    for i in hold:
        doc = f"{items[i].get('title', '')} {items[i].get('tags', '')}"
        v = vec_t.transform([doc]).toarray()[0]
        pred = map_to_1_5(cosine(v, proto_i))
        actual = int(items[i]["interest"])
        diff = abs(pred - actual)
        diffs.append(diff)
        if diff <= 1:
            hits += 1
        print(f"{actual:<8}{pred:<8.2f}{diff:<8.2f}{items[i].get('title') or items[i].get('bvid')}")
    print(f"\n命中率（误差≤1）：{hits}/{len(hold)} = {hits / len(hold):.0%}  平均误差：{np.mean(diffs):.2f}")
    print("说明：误差≤1 视为命中。命中率高 = 模型已能复现你的口味；命中率低 = 需要更多打分或升级特征。")


def compute_picks(top=10, value_floor=3.0, candidates_path=None):
    """核心推荐：读打分与候选，返回排序结果。失败时打印原因并返回 None。

    返回：{"train_count": int, "cand_count": int, "filtered": int,
           "picks": [{"bvid","title","tags","pred_interest","pred_value"}, ...]}
    供命令行（recommend.py）与网页（serve.py）共用。
    """
    candidates_path = candidates_path or CANDIDATES_FILE

    if not os.path.exists(SCORES_FILE):
        print(f"还没有打分数据：{SCORES_FILE}")
        print('先执行：python score.py --bvid BVxxx --title "标题" --tags "标签" --interest 4 --value 5')
        return None

    scores = load_rows(SCORES_FILE)
    valid = [s for s in scores if (s.get("title") or "").strip() or (s.get("tags") or "").strip()]
    if len(valid) < 3:
        print(f"有特征的打分太少（需要标题或标签）：目前 {len(valid)} 条，至少 3 条才能训练。")
        print("建议回顾式打 30~50 条再评价推荐质量。")
        return None

    X, vec = make_features(valid)
    interest = np.array([int(s["interest"]) for s in valid], dtype=float)
    value = np.array([int(s["value"]) for s in valid], dtype=float)

    # 双轴原型向量（3 分 = 中性，不投票；>3 拉近，<3 推远）
    proto_interest = X.T @ (interest - 3)
    proto_value = X.T @ (value - 3)
    pn_i, pn_v = np.linalg.norm(proto_interest), np.linalg.norm(proto_value)
    if pn_i == 0 and pn_v == 0:
        print("所有打分都是 3 分中性分，模型学不到偏好。请打一些 1、2、4、5 分。")
        return None

    if not os.path.exists(candidates_path):
        print(f"候选文件不存在：{candidates_path}")
        print("先执行：python collector.py --top 30")
        return None
    cands = load_rows(candidates_path)
    if not cands:
        print("候选列表为空。")
        return None

    Xc = vec.transform([f"{c.get('title', '')} {c.get('tags', '')}" for c in cands]).toarray()

    ranked = []
    for i, c in enumerate(cands):
        pred_value = map_to_1_5(cosine(Xc[i], proto_value)) if pn_v else 3.0
        pred_interest = map_to_1_5(cosine(Xc[i], proto_interest)) if pn_i else 3.0
        ranked.append((pred_interest, pred_value, c))
    ranked.sort(key=lambda t: (-t[0], -t[1]))

    passing = [t for t in ranked if t[1] >= value_floor]
    filtered = len(ranked) - len(passing)

    picks = [{"bvid": c.get("bvid", "").strip(),
              "title": c.get("title", "") or c.get("bvid", ""),
              "tags": c.get("tags", ""),
              "pred_interest": round(pi, 2),
              "pred_value": round(pv, 2)}
             for pi, pv, c in passing[:top]]
    return {"train_count": len(valid), "cand_count": len(cands),
            "filtered": filtered, "picks": picks}


def main():
    p = argparse.ArgumentParser(description="双轴推荐引擎")
    p.add_argument("--candidates", default=CANDIDATES_FILE,
                   help="候选视频 csv：bvid,title,tags")
    p.add_argument("--top", type=int, default=10, help="输出条数")
    p.add_argument("--value-floor", type=float, default=3.0,
                   help="预测价值分低于该值的候选直接过滤（垃圾拦截，默认 3）")
    p.add_argument("--self-check", type=int, metavar="N", default=0,
                   help="留出法自检：留出 N 条打分，用其余训练，对比预测兴趣与真实兴趣")
    args = p.parse_args()

    if args.self_check > 0:
        if not os.path.exists(SCORES_FILE):
            print(f"还没有打分数据：{SCORES_FILE}")
            sys.exit(1)
        scores = load_rows(SCORES_FILE)
        valid = [s for s in scores if (s.get("title") or "").strip() or (s.get("tags") or "").strip()]
        if len(valid) < 4:
            print("打分太少，无法自检。")
            sys.exit(1)
        interest = np.array([int(s["interest"]) for s in valid], dtype=float)
        run_self_check(valid, interest, args.self_check)
        return

    result = compute_picks(top=args.top, value_floor=args.value_floor, candidates_path=args.candidates)
    if result is None:
        sys.exit(1)

    print(f"训练样本 {result['train_count']} 条 | 候选 {result['cand_count']} 个")
    print(f"{'排名':<4}{'预测兴趣':<10}{'预测价值':<10}标题")
    for i, pk in enumerate(result["picks"], 1):
        print(f"{i:<4}{pk['pred_interest']:<10.2f}{pk['pred_value']:<10.2f}{pk['title']}  [{pk['bvid']}]")
    if not result["picks"]:
        print("（没有候选通过价值过滤）")
    if result["filtered"] > 0:
        print(f"\n另有 {result['filtered']} 个候选因预测价值分 < {args.value_floor} 被过滤（垃圾拦截）")


if __name__ == "__main__":
    main()
