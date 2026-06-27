# -*- coding: utf-8 -*-
"""F4: 三城 × seed 42-51 多 seed 批量 runner (subprocess 模式)。

每个 (city, seed) 调用 run_ablation.py 一次 (内部跑 graph-off + graph-on),
总计 30 次 subprocess。每次 Python 完全退出, 释放内存 (避免 in-process
模式下累积 800 居民 × 5160 nodes × 多次 sim 的 OOM/silent-crash)。

⚠️ 必须用 Crowds_sim conda env 启动:
    D:/EnvironmentAnaconda/envs/Crowds_sim/python.exe -u scripts/run_f4_multi_seed.py

设计:
  - 每个 subprocess 跑前 skip 检查 summary.json (断点续跑)
  - 实时输出 stdout (subprocess.run + sys.stdout flush)
  - 每个 (city, seed) 跑完打印进度 + ETA

后处理: analysis/f4_aggregate.py 读所有 summary.json 算 95% CI
"""
import importlib.util
import os
import sys
import subprocess
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
except Exception:
    pass

# fail-fast: 当前 python 必须装 networkx/osmnx
for _mod in ('networkx', 'osmnx'):
    if importlib.util.find_spec(_mod) is None:
        raise SystemExit(
            f'[FATAL] {_mod} 未安装。本脚本必须用 Crowds_sim env 启动:\n'
            f'    D:/EnvironmentAnaconda/envs/Crowds_sim/python.exe -u scripts/run_f4_multi_seed.py'
        )


CITIES = [
    ('厦门市', '思明区'),
    ('沈阳市', '沈河区'),
    ('北京市', '东城区'),
]
SEEDS = list(range(42, 52))  # 包含 6-22 baseline seed=42, 共 10 个

USE_MML = os.environ.get('BLACKOUT_USE_MML', '1') != '0'   # MML default since 2026-06-28; set '0' for sigmoid legacy
OUTPUT_BASE = 'M4_MML_F4_multi_seed' if USE_MML else 'M4_F4_multi_seed'
TRACE_ROOT = os.path.join(ROOT, 'trace_output')
PYTHON_EXE = sys.executable  # 用当前解释器 (已通过 fail-fast 检查)


def main():
    total = len(CITIES) * len(SEEDS)
    done = 0
    skipped = 0
    failed = 0
    t_global = time.time()

    for city, district in CITIES:
        for seed in SEEDS:
            done += 1
            tag = f'seed{seed:02d}'
            run_dir = os.path.join(TRACE_ROOT, OUTPUT_BASE,
                                   f't15_{city}_{district}_{tag}')

            summary_path = os.path.join(run_dir, 'summary.json')
            if os.path.exists(summary_path):
                skipped += 1
                print(f'[{done}/{total}] skip (已完成) {city}/{district} {tag}',
                      flush=True)
                continue

            cmd = [
                PYTHON_EXE, '-u', os.path.join(ROOT, 'scripts', 'run_ablation.py'),
                '--city', city, '--district', district,
                '--seed', str(seed), '--tag', tag,
                '--output-base', OUTPUT_BASE,
            ]
            if not USE_MML:
                cmd.append('--no-mml')
            print(f'\n{"#"*70}', flush=True)
            print(f'[{done}/{total}] {city}/{district} {tag}', flush=True)
            print(f'{"#"*70}', flush=True)

            t0 = time.time()
            try:
                subprocess.run(cmd, check=True)
            except subprocess.CalledProcessError as ex:
                failed += 1
                print(f'[ERROR] {city}/{district} {tag}: exit code {ex.returncode}',
                      flush=True)
                continue

            dt = time.time() - t0
            elapsed = time.time() - t_global
            actually_done = done - skipped - failed
            avg = elapsed / max(1, actually_done)
            remain = avg * (total - done)
            print(f'[progress] {done}/{total} ({(done/total*100):.0f}%) | '
                  f'this {dt:.0f}s | elapsed {elapsed/60:.1f}min | '
                  f'ETA {remain/60:.1f}min', flush=True)

    print(f'\n{"="*70}', flush=True)
    print(f'F4 complete: {total} runs ({skipped} skipped, {failed} failed), '
          f'total {(time.time()-t_global)/60:.1f} min', flush=True)
    print(f'output: {os.path.join(TRACE_ROOT, OUTPUT_BASE)}', flush=True)
    print(f'{"="*70}', flush=True)


if __name__ == '__main__':
    main()
