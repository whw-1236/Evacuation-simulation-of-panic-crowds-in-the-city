# -*- coding: utf-8 -*-
"""F5: 三城 × θ_flee ∈ {0.4, 0.5, 0.6, 0.7, 0.8} 扫描 batch runner (subprocess 模式)。

每个 (city, θ) 调用 run_ablation.py 一次 (内部跑 graph-off + graph-on),
总计 15 次 subprocess (3 城 × 5 θ)。固定 seed=42, N=800 (与 F4 baseline 一致),
只让 flee_threshold 变化, 用于绘制 §5.2 phase transition 图。

⚠️ 必须用 Crowds_sim conda env 启动 (通过 activate.bat, 否则 DLL 加载会爆):
    cmd /c "call D:/EnvironmentAnaconda/Scripts/activate.bat Crowds_sim ^
        && python -u scripts/run_f5_theta_flee.py"

设计:
  - 每个 subprocess 跑前 skip 检查 summary.json (断点续跑)
  - 实时输出 stdout
  - 每个 (city, θ) 跑完打印进度 + ETA

后处理: analysis/f5_phase_transition.py 读 15 个 summary.json 出 theta vs metric 曲线
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

# fail-fast: 当前 python 必须装 networkx/osmnx (否则 graph-on silent fallback)
for _mod in ('networkx', 'osmnx'):
    if importlib.util.find_spec(_mod) is None:
        raise SystemExit(
            f'[FATAL] {_mod} 未安装。本脚本必须用 Crowds_sim env 启动:\n'
            f'    cmd /c "call D:/EnvironmentAnaconda/Scripts/activate.bat Crowds_sim '
            f'&& python -u scripts/run_f5_theta_flee.py"'
        )


CITIES = [
    ('厦门市', '思明区'),
    ('沈阳市', '沈河区'),
    ('北京市', '东城区'),
]
THETAS = [0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7, 0.8]
SEED = 42  # 固定 seed, 跟 F7 baseline 一致

OUTPUT_BASE = 'M4_F5_theta_flee'
TRACE_ROOT = os.path.join(ROOT, 'trace_output')
PYTHON_EXE = sys.executable


def _theta_tag(th: float) -> str:
    # 0.4 → "theta0.4", 0.45 → "theta0.45"
    return f'theta{th:g}'


def main():
    total = len(CITIES) * len(THETAS)
    done = 0
    skipped = 0
    failed = 0
    t_global = time.time()

    for city, district in CITIES:
        for th in THETAS:
            done += 1
            tag = _theta_tag(th)
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
                '--flee-threshold', str(th),
                '--output-base', OUTPUT_BASE,
            ]
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
    print(f'F5 complete: {total} runs ({skipped} skipped, {failed} failed), '
          f'total {(time.time()-t_global)/60:.1f} min', flush=True)
    print(f'output: {os.path.join(TRACE_ROOT, OUTPUT_BASE)}', flush=True)
    print(f'{"="*70}', flush=True)


if __name__ == '__main__':
    main()
