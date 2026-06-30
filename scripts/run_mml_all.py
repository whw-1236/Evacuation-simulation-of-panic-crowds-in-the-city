# -*- coding: utf-8 -*-
"""F13 MML re-run master launcher: F1 + F4 + F7 + F2 全跑一遍 under --use-mml。

输出到 trace_output/M4_MML_*/ (跟 sigmoid baseline 平行存放, 不覆盖)。
F5 (θ_flee 扫描) 跳过 — MML 下没有 flee_threshold 概念, phase transition 是
softmax 温度的连续性质, 用 F7 的 N-invariance + smoke probe 即可论证 §5.2。

⚠️ 必须用 Crowds_sim conda env 启动 (DLL PATH 详见 §14 README):
    .\\tools\\run_in_crowds_env.ps1 scripts\\run_mml_all.py

预估总时间: F1(3) + F4(30) + F7(15) + F2(6) = 54 sub-run ≈ 55-65 min
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
        raise SystemExit(f'[FATAL] {_mod} 未安装, 必须用 Crowds_sim env')


CITIES = [
    ('厦门市', '思明区'),
    ('沈阳市', '沈河区'),
    ('北京市', '东城区'),
]
PYTHON_EXE = sys.executable
TRACE_ROOT = os.path.join(ROOT, 'trace_output')

# 注: 2026-06-28 起 batch runner 默认就是 MML 模式 (env var 默认 != '0'), 此处显式 = '1' 仅为前向兼容
env_mml = os.environ.copy()
env_mml['BLACKOUT_USE_MML'] = '1'


def _run_subprocess(args, **kwargs):
    print(f'\n>>> {" ".join(args[:8])}{" ..." if len(args) > 8 else ""}', flush=True)
    return subprocess.run(args, check=True, **kwargs)


def run_f1_cross_city():
    """F1: 三城 baseline (3 sub-run)"""
    out_base = 'M4_MML_F1_cross_city'
    print(f'\n{"="*70}\n  F1 (MML) — three cities baseline\n{"="*70}', flush=True)
    for city, district in CITIES:
        run_dir = os.path.join(TRACE_ROOT, out_base,
                               f't15_{city}_{district}')
        if os.path.exists(os.path.join(run_dir, 'summary.json')):
            print(f'[skip] {city}/{district}', flush=True)
            continue
        # F1 命名跟 sigmoid 的 M4_F1 一致 (区县名不带 tag), tag 设空字串让 run_ablation 命名一致
        cmd = [
            PYTHON_EXE, '-u', os.path.join(ROOT, 'scripts', 'run_ablation.py'),
            '--city', city, '--district', district,
            '--output-base', out_base,
            '--use-mml',
        ]
        t0 = time.time()
        _run_subprocess(cmd)
        print(f'   done in {time.time()-t0:.0f}s', flush=True)


def run_subscript(name, est_min):
    """Run an existing batch runner (e.g. run_f4_multi_seed.py) under MML env."""
    print(f'\n{"="*70}\n  {name} (MML) — est ~{est_min} min\n{"="*70}', flush=True)
    cmd = [PYTHON_EXE, '-u', os.path.join(ROOT, 'scripts', name)]
    t0 = time.time()
    subprocess.run(cmd, env=env_mml, check=True)
    print(f'\n  {name} done in {(time.time()-t0)/60:.1f} min', flush=True)


def main():
    t_global = time.time()
    run_f1_cross_city()
    run_subscript('run_f4_multi_seed.py', est_min=30)
    run_subscript('run_f7_n_scan.py',     est_min=22)
    run_subscript('run_f2_home_dist.py',  est_min=6)
    total_min = (time.time() - t_global) / 60
    print(f'\n{"="*70}\n  MML re-run all done in {total_min:.1f} min\n{"="*70}', flush=True)


if __name__ == '__main__':
    main()
