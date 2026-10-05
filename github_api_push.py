#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kronos/CS2 看板 · GitHub API 推送通道（替代被限速的 git push）

为什么需要它
------------
服务器侧原本用 `git push`（github.com:443），而该端点在腾讯云服务器上实测
<1KB/s 被限速；push 一旦被超时掐断就会损坏 `.git/index`，导致后续 `git add`
全失败、推送再也无法恢复（2026-10-04 出现过 10 小时断供）。

本模块改用 **GitHub Git Database API**（走 api.github.com，与网站部署同一条
稳定的 HTTPS 通道），彻底不碰 git 内部状态：
  - 为**每个变更文件**创建 blob（base64，支持到 100MB，无 Contents API 的 1MB 限制）
  - 以当前 main 为 base_tree，构造只包含这些文件的新 tree
  - 在 main 顶端提交一个新 commit
  - PATCH refs/heads/main 指向新 commit
  - 若提交期间 refs 被他人（如家里 Windows 那台）移动（409/422），自动重取 HEAD
    重建 tree/commit 重试，最多 3 次 —— 自愈，不丢数据。

所有请求走 api.github.com，不依赖本地 .git，因此 `.git/index` 损坏这条路
从根上消失。
"""

import base64
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

API = "https://api.github.com"
UA = {"User-Agent": "cs2-push/1.0"}


def _ssl_ctx():
    return ssl.create_default_context()


def _gh(method, url, token, body=None, ctx=None, timeout=120):
    """发一次 GitHub API 请求。返回 (status, parsed_json_or_none, raw_text)。

    对 409/422 不抛异常，交给上层做冲突重试；其余 4xx/5xx 也返回 status 让上层判。
    """
    headers = {
        "Authorization": "token %s" % token,
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }
    headers.update(UA)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(API + url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            raw = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(raw), raw
            except Exception:
                return r.status, None, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw), raw
        except Exception:
            return e.code, None, raw
    except Exception as e:  # 网络层错误
        return -1, None, str(e)
    return -2, None, "unknown"


def api_push_all(files, message, repo, token, ctx=None, base_dir="."):
    """把 files（相对 base_dir 的路径列表）一次性推到 GitHub main。

    走 Git Database API，单 commit、支持任意大小文件（<=100MB/文件）。

    返回 (ok: bool, failed: list[str])
      ok=True   全部成功
      ok=False 有文件没推上去（failed 列出未能提交的文件名）
    """
    if not token:
        print("[API-PUSH] 无 GH_TOKEN，跳过", file=sys.stderr)
        return False, list(files)
    if ctx is None:
        ctx = _ssl_ctx()

    # 1) 准备：绝对路径 + 过滤不存在的
    full = []
    for f in files:
        p = f if os.path.isabs(f) else os.path.join(base_dir, f)
        if os.path.isfile(p):
            full.append((f, p))
        else:
            print("[API-PUSH] 跳过不存在的文件: %s" % f, file=sys.stderr)
    if not full:
        print("[API-PUSH] 无有效文件可推", file=sys.stderr)
        return False, list(files)

    # 2) 为每个文件创建 blob
    blobs = {}
    for rel, p in full:
        with open(p, "rb") as fh:
            content = fh.read()
        b64 = base64.b64encode(content).decode("ascii")
        st, js, _ = _gh("POST", "/repos/%s/git/blobs" % repo,
                        token, {"content": b64, "encoding": "base64"},
                        ctx=ctx, timeout=180)
        if st != 201 or not js or "sha" not in js:
            print("[API-PUSH] blob 失败 %s: %s %s" % (rel, st, js), file=sys.stderr)
            return False, [r for r, _ in full]
        blobs[rel] = js["sha"]
        print("[API-PUSH] blob ok %s (%d bytes)" % (rel, len(content)))

    # 3) 构造 tree + commit + 更新 ref，带冲突重试
    last_err = None
    for attempt in range(3):
        # 3a) 取当前 main HEAD
        st, js, _ = _gh("GET", "/repos/%s/git/ref/heads/main" % repo, token, ctx=ctx, timeout=30)
        if st != 200 or not js or "object" not in js:
            last_err = "get ref failed: %s %s" % (st, js)
            print("[API-PUSH] %s" % last_err, file=sys.stderr)
            time.sleep(2)
            continue
        head_sha = js["object"]["sha"]
        # 3b) 取 HEAD 的 tree
        st, js, _ = _gh("GET", "/repos/%s/git/commits/%s" % (repo, head_sha), token, ctx=ctx, timeout=30)
        if st != 200 or not js or "tree" not in js:
            last_err = "get commit failed: %s %s" % (st, js)
            print("[API-PUSH] %s" % last_err, file=sys.stderr)
            time.sleep(2)
            continue
        base_tree = js["tree"]["sha"]
        # 3c) 建 tree（base_tree + 本次变更）
        tree_entries = [{"path": rel, "mode": "100644", "type": "blob", "sha": blobs[rel]}
                        for rel, _ in full]
        st, js, _ = _gh("POST", "/repos/%s/git/trees" % repo, token,
                        {"base_tree": base_tree, "tree": tree_entries},
                        ctx=ctx, timeout=60)
        if st != 201 or not js or "sha" not in js:
            last_err = "create tree failed: %s %s" % (st, js)
            print("[API-PUSH] %s" % last_err, file=sys.stderr)
            time.sleep(2)
            continue
        new_tree = js["sha"]
        # 3d) 建 commit
        st, js, _ = _gh("POST", "/repos/%s/git/commits" % repo, token,
                        {"message": message, "tree": new_tree, "parents": [head_sha]},
                        ctx=ctx, timeout=60)
        if st != 201 or not js or "sha" not in js:
            last_err = "create commit failed: %s %s" % (st, js)
            print("[API-PUSH] %s" % last_err, file=sys.stderr)
            time.sleep(2)
            continue
        new_commit = js["sha"]
        # 3e) 更新 ref
        st, js, _ = _gh("PATCH", "/repos/%s/git/refs/heads/main" % repo, token,
                        {"sha": new_commit, "force": False}, ctx=ctx, timeout=30)
        if st == 200 and js and js.get("object", {}).get("sha") == new_commit:
            print("[API-PUSH] 提交成功: %s (files=%d)" % (new_commit[:8], len(full)))
            return True, []
        # 409/422 说明 refs 在我们读 HEAD 之后被别人移动了 → 重试整段
        if st in (409, 422):
            last_err = "ref conflict (%s)，重试" % st
            print("[API-PUSH] %s" % last_err, file=sys.stderr)
            time.sleep(2)
            continue
        last_err = "update ref failed: %s %s" % (st, js)
        print("[API-PUSH] %s" % last_err, file=sys.stderr)
        time.sleep(2)
        continue

    print("[API-PUSH] 重试 3 次仍失败: %s" % last_err, file=sys.stderr)
    return False, [r for r, _ in full]


def _gh_delete(path, repo, token, ctx=None):
    """删除仓库内一个文件（测试清理用）。"""
    if ctx is None:
        ctx = _ssl_ctx()
    st, js, _ = _gh("GET", "/repos/%s/contents/%s" % (repo, path), token, ctx=ctx, timeout=30)
    if st != 200 or not js or "sha" not in js:
        return False
    st, _, _ = _gh("DELETE", "/repos/%s/contents/%s" % (repo, path), token,
                   {"message": "test cleanup", "sha": js["sha"]}, ctx=ctx, timeout=30)
    return st == 200


def _self_test(repo, token, ctx=None, base_dir="."):
    """验证 API 通道：推一个 1KB 小文件 + 一个 1.5MB 大文件，再清理。"""
    print("=== api_push_all 自测 ===")
    small = "__api_test_small.txt"
    big = "__api_test_big.bin"
    sp = os.path.join(base_dir, small)
    bp = os.path.join(base_dir, big)
    with open(sp, "w", encoding="utf-8") as f:
        f.write("api push ok @ %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    with open(bp, "wb") as f:
        f.write(b"\x00" * (1500 * 1024))  # 1.5MB
    ok, failed = api_push_all([small, big], "test: api push self-test",
                              repo, token, ctx=ctx, base_dir=base_dir)
    print("小+大文件推送结果: ok=%s failed=%s" % (ok, failed))
    # 清理
    _gh_delete(small, repo, token, ctx)
    _gh_delete(big, repo, token, ctx)
    print("测试文件已清理")
    return ok


if __name__ == "__main__":
    # 直接运行时做自测；token/repo 从环境变量取（与 update.py 一致）
    import os as _os
    _repo = _os.environ.get("CS2_REPO") or "hintime/cs2-dashboard"
    _tok = (_os.environ.get("GH_TOKEN") or _os.environ.get("GITHUB_TOKEN") or "")
    if not _tok:
        print("需要 GH_TOKEN 环境变量", file=sys.stderr)
        sys.exit(2)
    _ok = _self_test(_repo, _tok, base_dir=".")
    sys.exit(0 if _ok else 1)
