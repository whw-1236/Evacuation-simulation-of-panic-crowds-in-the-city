# -*- coding: utf-8 -*-
"""F2: 三城 × {poi, uniform} home 分布对照 (subprocess 模式)。

每个 (city, home_dist) 调用 run_ablation.py 一次 (内部跑 graph-off + graph-on),
总计 3 × 2 = 6 次 subprocess。

⚠️ 必须用 Crowds_sim conda env 启动:
    D:/EnvironmentAnaconda/envs/Crowds_sim/python.exe -u scripts/run_f2_home_dist.py

设计意图:
  - poi 模式: home 聚集在 industry/school 等 CSV 点位 0.002° 圆内 (当前默认, 与 F1 一致)
  - uniform 模式: home 在 polygon 内 rejection sampling 均匀分布 (去除 POI bias)
  - 用 seed=42 固定, 让 stochastic 差异最小化, 突出 distribution 差异

预期检验:
  L 形 BC 反相关 (T16) 在 uniform 下是否消失? 若消失 → POI bias 是 L 形主因;
  若仍存在 → 模型本质性质 (cascade 在街道窄边 + shelter 拥堵)。

输出:
  trace_output/M4_F2_home_dist/t15_<城>_<区>_{poi,uniform}/
后处理:
  analysis/f2_compare_r.py 跑 betweenness_vs_sim 对照 poi vs uniform 的 Pearson r
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
            f'    D:/EnvironmentAnaconda/envs/Crowds_sim/python.exe -u scripts/run_f2_home_dist.py'
        )


CITIES = [
    ('厦门市', '思明区'),
    ('沈阳市', '沈河区'),
    ('北京市', '东城区'),
]
HOME_DISTS = ['poi', 'uniform']
SEED = 42

USE_MML = os.environ.get('BLACKOUT_USE_MML', '1') != '0'   # MML default since 2026-06-28; set '0' for sigmoid legacy
OUTPUT_BASE = 'M4_MML_F2_home_dist' if USE_MML else 'M4_F2_home_dist'
TRACE_ROOT = os.path.join(ROOT, 'trace_output')
PYTHON_EXE = sys.executable


def main():
    total = len(CITIES) * len(HOME_DISTS)
    done = 0
    skipped = 0
    failed = 0
    t_global = time.time()

    for city, district in CITIES:
        for hd in HOME_DISTS:
            done += 1
            tag = hd  # poi / uniform
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
                '--home-distribution', hd,
                '--output-base', OUTPUT_BASE,
            ]
            if not USE_MML:
                cmd.append('--no-mml')
            print(f'\n{"#"*70}', flush=True)
            print(f'[{done}/{total}] {city}/{district} home_dist={hd}', flush=True)
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
    print(f'F2 complete: {total} runs ({skipped} skipped, {failed} failed), '
          f'total {(time.time()-t_global)/60:.1f} min', flush=True)
    print(f'output: {os.path.join(TRACE_ROOT, OUTPUT_BASE)}', flush=True)
    print(f'{"="*70}', flush=True)


if __name__ == '__main__':
    main()
