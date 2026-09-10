#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bili_meta.py —— 通过 B站公开接口抓取视频元数据（无需登录）

用途：给打分补全标题/UP主/标签（doctor.py --enrich）、后续 score.py --url 自动抓取。

注意：显式禁用一切代理（本机 IE 代理 127.0.0.1:7897 会破坏 Python 网络）。
"""

import json
import urllib.request

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.com/",
}


def _get_json(url, timeout=10):
    req = urllib.request.Request(url, headers=HEADERS)
    with OPENER.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_video(bvid, with_tags=True, timeout=10):
    """返回 {title, author, tname, tags, duration, view}；失败返回已抓到的部分（不抛异常）。"""
    info = {}
    try:
        data = _get_json(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}", timeout)
        if data.get("code") == 0:
            d = data.get("data") or {}
            owner = d.get("owner") or {}
            stat = d.get("stat") or {}
            info["title"] = (d.get("title") or "").strip()
            info["author"] = (owner.get("name") or "").strip()
            info["tname"] = (d.get("tname") or "").strip()
            info["duration"] = d.get("duration")
            info["view"] = stat.get("view")
    except Exception:
        return info

    if with_tags:
        try:
            t = _get_json(f"https://api.bilibili.com/x/tag/archive/tags?bvid={bvid}", timeout)
            if t.get("code") == 0:
                names = [str(x.get("tag_name", "")).strip() for x in (t.get("data") or [])]
                names = [n for n in names if n]
                if names:
                    info["tags"] = "、".join(names)
        except Exception:
            pass
    return info


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        print(json.dumps(fetch_video(sys.argv[1]), ensure_ascii=False, indent=2))
    else:
        print("用法：python bili_meta.py BV1xx4y1z7Ab")
