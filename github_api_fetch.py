#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GitHub API 拉取通道（与 github_api_push.py 对称）——解决「服务器侧 git 被限速」。

背景
----
腾讯云服务器到 github.com:443 实测 <1KB/s（git push/clone/pack 全都极慢甚至不可用），
但 api.github.com 通畅。搬服务器时新机若 `git clone`，509M 的 .git 历史根本拉不动。
本脚本用 **Git Data API** 把 main 分支的文件树直接还原到目标目录：
  - 不依赖 git 端点、不需要 .git，绕开限速与 index 损坏链；
  - 能还原【代码 + 顶层数据 JSON + market_history/index_history】。

限制
----
  - price_history.db（1.2GB，>API blob 100MB 上限，且当前只在旧机）**拉不到**，
    必须旧机→新机直传。本脚本默认排除 *.db。
  - GitHub 上的 db 是旧快照，仅作兜底，不作为迁移数据源。

用法
----
    python github_api_fetch.py --repo hintime/cs2-dashboard --ref main \
        --dest /home/ubuntu/cs2-run --exclude 'price_history.db' --max-mb 50
    # token 依次从 --token、$GH_TOKEN、local_keys.env 读取
"""
import argparse
import base64
import os
import sys
import time
import urllib.request
import urllib.error
import json as _json

API = "https://api.github.com"


def _read_token(explicit=None):
    if explicit:
        return explicit.strip()
    t = os.environ.get("GH_TOKEN", "").strip()
    if t:
        return t
    for cand in ("local_keys.env", "/home/ubuntu/cs2-run/local_keys.env"):
        if os.path.exists(cand):
            for line in open(cand, encoding="utf-8"):
                if line.startswith("GH_TOKEN="):
                    return line.split("=", 1)[1].strip().strip("\r\n")
    return ""


def _gh(method, path, token, data=None, timeout=60, retries=3):
    url = API + path
    body = _json.dumps(data).encode() if data is not None else None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "cs2-migrate-fetch")
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, _json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            code = e.code
            if code in (404, 409, 422):
                return code, None          # 调用方决定
            if code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return code, None
        except Exception:
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return 0, None
    return 0, None


def fetch_tree(repo, token, ref="main"):
    st, j = _gh("GET", "/repos/%s/git/trees/%s?recursive=1" % (repo, ref), token, timeout=60)
    if st != 200 or not j or "tree" not in j:
        print("[TREE] 获取失败 st=%s" % st)
        return []
    tree = [e for e in j["tree"] if e.get("type") == "blob"]
    if j.get("truncated"):
        print("[TREE] 警告：树被截断（文件过多），可能不完整")
    return tree


def fetch_blob(repo, token, sha):
    st, j = _gh("GET", "/repos/%s/git/blobs/%s" % (repo, sha), token, timeout=120)
    if st != 200 or not j or "content" not in j:
        return None
    content = j["content"].replace("\n", "")
    if j.get("encoding") == "base64":
        return base64.b64decode(content)
    return content.encode("utf-8")


def fetch_all(repo, token, ref, dest, exclude=(), max_mb=50, only_prefix=None):
    tree = fetch_tree(repo, token, ref)
    ex = {e.lower() for e in exclude}
    limit = max_mb * 1024 * 1024
    picked, skipped = [], []
    for e in tree:
        p = e["path"]
        low = p.lower()
        if any(x in low for x in ex):
            skipped.append((p, "excluded"))
            continue
        if p.endswith(".db") or p.endswith(".sqlite"):
            skipped.append((p, "db-skip"))
            continue
        if e.get("size", 0) > limit:
            skipped.append((p, "too-big %dMB" % (e.get("size", 0) // 1048576)))
            continue
        if only_prefix and not p.startswith(only_prefix):
            skipped.append((p, "prefix-skip"))
            continue
        picked.append(e)
    print("[PLAN] 树内文件 %d → 拉取 %d，跳过 %d" % (len(tree), len(picked), len(skipped)))
    for p, why in skipped:
        print("       skip %-50s %s" % (p, why))
    ok = fail = 0
    total = len(picked)
    t0 = time.time()
    for i, e in enumerate(picked, 1):
        p, sha = e["path"], e["sha"]
        out = os.path.join(dest, p.replace("/", os.sep))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        data = fetch_blob(repo, token, sha)
        if data is None:
            print("[BLOB] FAIL %s" % p)
            fail += 1
            continue
        with open(out, "wb") as f:
            f.write(data)
        ok += 1
        if i % 20 == 0 or i == total:
            print("[BLOB] %d/%d ok=%d fail=%d (%.0fs)" % (i, total, ok, fail, time.time() - t0))
    print("[DONE] 写入 %s：成功 %d / 失败 %d，用时 %.0fs" % (dest, ok, fail, time.time() - t0))
    return ok, fail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="hintime/cs2-dashboard")
    ap.add_argument("--ref", default="main")
    ap.add_argument("--dest", required=True)
    ap.add_argument("--token", default=None)
    ap.add_argument("--exclude", nargs="*", default=["price_history.db"])
    ap.add_argument("--max-mb", type=int, default=50)
    ap.add_argument("--only-prefix", default=None)
    a = ap.parse_args()
    token = _read_token(a.token)
    if not token:
        print("NO TOKEN（GH_TOKEN / local_keys.env 都没有）")
        sys.exit(2)
    print("[AUTH] token ok  repo=%s ref=%s dest=%s" % (a.repo, a.ref, a.dest))
    ok, fail = fetch_all(a.repo, token, a.ref, a.dest, a.exclude, a.max_mb, a.only_prefix)
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
