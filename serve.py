#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
serve.py —— 每日精选网页（每日清单 + 三档反馈 + 为什么推荐）

用法：
    python serve.py                 # 默认 http://127.0.0.1:8765/，自动打开浏览器
    python serve.py --no-browser    # 静默启动（只起服务）
    python serve.py --port 9000     # 指定端口
    python serve.py --top 10        # 今日清单条数（首次生成时生效）
    python serve.py --refresh       # 启动时强制重算今日清单

清单语义（B1）：
- 当天首次打开时生成 data/daily/YYYY-MM-DD.json（默认 10 条），当天固定不变
- 已打分（含反馈）的视频不会再进入候选；次日自动生成新清单
- 点「喜欢 / 无感 / 踩雷」→ 三档反馈写回 scores.csv；同一条可「撤销」

三档反馈映射（B4）：
- 喜欢 like → 兴趣 5 / 价值 4
- 无感 meh  → 兴趣 3 / 价值 3（中性，不改模型，但排除该视频不再推荐）
- 踩雷 bad  → 兴趣 1 / 价值 1

接口（供油猴脚本 / 其他界面）：
- GET  /api/ping        心跳（极轻，不跑模型）
- GET  /api/daily       今日清单 JSON
- POST /api/feedback    {bvid, kind} 或 {bvid, undo: true}
- POST /api/score       {bvid,title,tags,author,interest,value}
- GET  /?refresh=1      强制重算今日清单
"""

import argparse
import json
import os
import sys
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# Windows 控制台默认 GBK，强制 UTF-8 输出避免中文乱码
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import storage          # noqa: E402
import recommend as rec  # noqa: E402

HOST = "127.0.0.1"
DEFAULT_PORT = 8765

FEEDBACK_MAP = {
    "like": {"interest": 5, "value": 4, "label": "喜欢"},
    "meh": {"interest": 3, "value": 3, "label": "无感"},
    "bad": {"interest": 1, "value": 1, "label": "踩雷"},
}

# E1 第一层防护：只允许本机与 B站来源的跨域写操作（油猴脚本走 GM_xmlhttpRequest 时 Origin 为空）
ALLOWED_ORIGIN_HOSTS = ("127.0.0.1", "localhost", "www.bilibili.com", "bilibili.com")

CONFIG = {"top": 10, "pick_kwargs": {}}

_ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}


def esc(s):
    return "".join(_ESC.get(ch, ch) for ch in str(s))


def origin_allowed(origin):
    if not origin:
        return True   # 同源请求 / 非浏览器客户端
    try:
        host = (urlparse(origin).hostname or "").lower()
    except Exception:
        return False
    return host in ALLOWED_ORIGIN_HOSTS


# ---------------- 业务逻辑 ----------------

def get_snapshot(force=False):
    return rec.generate_daily(top=CONFIG["top"], force=force, **CONFIG["pick_kwargs"])


def set_snapshot_feedback(bvid, kind):
    """把反馈状态写进今日清单（清单当天不变，但状态要更新）。"""
    snap = rec.load_daily()
    if not snap:
        return
    changed = False
    for it in snap.get("items", []):
        if it.get("bvid") == bvid:
            it["feedback"] = kind
            changed = True
    if changed:
        rec.save_daily(snap)


def apply_feedback(bvid, kind=None, undo=False, item=None):
    """写回或撤销反馈。返回 (ok, message)。"""
    bvid = str(bvid or "").strip()
    if not bvid:
        return False, "缺少 bvid"

    if undo:
        removed = storage.delete_score(bvid)
        set_snapshot_feedback(bvid, None)
        return True, ("已撤销并删除打分" if removed else "没有找到打分记录")

    if kind not in FEEDBACK_MAP:
        return False, "未知反馈类型"
    cfg = FEEDBACK_MAP[kind]
    storage.upsert_score({
        "bvid": bvid,
        "title": (item or {}).get("title", ""),
        "tags": (item or {}).get("tags", ""),
        "author": (item or {}).get("author", ""),
        "interest": cfg["interest"],
        "value": cfg["value"],
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    set_snapshot_feedback(bvid, kind)
    return True, f"已记录：{cfg['label']}"


# ---------------- 页面渲染 ----------------

def render_page(snap):
    scored = storage.scored_bvids()
    items = snap.get("items", [])
    done = sum(1 for it in items if it.get("feedback") or it.get("bvid") in scored)

    cards = []
    for i, it in enumerate(items, 1):
        bvid = it.get("bvid", "")
        fb = it.get("feedback")
        scored_elsewhere = (not fb) and (bvid in scored)
        cls = " done" if (fb or scored_elsewhere) else ""

        badges = ""
        if it.get("explore"):
            badges += '<span class="badge explore">探索</span>'
        if fb:
            badges += f'<span class="badge fb-{esc(fb)}">{esc(FEEDBACK_MAP.get(fb, {}).get("label", fb))}</span>'
        elif scored_elsewhere:
            badges += '<span class="badge done-badge">已打分</span>'

        why = "、".join(it.get("why") or [])
        why_html = f'<div class="why">为什么：{esc(why)}</div>' if why else ""
        author = it.get("author") or ""
        author_html = f'<span class="author">{esc(author)}</span> · ' if author else ""
        # 匹配度条
        match = int(it.get("match", 0) or 0)
        match_html = (f'<div class="matchwrap" title="匹配度 {match}/100">'
                      f'<div class="matchbar" style="width:{max(2, min(100, match))}%"></div>'
                      f'<span class="matchnum">{match}</span></div>')

        data = json.dumps({"bvid": bvid, "title": it.get("title", ""),
                           "tags": it.get("tags", ""), "author": author}, ensure_ascii=False)

        if fb or scored_elsewhere:
            actions = (f'<div class="actions" data-item="{esc(data)}">'
                       f'<button class="undo" onclick="undo(this)">撤销</button>'
                       f'<span class="note"></span></div>')
        else:
            actions = (f'<div class="actions" data-item="{esc(data)}">'
                       f'<button class="like" onclick="fb(this,\'like\')">喜欢</button>'
                       f'<button class="meh" onclick="fb(this,\'meh\')">无感</button>'
                       f'<button class="bad" onclick="fb(this,\'bad\')">踩雷</button>'
                       f'<span class="note"></span></div>')

        cards.append(
            f'<div class="card{cls}">'
            f'<div class="rank">{i}</div>'
            f'<div class="body">'
            f'<a class="title" href="https://www.bilibili.com/video/{esc(bvid)}" target="_blank">'
            f'{esc(it.get("title", ""))}</a> {badges}'
            f'<div class="meta">{author_html}分区：{esc(it.get("tags", ""))} · '
            f'预测兴趣 <b>{it.get("pred_interest")}</b> · 预测价值 <b>{it.get("pred_value")}</b></div>'
            f'{match_html}{why_html}{actions}'
            f'</div></div>')

    head = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>我的每日精选</title>
<style>
body{font-family:"Microsoft YaHei",sans-serif;background:#f6f7f9;margin:0;padding:24px;color:#18191c}
h1{font-size:22px;margin-bottom:6px}
.sub{color:#666;font-size:13px;margin-bottom:6px}
.sub b{color:#fb7299}
.toolbar{margin:10px 0 18px}
.toolbar a{font-size:13px;color:#00aeec;text-decoration:none;margin-right:14px}
.card{display:flex;gap:14px;background:#fff;border-radius:10px;padding:14px 16px;margin-bottom:10px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.card.done{opacity:.55}
.rank{font-size:20px;font-weight:700;color:#fb7299;min-width:28px}
.body{flex:1;min-width:0}
.title{font-size:16px;color:#18191c;text-decoration:none}
.title:hover{color:#00aeec}
.meta{font-size:13px;color:#888;margin-top:6px}
.author{color:#61666d}
.badge{display:inline-block;font-size:11px;padding:1px 7px;border-radius:9px;margin-left:6px;vertical-align:middle}
.badge.explore{background:#e8f5ff;color:#008ac5}
.badge.fb-like{background:#e6f7ee;color:#0a8f4d}
.badge.fb-meh{background:#f0f0f0;color:#666}
.badge.fb-bad{background:#ffecef;color:#d6335c}
.badge.done-badge{background:#f0f0f0;color:#999}
.matchwrap{position:relative;background:#f0f1f3;border-radius:6px;height:14px;margin:8px 0 0;max-width:240px}
.matchbar{background:linear-gradient(90deg,#7ed0f5,#00aeec);height:14px;border-radius:6px}
.matchnum{position:absolute;right:6px;top:-1px;font-size:11px;color:#555}
.why{font-size:12px;color:#9aa0a6;margin-top:6px}
.actions{margin-top:8px}
.actions button{border:none;border-radius:6px;padding:4px 14px;margin-right:8px;cursor:pointer;font-size:13px;color:#fff}
.like{background:#00aeec}.meh{background:#b8bcc2}.bad{background:#f25d8e}.undo{background:#c9ccd1}
.note{color:#888;font-size:12px;margin-left:6px}
</style></head><body>
<h1>我的每日精选</h1>
"""
    sub = (f'<div class="sub">今日 {esc(snap.get("date", ""))} · 进度 <b>{done}/{len(items)}</b> · '
           f'训练样本 {snap.get("train_count", 0)} 条 · 候选 {snap.get("cand_count", 0)} 个 · '
           f'已过滤 {snap.get("filtered", 0)} 个</div>'
           f'<div class="toolbar"><a href="/?refresh=1">重算今日清单</a>'
           f'<a href="/api/daily" target="_blank">清单 JSON</a></div>')

    tail = """<script>
async function post(body){
  const res = await fetch('/api/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  return res.json();
}
async function fb(el,kind){
  const item=JSON.parse(el.closest('.actions').dataset.item);
  const r=await post(Object.assign({},item,{kind}));
  if(r.ok){location.reload();}else{alert(r.message||'记录失败');}
}
async function undo(el){
  const item=JSON.parse(el.closest('.actions').dataset.item);
  const r=await post({bvid:item.bvid,undo:true});
  if(r.ok){location.reload();}else{alert(r.message||'撤销失败');}
}
</script></body></html>"""
    return head + sub + "".join(cards) + tail


