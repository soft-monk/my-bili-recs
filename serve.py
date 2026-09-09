#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
serve.py —— 每日精选网页 + 反馈回写（推荐结果的"最后一公里"，方案 A）

用法：
    python serve.py               # 启动本地服务并自动打开浏览器
    python serve.py --port 8765   # 指定端口
    python serve.py --no-browser  # 只启动服务，不自动开浏览器

- 页面：卡片流（排名/标题/分区/预测兴趣/预测价值），标题链接到 B站播放页
- 反馈：每张卡片有「满意」「踩雷」按钮 → 写入 data/scores.csv → 刷新页面推荐即重算
  满意 → interest=4, value=4；踩雷 → interest=1, value=1
- 纯标准库实现（http.server），无新依赖
"""

import argparse
import csv
import json
import os
import sys
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Windows 控制台默认 GBK，强制 UTF-8 输出避免中文乱码
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import recommend as rec

HOST = "127.0.0.1"
DEFAULT_PORT = 8765

FEEDBACK_MAP = {
    "good": {"interest": 4, "value": 4, "label": "满意"},
    "bad": {"interest": 1, "value": 1, "label": "踩雷"},
}

_ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}


def esc(s):
    return "".join(_ESC.get(ch, ch) for ch in str(s))


def record_feedback(bvid, title, tags, kind):
    """把网页反馈写成一条双轴打分（追加到 scores.csv）。"""
    if kind not in FEEDBACK_MAP or not bvid:
        return False
    cfg = FEEDBACK_MAP[kind]
    os.makedirs(rec.DATA_DIR, exist_ok=True)
    row = [bvid, title, tags, cfg["interest"], cfg["value"],
           datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    with open(rec.SCORES_FILE, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)
    return True


def render_page(result):
    cards = []
    for i, pk in enumerate(result["picks"], 1):
        link = f"https://www.bilibili.com/video/{pk['bvid']}"
        data = json.dumps({"bvid": pk["bvid"], "title": pk["title"], "tags": pk["tags"]},
                          ensure_ascii=False)
        cards.append(
            '<div class="card"><div class="rank">%d</div><div class="body">'
            '<a class="title" href="%s" target="_blank">%s</a>'
            '<div class="meta">分区：%s · 预测兴趣 <b>%s</b> · 预测价值 <b>%s</b></div>'
            '<div class="actions" data-item="%s">'
            '<button class="good" onclick="fb(this,\'good\')">满意</button>'
            '<button class="bad" onclick="fb(this,\'bad\')">踩雷</button>'
            '<span class="note"></span></div></div></div>'
            % (i, link, esc(pk["title"]), esc(pk["tags"]),
               pk["pred_interest"], pk["pred_value"], esc(data)))

    head = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>我的每日精选</title>
<style>
body{font-family:"Microsoft YaHei",sans-serif;background:#f6f7f9;margin:0;padding:24px}
h1{font-size:22px}
.sub{color:#666;font-size:13px;margin-bottom:16px}
.card{display:flex;gap:14px;background:#fff;border-radius:10px;padding:14px 16px;margin-bottom:10px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.rank{font-size:20px;font-weight:700;color:#fb7299;min-width:28px}
.body{flex:1}
.title{font-size:16px;color:#18191c;text-decoration:none}
.title:hover{color:#00aeec}
.meta{font-size:13px;color:#888;margin-top:6px}
.actions{margin-top:8px}
.actions button{border:none;border-radius:6px;padding:4px 14px;margin-right:8px;cursor:pointer;font-size:13px;color:#fff}
.good{background:#00aeec}
.bad{background:#f25d8e}
.note{color:#888;font-size:12px;margin-left:6px}
</style></head><body>
<h1>我的每日精选</h1>
"""
    sub = ('<div class="sub">训练样本 %d 条 · 候选 %d 个 · 已过滤 %d 个 · '
           '看完视频回到本页点「满意/踩雷」，刷新页面推荐即更新</div>'
           % (result["train_count"], result["cand_count"], result["filtered"]))
    tail = """<script>
async function fb(el,kind){
 const item=JSON.parse(el.parentElement.dataset.item);
 const res=await fetch('/feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.assign(item,{kind}))});
 const r=await res.json();
 el.parentElement.querySelector('.note').textContent=r.ok?('已记录：'+(kind==='good'?'满意':'踩雷')+'（刷新页面生效）'):'记录失败';
}
</script></body></html>"""
    return head + sub + "".join(cards) + tail


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            result = rec.compute_picks(top=20, value_floor=3.0)
            if result is None:
                body = ("<meta charset='utf-8'><h2>数据不足</h2>"
                        "<p>先打分（score.py / 网页反馈），再拉候选（collector.py）。</p>")
                self._send(200, "text/html; charset=utf-8", body)
            else:
                self._send(200, "text/html; charset=utf-8", render_page(result))
        else:
            self._send(404, "text/plain; charset=utf-8", "not found")

    def do_POST(self):
        if self.path == "/feedback":
            try:
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                ok = record_feedback(payload.get("bvid", ""), payload.get("title", ""),
                                     payload.get("tags", ""), payload.get("kind", ""))
                self._send(200, "application/json; charset=utf-8",
                           json.dumps({"ok": ok}, ensure_ascii=False))
            except Exception as e:
                self._send(400, "application/json; charset=utf-8",
                           json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        else:
            self._send(404, "text/plain; charset=utf-8", "not found")

    def _send(self, code, ctype, body):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass  # 静默访问日志


def main():
    p = argparse.ArgumentParser(description="每日精选网页")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = p.parse_args()

    url = f"http://{HOST}:{args.port}/"
    print(f"每日精选：{url}")
    print("看完视频回到本页点「满意/踩雷」，分数会写回 data/scores.csv；Ctrl+C 停止服务。")
    if not args.no_browser:
        webbrowser.open(url)

    server = ThreadingHTTPServer((HOST, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")


if __name__ == "__main__":
    main()
