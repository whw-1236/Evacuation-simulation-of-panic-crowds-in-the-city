# -*- coding: utf-8 -*-
"""F2 后处理: 对比 home_distribution=poi vs uniform 的 Pearson r (BC vs sim load)。

步骤:
  1. 对每个 (city, district) × {poi, uniform} 跑 betweenness_vs_sim.py
     - 输入: trace_output/M4_F2_home_dist/t15_<城>_<区>_<hd>/graph_on/edge_observations.csv
     - 输出: trace_output/M4_F2_home_dist/_corr/<城>_<区>_<hd>/correlation.json
  2. 读 6 个 correlation.json, 汇总成对照表
  3. 关键检验: uniform 下 r 是否显著大于 poi (跃升 → POI bias 主导 L 形反相关)

输出:
  - trace_output/M4_F2_home_dist/r_compare.csv
  - trace_output/M4_F2_home_dist/r_compare.json
  - terminal print 对照表

调用:
    python analysis/f2_compare_r.py
"""
import os
import sys
import json
import csv
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


_USE_MML = os.environ.get('BLACKOUT_USE_MML', '0') == '1'
F2_DIR = os.path.join(ROOT, 'trace_output',
                      'M4_MML_F2_home_dist' if _USE_MML else 'M4_F2_home_dist')
CORR_BASE = os.path.join(F2_DIR, '_corr')

CITIES = [
    ('厦门市', '思明区'),
    ('沈阳市', '沈河区'),
    ('北京市', '东城区'),
]
HOME_DISTS = ['poi', 'uniform']


def run_betweenness_for(city, district, hd):
    """跑 betweenness_vs_sim 一次, 输出到 F2 子目录。"""
    edge_csv = os.path.join(F2_DIR, f't15_{city}_{district}_{hd}',
                            'graph_on', 'edge_observations.csv')
    out_dir = os.path.join(CORR_BASE, f'{city}_{district}_{hd}')
    if not os.path.exists(edge_csv):
        print(f'  [skip] {city}/{district}/{hd}: edge_csv 不存在 ({edge_csv})')
        return None

    cmd = [
        sys.executable, '-u', os.path.join(ROOT, 'analysis', 'betweenness_vs_sim.py'),
        '--city', city, '--district', district,
        '--edge-csv', edge_csv,
        '--out-dir', out_dir,
    ]
    print(f'  [run] {city}/{district}/{hd} → {out_dir}')
    # check=False: 即使 plot 阶段 crash (Crowds_sim matplotlib 已知问题),
    # summary-first 的 correlation.json 已落盘, 数据完整。
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True, encoding='utf-8')
    if proc.returncode != 0:
        print(f'  [WARN] {city}/{district}/{hd}: exit code {proc.returncode} '
              f'(很可能是 matplotlib plot crash, json 应该已落盘)')

    corr_json = os.path.join(out_dir, 'correlation.json')
    if not os.path.exists(corr_json):
        print(f'  [ERROR] {city}/{district}/{hd}: correlation.json 未生成, '
              f'真的失败了。stderr: {proc.stderr[-300:] if proc.stderr else "(empty)"}')
        return None
    with open(corr_json, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    if not os.path.exists(F2_DIR):
        raise SystemExit(f'F2 目录不存在: {F2_DIR}, 是否 F2 还没跑?')

    rows = []
    print('\n[1/2] 跑 betweenness_vs_sim 6 次 (三城 × {poi, uniform})')
    for city, district in CITIES:
        for hd in HOME_DISTS:
            corr = run_betweenness_for(city, district, hd)
            if corr is None:
                continue
            row = {
                'city': city, 'district': district,
                'home_distribution': hd,
                'n_nodes_loaded':    corr.get('n_nodes_with_observed_load', 0),
                'pearson_r_all':     corr.get('pearson_r_all'),
                'pearson_r_loaded':  corr.get('pearson_r_nonzero'),
                'spearman_rho':      corr.get('spearman_rho_all'),
            }
            rows.append(row)

    if not rows:
        raise SystemExit('未生成任何 correlation.json, 检查上面的 ERROR')

    # 落盘
    csv_path = os.path.join(F2_DIR, 'r_compare.csv')
    json_path = os.path.join(F2_DIR, 'r_compare.json')
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print(f'\n[csv] saved {csv_path}')
    print(f'[json] saved {json_path}')

    # 对照表
    print('\n' + '=' * 90)
    print('[2/2] F2 对照表: poi vs uniform 的 Pearson r')
    print('=' * 90)
    print(f'  {"城市":<14} {"hd":<8} {"n_nodes>0":>10} {"r(all)":>10} {"r(loaded)":>12} {"ρ(Spearman)":>14}')
    for r in rows:
        ra = r['pearson_r_all']
        rl = r['pearson_r_loaded']
        sp = r['spearman_rho']
        print(f"  {r['city'] + '/' + r['district']:<14} {r['home_distribution']:<8} "
              f"{r['n_nodes_loaded']:>10} "
              f"{(ra if ra is not None else 0):>+10.4f} "
              f"{(rl if rl is not None else 0):>+12.4f} "
              f"{(sp if sp is not None else 0):>+14.4f}")

    # 关键判断: uniform r 是否显著大于 poi → POI bias 主导 L 形反相关
    print('\n[关键判断 — poi vs uniform 的 r 差]')
    by_city = {}
    for r in rows:
        by_city.setdefault((r['city'], r['district']), {})[r['home_distribution']] = r
    for (c, d), grp in by_city.items():
        if 'poi' in grp and 'uniform' in grp:
            r_poi = grp['poi'].get('pearson_r_loaded') or 0
            r_uni = grp['uniform'].get('pearson_r_loaded') or 0
            delta = r_uni - r_poi
            verdict = '→ uniform 显著高' if delta > 0.1 else ('→ uniform 略高' if delta > 0.03 else ('→ 几乎一致' if abs(delta) <= 0.03 else '→ uniform 反而低'))
            print(f'  {c}/{d}: r(uniform) - r(poi) = {delta:+.4f}  {verdict}')


if __name__ == '__main__':
    main()
