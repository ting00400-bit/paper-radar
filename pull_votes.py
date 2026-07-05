#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 D1 actions 表裡有投票的紀錄拉下來，覆寫 training_log.jsonl 供 train_interest.py 使用。

只做 SELECT（唯讀），NAS 上 .env 的唯讀 token（D1:Read）即可執行，不需要 OAuth。
train_interest.py 的 load_votes() 本身會依 ts 取每個 item_id 的最新一票，
所以這裡採「整份覆寫」而非逐行 append，簡單且不會有重複/漂移風險。

用法：python pull_votes.py
"""
import json
import os
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
LOG_PATH = SCRIPT_DIR / "training_log.jsonl"
D1_NAME = "paper-radar-db"


def query_votes():
    env = {k: v for k, v in os.environ.items()}
    r = subprocess.run(
        ["npx", "--yes", "wrangler", "d1", "execute", D1_NAME, "--remote", "--json",
         "--command", "SELECT item_id, doi, title, vote, updated FROM actions WHERE vote IS NOT NULL"],
        cwd=SCRIPT_DIR, env=env, capture_output=True, text=True, encoding="utf-8",
        shell=(os.name == "nt"),
    )
    if r.returncode != 0:
        raise RuntimeError(f"wrangler d1 query failed:\n{r.stderr}")
    out = r.stdout
    data = json.loads(out[out.index("["):])
    return data[0]["results"]


def main():
    rows = query_votes()
    lines = []
    for row in rows:
        lines.append(json.dumps({
            "item_id": row["item_id"],
            "vote": row["vote"],
            "ts": row.get("updated") or "",
            "title": row.get("title") or "",
        }, ensure_ascii=False))
    LOG_PATH.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    print(f"已寫入 {len(lines)} 筆投票到 {LOG_PATH}")


if __name__ == "__main__":
    main()
