#!/bin/bash
cd /workspace/solana-10x
set -a; source .env; set +a
export PYTHONPATH=src
exec .venv/bin/python -m paper_live --live --cycles 0 --feed pump --enrich-via pump --score-mode histgb_q5b --entry-rule train_quantile --score-threshold 0.9 --max-calls 100000
