#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
recommend.py —— 双轴推荐引擎

流程（详见 docs/B站个人推荐层实现方案.md 第 5 节）：
1. 训练：读取 data/scores.csv 全部打分 → 双轴原型（兴趣 / 价值）
2. 候选：读取 data/candidates.csv → **排除已打分** → 价值过滤 → 兴趣排序
3. 探索位：按天固定随机，插入少量低相似度候选，防回音室
4. UP 去重：同一作者最多 N 条
5. 可解释：给出每条推荐贡献最大的关键词（"为什么推荐给你"）
6. 每日清单：当天首次生成后固定不变，次日自动重算

用法：
    python recommend.py --top 10          # 直接算一份（每次重新排序）
    python recommend.py --daily           # 使用/生成今日清单（当天固定）
    python recommend.py --refresh         # 强制重算今日清单
    python recommend.py --explain         # 附带"为什么推荐"
    python recommend.py --self-check 8    # 留出法自检
"""

import argparse
import json
import os
import random
import re
import sys
from datetime import date, datetime

# Windows 控制台默认 GBK，强制 UTF-8 输出避免中文乱码
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import storage  # noqa: E402

DATA_DIR = storage.DATA_DIR
SCORES_FILE = storage.SCORES_FILE
CANDIDATES_FILE = storage.CANDIDATES_FILE
DAILY_DIR = storage.DAILY_DIR

# 中文停用词：去掉这些噪声词，TF-IDF 的权重才会落在真正的主题词上
STOPWORDS = set("""
的 了 是 在 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自己 这 那 什么 怎么
为什么 如何 我们 他们 她们 你们 这个 那个 这些 那些 但是 因为 所以 就是 可以 这样 那样 还是 或者
如果 已经 但 与 及 被 把 让 从 对 为 于 之 其 中 下 里 个 们 更 最 太 再 又 还 只 才 而 并 且 或 等
呢 吧 啊 呀 哦 嗯 吗 一下 一直 之后 之前 现在 时候 知道 觉得
""".split())


def tokenize(text):
    """中文分词；jieba 不可用时回退到按中英文片段粗分。"""
    try:
        import jieba
        return jieba.lcut(text)
    except ImportError:
        return re.findall(r"[\u4e00-\u9fff]+|[A-Za-z0-9]+", text)


def row_text(item):
    """特征文本 = 标题 + 标签 + UP 主（UP 主是最强的创作者信号）。"""
    return " ".join(str(item.get(k, "") or "") for k in ("title", "tags", "author")).strip()


def make_features(items):
    from sklearn.feature_extraction.text import TfidfVectorizer
    docs = [row_text(it) for it in items]
    vec = TfidfVectorizer(tokenizer=tokenize, stop_words=list(STOPWORDS), token_pattern=None)
    return vec.fit_transform(docs).toarray(), vec


def cosine(a, b):
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(a @ b / (na * nb))


def map_to_1_5(cos):
    """余弦相似度 [-1,1] 粗略映射到 1~5 分。"""
    return float(np.clip(3 + cos * 3, 1, 5))


def to_int(value, default=3):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def valid_scores():
    """有特征文本的打分记录。"""
    return [r for r in storage.load_scores() if row_text(r)]


def train_prototypes(valid):
    """返回 (vec, 兴趣原型, 价值原型, 兴趣分数组, 价值分数组)。"""
    X, vec = make_features(valid)
    interest = np.array([to_int(r.get("interest")) for r in valid], dtype=float)
    value = np.array([to_int(r.get("value")) for r in valid], dtype=float)
    proto_i = X.T @ (interest - 3)   # 3 分 = 中性，不投票
    proto_v = X.T @ (value - 3)
    return vec, proto_i, proto_v, interest, value


def explain_pick(vec, x, proto_i, k=4):
    """返回对该候选贡献最大的关键词（"为什么推荐给你"）。"""
    contrib = x * proto_i
    if contrib.size == 0:
        return []
    names = vec.get_feature_names_out()
    order = np.argsort(-contrib)

    def collect(allow_short=False):
        out = []
        for idx in order:
            if contrib[idx] <= 0:
                break
            term = str(names[idx]).strip()
            if not term or term in STOPWORDS:
                continue
            if not allow_short and len(term) < 2 and not term.isascii():
                continue
            if all(ch in "，。！？、；：\"'（）《》…—-· " for ch in term):
                continue
            out.append(term)
            if len(out) >= k:
                break
        return out

    # 优先取语义完整的词；若全是单字（jieba 切出的碎片），退化到不过滤长度
    return collect() or collect(allow_short=True)


def compute_picks(top=10, value_floor=3.0, value_drop_pct=25.0, explore=2,
                  per_author_cap=2, seed=None, candidates_path=None):
    """核心推荐：返回 {"train_count","cand_count","filtered","picks":[...]}；失败返回 None。"""
    candidates_path = candidates_path or CANDIDATES_FILE

    valid = valid_scores()
    if len(valid) < 3:
        print(f"打分数据不足：至少需要 3 条有标题/标签的打分，当前 {len(valid)} 条。")
        return None

    vec, proto_i, proto_v, _, _ = train_prototypes(valid)
    if not np.any(proto_i) and not np.any(proto_v):
        print("所有打分都是 3 分中性分，模型学不到偏好。请打一些 1、2、4、5 分。")
        return None

    cands = storage.load_rows(candidates_path)
    if not cands:
        print(f"候选为空或不存在：{candidates_path}（先运行 python collector.py --top 30）")
        return None

    # A1：排除已打分的视频（不会再推荐你看过的）
    scored = storage.scored_bvids()
    cands = [c for c in cands
             if c.get("bvid", "").strip() and c.get("bvid", "").strip() not in scored]
    if not cands:
        print("候选在排除已打分后为空。运行 python collector.py 拉新候选。")
        return None

    Xc = vec.transform([row_text(c) for c in cands]).toarray()
    pi = np.array([map_to_1_5(cosine(Xc[i], proto_i)) for i in range(len(cands))])
    pv = np.array([map_to_1_5(cosine(Xc[i], proto_v)) for i in range(len(cands))])

    # 价值过滤：绝对阈值 + 动态分位（A8，适应候选池整体分布）
    floor = float(value_floor)
    if value_drop_pct and value_drop_pct > 0:
        floor = max(floor, float(np.percentile(pv, value_drop_pct)))
    keep = [i for i in range(len(cands)) if pv[i] >= floor]
    filtered = len(cands) - len(keep)
    if not keep:
        print("没有候选通过价值过滤（可降低 --value-drop-pct 或 --value-floor）。")
        return None

    keep.sort(key=lambda i: -pi[i])

    # 匹配度：在通过过滤的池子里做极值归一化，让数字有区分度（A7）
    vals = pi[keep]
    lo, hi = float(vals.min()), float(vals.max())
    span = (hi - lo) or 1.0

    def pack(i, is_explore=False):
        c = cands[i]
        return {
            "bvid": c.get("bvid", "").strip(),
            "title": c.get("title", "") or c.get("bvid", ""),
            "tags": c.get("tags", ""),
            "author": c.get("author", ""),
            "pred_interest": round(float(pi[i]), 2),
            "pred_value": round(float(pv[i]), 2),
            "match": int(round(100 * (float(pi[i]) - lo) / span)),
            "explore": bool(is_explore),
            "why": (["探索位：故意跳出你的口味圈"] if is_explore
                    else explain_pick(vec, Xc[i], proto_i)),
        }

    core_n = max(0, top - max(0, explore))
    picks, author_count = [], {}
    for i in keep:
        if len(picks) >= core_n:
            break
        author = (cands[i].get("author") or "").strip()
        if author and author_count.get(author, 0) >= max(1, per_author_cap):
            continue   # A11：同一 UP 主限量
        if author:
            author_count[author] = author_count.get(author, 0) + 1
        picks.append(pack(i))

    # A10：探索位——从相似度较低的剩余候选里随机抽（同一天种子固定）
    if explore > 0:
        used = {p["bvid"] for p in picks}
        rest = [i for i in keep if cands[i].get("bvid", "").strip() not in used]
        if rest:
            rest_sorted = sorted(rest, key=lambda i: pi[i])       # 偏好相似度低的
            pool = rest_sorted[: max(len(rest_sorted) // 2, 1)]
            rnd = random.Random(seed)
            for i in rnd.sample(pool, min(explore, len(pool))):
                picks.append(pack(i, is_explore=True))

    return {"train_count": len(valid), "cand_count": len(cands),
            "filtered": filtered, "picks": picks}


# ---------------- 每日清单（B1：当天固定，次日重算） ----------------

def daily_path(day=None):
    return os.path.join(DAILY_DIR, f"{day or date.today().isoformat()}.json")


def load_daily(day=None):
    p = daily_path(day)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_daily(snap, day=None):
    os.makedirs(DAILY_DIR, exist_ok=True)
    with open(daily_path(day), "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)


def generate_daily(top=10, force=False, **kwargs):
    """生成今日清单；当天已存在且未 force 时直接复用，并保留已有反馈状态。"""
    today = date.today().isoformat()
    old = load_daily(today)
    if old and not force:
        return old

    kwargs.setdefault("seed", int(today.replace("-", "")))
    result = compute_picks(top=top, **kwargs)
    if result is None:
        return None

    feedback_map = {it["bvid"]: it.get("feedback")
                    for it in (old or {}).get("items", []) if it.get("feedback")}
    items = []
    for p in result["picks"]:
        p = dict(p)
        p["feedback"] = feedback_map.get(p["bvid"])
        items.append(p)

    snap = {"date": today,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "train_count": result["train_count"],
            "cand_count": result["cand_count"],
            "filtered": result["filtered"],
            "items": items}
    save_daily(snap, today)
    return snap


def run_self_check(items, interest, n_holdout):
    """留出法自检：随机留出 n_holdout 条打分，用其余训练，预测留出条目的兴趣分并对比。"""
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
    if not np.any(proto_i):
        print("训练集中全是中性分，无法自检。")
        return

    print(f"自检：留出 {len(hold)} 条打分，用其余 {len(train)} 条训练\n")
    print(f"{'真实兴趣':<8}{'预测兴趣':<8}{'误差':<8}标题")
    hits, diffs = 0, []
    for i in hold:
        x = vec_t.transform([row_text(items[i])]).toarray()[0]
        pred = map_to_1_5(cosine(x, proto_i))
        actual = to_int(items[i].get("interest"))
        diff = abs(pred - actual)
        diffs.append(diff)
        if diff <= 1:
            hits += 1
        print(f"{actual:<8}{pred:<8.2f}{diff:<8.2f}{items[i].get('title') or items[i].get('bvid')}")
    print(f"\n命中率（误差≤1）：{hits}/{len(hold)} = {hits / len(hold):.0%}  平均误差：{np.mean(diffs):.2f}")
    print("说明：误差≤1 视为命中。命中率高 = 模型已能复现你的口味；命中率低 = 需要更多打分或升级特征。")


def main():
    p = argparse.ArgumentParser(description="双轴推荐引擎")
    p.add_argument("--candidates", default=CANDIDATES_FILE, help="候选 csv：bvid,title,tags,author")
    p.add_argument("--top", type=int, default=10, help="输出条数")
    p.add_argument("--value-floor", type=float, default=3.0, help="预测价值分绝对下限")
    p.add_argument("--value-drop-pct", type=float, default=25.0,
                   help="额外过滤掉预测价值最低的百分比（0 = 关闭）")
    p.add_argument("--explore", type=int, default=2, help="探索位数量（防回音室）")
    p.add_argument("--per-author", type=int, default=2, help="同一 UP 主最多条数")
    p.add_argument("--explain", action="store_true", help="打印「为什么推荐」")
    p.add_argument("--daily", action="store_true", help="使用/生成今日清单（当天固定）")
    p.add_argument("--refresh", action="store_true", help="强制重算今日清单")
    p.add_argument("--self-check", type=int, metavar="N", default=0,
                   help="留出法自检：留出 N 条打分做验证")
    args = p.parse_args()

    if args.self_check > 0:
        valid = valid_scores()
        if len(valid) < 4:
            print("打分太少，无法自检。")
            sys.exit(1)
        _, _, _, interest, _ = train_prototypes(valid)
        run_self_check(valid, interest, args.self_check)
        return

    common = dict(value_floor=args.value_floor, value_drop_pct=args.value_drop_pct,
                  explore=args.explore, per_author_cap=args.per_author,
                  candidates_path=args.candidates)

    if args.daily or args.refresh:
        snap = generate_daily(top=args.top, force=args.refresh, **common)
        if snap is None:
            sys.exit(1)
        print(f"今日清单 {snap['date']}（训练 {snap['train_count']} 条 · 候选 {snap['cand_count']} 个 "
              f"· 价值过滤 {snap['filtered']} 个）")
        for i, it in enumerate(snap["items"], 1):
            tag = "[探索]" if it.get("explore") else "      "
            fb = f"  已反馈:{it['feedback']}" if it.get("feedback") else ""
            author = f" · {it['author']}" if it.get("author") else ""
            print(f"{i:<3}{tag} 匹配{it.get('match', 0):>3} 兴趣{it['pred_interest']:<5} "
                  f"价值{it['pred_value']:<5}{it['title']}{author}{fb}")
            if it.get("why"):
                print(f"          为什么：{'、'.join(it['why'])}")
        return

    result = compute_picks(top=args.top, **common)
    if result is None:
        sys.exit(1)

    print(f"训练样本 {result['train_count']} 条 | 候选 {result['cand_count']} 个 | "
          f"价值过滤 {result['filtered']} 个")
    print(f"{'排名':<4}{'匹配':<6}{'预测兴趣':<10}{'预测价值':<10}标题 / UP主")
    for i, pk in enumerate(result["picks"], 1):
        tag = "[探索] " if pk["explore"] else ""
        author = f" · {pk['author']}" if pk.get("author") else ""
        print(f"{i:<4}{pk['match']:<6}{pk['pred_interest']:<10.2f}{pk['pred_value']:<10.2f}"
              f"{tag}{pk['title']}{author}  [{pk['bvid']}]")
        if args.explain and pk.get("why"):
            print(f"        为什么：{'、'.join(pk['why'])}")


if __name__ == "__main__":
    main()
