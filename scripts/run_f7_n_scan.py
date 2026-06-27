# -*- coding: utf-8 -*-
"""F7: 三城 × N ∈ {200, 500, 800, 1500, 3000} 居民数扫描 (subprocess 模式)。

每个 (city, N) 调用 run_ablation.py 一次 (内部跑 graph-off + graph-on),
总计 3 × 5 = 15 次 subprocess。

⚠️ 必须用 Crowds_sim conda env 启动:
    D:/EnvironmentAnaconda/envs/Crowds_sim/python.exe -u scripts/run_f7_n_scan.py

设计:
  - 用 seed=42 固定 (与 F1 baseline 一致)
  - 输出 trace_output/M4_F7_N_scan/t15_<城>_<区>_N{200,500,800,1500,3000}/
  - 后处理: analysis/f7_n_curve.py 出 cascade 强度 vs N 的 log-log 曲线

预估时长: N=3000 单次 ~60-120s, 总计 ~30 min
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

for _mod in ('networkx', 'osmnx'):
    if importlib.util.find_spec(_mod) is None:
        raise SystemExit(
            f'[FATAL] {_mod} 未安装。本脚本必须用 Crowds_sim env 启动:\n'
            f'    D:/EnvironmentAnaconda/envs/Crowds_sim/python.exe -u scripts/run_f7_n_scan.py'
        )


CITIES = [
    ('厦门市', '思明区'),
    ('沈阳市', '沈河区'),
    ('北京市', '东城区'),
]
N_VALUES = [200, 500, 800, 1500, 3000]
SEED = 42  # 固定 seed, 与 F1 baseline 一致

USE_MML = os.environ.get('BLACKOUT_USE_MML', '1') != '0'   # MML default since 2026-06-28; set '0' for sigmoid legacy
OUTPUT_BASE = 'M4_MML_F7_N_scan' if USE_MML else 'M4_F7_N_scan'
TRACE_ROOT = os.path.join(ROOT, 'trace_output')
PYTHON_EXE = sys.executable


def main():
    total = len(CITIES) * len(N_VALUES)
    done = 0
    skipped = 0
    failed = 0
    t_global = time.time()

    for city, district in CITIES:
        for N in N_VALUES:
            done += 1
            tag = f'N{N:04d}'
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
                '--seed', str(SEED), '--tag', tag,
                '--n-residents', str(N),
                '--output-base', OUTPUT_BASE,
            ]
            if not USE_MML:
                cmd.append('--no-mml')
            print(f'\n{"#"*70}', flush=True)
            print(f'[{done}/{total}] {city}/{district} {tag} (N={N})', flush=True)
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
    print(f'F7 complete: {total} runs ({skipped} skipped, {failed} failed), '
          f'total {(time.time()-t_global)/60:.1f} min', flush=True)
    print(f'output: {os.path.join(TRACE_ROOT, OUTPUT_BASE)}', flush=True)
    print(f'{"="*70}', flush=True)


if __name__ == '__main__':
    main()
