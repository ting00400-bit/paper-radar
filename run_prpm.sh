#!/bin/bash
# PRPM 是建議層：任何匯出或訓練失敗都保留 keyword 排序，不能中斷部署。
set +e

if python export_action_log.py && \
   python train_prpm.py \
     --papers site/papers.json \
     --events _prpm_cache/events.json \
     --profile site/profile.json; then
  echo "=== PRPM profile refreshed ==="
else
  rm -f site/profile.json
  echo "WARNING: PRPM refresh failed; using keyword ranking only"
fi

exit 0