# ---------------- HTTP 服务 ----------------

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path in ("/", "/index.html"):
                force = parse_qs(parsed.query).get("refresh", ["0"])[0] in ("1", "true", "yes")
                snap = get_snapshot(force=force)
                if snap is None:
                    self._send(200, "text/html; charset=utf-8",
                               "<meta charset='utf-8'><h2>数据不足</h2>"
                               "<p>先打分（score.py 或网页反馈），再拉候选（collector.py）。</p>")
                else:
                    self._send(200, "text/html; charset=utf-8", render_page(snap))
            elif path == "/api/ping":
                snap = rec.load_daily()
                self._json(200, {"ok": True, "date": (snap or {}).get("date"),
                                 "items": len((snap or {}).get("items", [])),
                                 "train_count": len(storage.load_scores())})
            elif path == "/api/daily":
                snap = get_snapshot()
                if snap is None:
                    self._json(503, {"ok": False, "message": "数据不足"})
                else:
                    self._json(200, snap)
            else:
                self._send(404, "text/plain; charset=utf-8", "not found")
        except Exception as e:
            self._json(500, {"ok": False, "message": str(e)})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if not origin_allowed(self.headers.get("Origin")):
            self._json(403, {"ok": False, "message": "来源不被允许"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception as e:
            self._json(400, {"ok": False, "message": f"请求体解析失败：{e}"})
            return

        try:
            if path == "/api/feedback":
                ok, message = apply_feedback(payload.get("bvid", ""), payload.get("kind"),
                                             bool(payload.get("undo")), payload)
                self._json(200 if ok else 400, {"ok": ok, "message": message})
            elif path == "/api/score":
                bvid = str(payload.get("bvid", "")).strip()
                interest, value = payload.get("interest"), payload.get("value")
                if not bvid or interest is None or value is None:
                    self._json(400, {"ok": False, "message": "需要 bvid / interest / value"})
                elif not (1 <= int(interest) <= 5 and 1 <= int(value) <= 5):
                    self._json(400, {"ok": False, "message": "interest / value 必须是 1~5"})
                else:
                    storage.upsert_score({
                        "bvid": bvid,
                        "title": payload.get("title", ""),
                        "tags": payload.get("tags", ""),
                        "author": payload.get("author", ""),
                        "interest": int(interest),
                        "value": int(value),
                        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    self._json(200, {"ok": True, "message": "已记录"})
            else:
                self._send(404, "text/plain; charset=utf-8", "not found")
        except Exception as e:
            self._json(500, {"ok": False, "message": str(e)})

    def _send(self, code, ctype, body):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False))

    def log_message(self, fmt, *args):
        pass  # 静默访问日志


def main():
    p = argparse.ArgumentParser(description="每日精选网页")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    p.add_argument("--top", type=int, default=10, help="今日清单条数")
    p.add_argument("--refresh", action="store_true", help="启动时强制重算今日清单")
    p.add_argument("--value-floor", type=float, default=3.0)
    p.add_argument("--value-drop-pct", type=float, default=25.0)
    p.add_argument("--explore", type=int, default=2, help="探索位数量")
    p.add_argument("--per-author", type=int, default=2, help="同一 UP 主最多条数")
    args = p.parse_args()

    CONFIG["top"] = args.top
    CONFIG["pick_kwargs"] = {"value_floor": args.value_floor,
                             "value_drop_pct": args.value_drop_pct,
                             "explore": args.explore,
                             "per_author_cap": args.per_author}

    snap = get_snapshot(force=args.refresh)
    url = f"http://{HOST}:{args.port}/"
    print(f"每日精选：{url}")
    if snap:
        print(f"今日清单 {snap['date']}：{len(snap['items'])} 条"
              f"（训练 {snap['train_count']} 条 · 候选 {snap['cand_count']} 个）")
    else:
        print("提示：数据不足，页面会显示引导信息。")
    print("点「喜欢 / 无感 / 踩雷」会写回 data/scores.csv；Ctrl+C 停止服务。")
    if not args.no_browser:
        webbrowser.open(url)

    server = ThreadingHTTPServer((HOST, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
