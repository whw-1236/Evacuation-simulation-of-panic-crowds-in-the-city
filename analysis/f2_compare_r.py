# -*- coding: utf-8 -*-
"""F2 后处理: 对比 home_distribution=poi vs uniform 的 Pearson r (BC vs sim load)。

步骤:
  1. 对每个 (city, district) × {poi, uniform} 跑 betweenness_vs_sim.py
     - 输入: <formal-root>/psychology_<semantics>/t15_<城>_<区>_<hd>_seed<seed>/graph_on/edge_observations.csv
     - 输出: <formal-root>/psychology_<semantics>/_corr/<城>_<区>_<hd>_seed<seed>/correlation.json
  2. 读 6 个 correlation.json, 汇总成对照表
  3. 关键检验: uniform 下 r 是否显著大于 poi (跃升 → POI bias 主导 L 形反相关)

输出:
  - <formal-root>/psychology_<semantics>/r_compare.csv
  - <formal-root>/psychology_<semantics>/r_compare.json
  - terminal print 对照表

调用:
    python analysis/f2_compare_r.py
"""
import argparse
import os
import sys
import json
import csv
import math
import subprocess
from itertools import product

from scipy.stats import t as student_t

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


_USE_MML = os.environ.get('BLACKOUT_USE_MML', '1') != '0'   # MML default since 2026-06-28; set '0' for sigmoid legacy supplementary
F2_BASE = os.path.join(
    ROOT,
    'trace_output',
    'IJDRR_v7_strict_formal',
    'F2_home_dist_n5' if _USE_MML else 'F2_home_dist_n5_sigmoid',
)
EXPECTED_MODEL_CONTRACT_VERSION = 'ijdrr_strict_v1'
MIN_METRIC_SCHEMA_VERSION = 4

CITIES = [
    ('厦门市', '思明区'),
    ('沈阳市', '沈河区'),
    ('北京市', '东城区'),
]
HOME_DISTS = ['poi', 'uniform']
DEFAULT_SEEDS = [42, 43, 44, 45, 46]


def semantics_dir(base, semantics):
    leaf = f'psychology_{semantics}'
    return base if os.path.basename(os.path.normpath(base)) == leaf else os.path.join(base, leaf)


def validate_summary_semantics(summary, expected, path):
    if summary.get('model_contract_version') != EXPECTED_MODEL_CONTRACT_VERSION:
        raise ValueError(f'summary model_contract_version mismatch: {path}')
    try:
        schema_version = int(summary.get('metric_schema_version'))
    except (TypeError, ValueError):
        schema_version = -1
    if schema_version < MIN_METRIC_SCHEMA_VERSION:
        raise ValueError(f'summary metric_schema_version is too old: {path}')
    actual = summary.get('config', {}).get('psychology_semantics')
    if actual != expected:
        raise ValueError(
            f'summary psychology_semantics mismatch: expected={expected!r}, '
            f'actual={actual!r}, path={path}'
        )
    manifests = summary.get('manifest')
    if not isinstance(manifests, dict):
        raise ValueError(f'summary manifest missing: {path}')
    for graph_mode in ('off', 'on'):
        manifest = manifests.get(graph_mode)
        actual = manifest.get('psychology_semantics') if isinstance(manifest, dict) else None
        if actual != expected:
            raise ValueError(
                f'{graph_mode} manifest psychology_semantics mismatch: '
                f'expected={expected!r}, actual={actual!r}, path={path}'
            )
        if manifest.get('model_contract_version') != EXPECTED_MODEL_CONTRACT_VERSION:
            raise ValueError(
                f'{graph_mode} manifest model_contract_version mismatch: {path}'
            )
        try:
            manifest_schema = int(manifest.get('metric_schema_version'))
        except (TypeError, ValueError):
            manifest_schema = -1
        if manifest_schema < MIN_METRIC_SCHEMA_VERSION:
            raise ValueError(
                f'{graph_mode} manifest metric_schema_version is too old: {path}'
            )


def run_betweenness_for(
    city, district, hd, seed, f2_dir, corr_base, psychology_semantics
):
    """跑 betweenness_vs_sim 一次, 输出到 F2 子目录。"""
    tag = f'{hd}_seed{seed}'
    run_dir = os.path.join(f2_dir, f't15_{city}_{district}_{tag}')
    summary_path = os.path.join(run_dir, 'summary.json')
    if not os.path.exists(summary_path):
        raise FileNotFoundError(f'Missing summary: {summary_path}')
    with open(summary_path, 'r', encoding='utf-8') as handle:
        summary = json.load(handle)
    validate_summary_semantics(summary, psychology_semantics, summary_path)
    config = summary.get('config', {})
    expected_config = {
        'city': city,
        'district': district,
        'home_distribution': hd,
        'seed': seed,
        'tag': tag,
    }
    mismatches = {
        key: (expected, config.get(key))
        for key, expected in expected_config.items()
        if config.get(key) != expected
    }
    if mismatches:
        raise ValueError(f'summary config mismatch: {mismatches}, path={summary_path}')
    edge_csv = os.path.join(run_dir, 'graph_on', 'edge_observations.csv')
    out_dir = os.path.join(corr_base, f'{city}_{district}_{tag}')
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


def parse_seed_list(value):
    values = []
    for part in value.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            lo_text, hi_text = part.split('-', 1)
            lo, hi = int(lo_text), int(hi_text)
            step = 1 if hi >= lo else -1
            values.extend(range(lo, hi + step, step))
        else:
            values.append(int(part))
    if not values:
        raise argparse.ArgumentTypeError('expected at least one seed')
    return values


def mean_ci(values):
    clean = [float(value) for value in values if value is not None and math.isfinite(value)]
    n = len(clean)
    if n == 0:
        return None, None, None, 0
    mean = sum(clean) / n
    if n == 1:
        return mean, None, None, 1
    variance = sum((value - mean) ** 2 for value in clean) / (n - 1)
    half = float(student_t.ppf(0.975, n - 1)) * math.sqrt(variance) / math.sqrt(n)
    return mean, mean - half, mean + half, n


def aggregate_rows(rows):
    grouped = {}
    for row in rows:
        key = (row['city'], row['district'], row['home_distribution'])
        grouped.setdefault(key, []).append(row)
    metrics = ('n_nodes_loaded', 'pearson_r_all', 'pearson_r_loaded', 'spearman_rho')
    out = []
    for (city, district, home_distribution), group in sorted(grouped.items()):
        aggregate = {
            'city': city,
            'district': district,
            'home_distribution': home_distribution,
            'psychology_semantics': group[0]['psychology_semantics'],
            'n_runs': len(group),
            'seeds': ','.join(str(row['seed']) for row in sorted(group, key=lambda row: row['seed'])),
        }
        for metric_name in metrics:
            mean, lo, hi, n = mean_ci([row.get(metric_name) for row in group])
            aggregate[f'{metric_name}_mean'] = mean
            aggregate[f'{metric_name}_ci95_lo'] = lo
            aggregate[f'{metric_name}_ci95_hi'] = hi
            aggregate[f'{metric_name}_n'] = n
        out.append(aggregate)
    return out


def parse_args():
    parser = argparse.ArgumentParser(description='Compare F2 centrality correlations.')
    parser.add_argument('--input-base', default=F2_BASE)
    parser.add_argument(
        '--seeds',
        type=parse_seed_list,
        default=list(DEFAULT_SEEDS),
        help='Comma/range seed list; defaults to 42-46.',
    )
    parser.add_argument(
        '--psychology-semantics',
        choices=('strict', 'legacy'),
        default='strict',
        help='Only read runs produced under this psychology contract.',
    )
    return parser.parse_args()


def main():
    args = parse_args()
    input_base = (
        args.input_base if os.path.isabs(args.input_base)
        else os.path.join(ROOT, 'trace_output', args.input_base)
    )
    f2_dir = semantics_dir(input_base, args.psychology_semantics)
    corr_base = os.path.join(f2_dir, '_corr')
    if not os.path.exists(f2_dir):
        raise SystemExit(f'F2 input directory does not exist: {f2_dir}')

    rows = []
    print(
        f'\n[1/2] 跑 betweenness_vs_sim '
        f'{len(CITIES) * len(args.seeds) * len(HOME_DISTS)} 次'
    )
    for city, district in CITIES:
        for seed, hd in product(args.seeds, HOME_DISTS):
            corr = run_betweenness_for(
                city,
                district,
                hd,
                seed,
                f2_dir,
                corr_base,
                args.psychology_semantics,
            )
            if corr is None:
                continue
            row = {
                'city': city, 'district': district,
                'home_distribution': hd,
                'seed': seed,
                'psychology_semantics': args.psychology_semantics,
                'n_nodes_loaded':    corr.get('n_nodes_with_observed_load', 0),
                'pearson_r_all':     corr.get('pearson_r_all'),
                'pearson_r_loaded':  corr.get('pearson_r_nonzero'),
                'spearman_rho':      corr.get('spearman_rho_all'),
            }
            rows.append(row)

    if not rows:
        raise SystemExit('未生成任何 correlation.json, 检查上面的 ERROR')

    aggregate = aggregate_rows(rows)
    # 落盘: raw per-seed rows plus manuscript-facing Student-t CI table.
    raw_csv_path = os.path.join(f2_dir, 'r_compare_raw.csv')
    csv_path = os.path.join(f2_dir, 'r_compare.csv')
    json_path = os.path.join(f2_dir, 'r_compare.json')
    with open(raw_csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(aggregate[0].keys()))
        w.writeheader()
        w.writerows(aggregate)
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(aggregate, f, ensure_ascii=False, indent=2)
    print(f'\n[csv] saved {raw_csv_path}')
    print(f'\n[csv] saved {csv_path}')
    print(f'[json] saved {json_path}')

    # 对照表
    print('\n' + '=' * 90)
    print('[2/2] F2 对照表: poi vs uniform 的 Pearson r')
    print('=' * 90)
    print(f'  {"城市":<14} {"hd":<8} {"n_nodes>0":>10} {"r(all)":>10} {"r(loaded)":>12} {"ρ(Spearman)":>14}')
    for r in aggregate:
        ra = r['pearson_r_all_mean']
        rl = r['pearson_r_loaded_mean']
        sp = r['spearman_rho_mean']
        print(f"  {r['city'] + '/' + r['district']:<14} {r['home_distribution']:<8} "
              f"{r['n_nodes_loaded_mean']:>10.1f} "
              f"{(ra if ra is not None else 0):>+10.4f} "
              f"{(rl if rl is not None else 0):>+12.4f} "
              f"{(sp if sp is not None else 0):>+14.4f}")

    # 关键判断: uniform r 是否显著大于 poi → POI bias 主导 L 形反相关
    print('\n[关键判断 — poi vs uniform 的 r 差]')
    by_city = {}
    for r in aggregate:
        by_city.setdefault((r['city'], r['district']), {})[r['home_distribution']] = r
    for (c, d), grp in by_city.items():
        if 'poi' in grp and 'uniform' in grp:
            r_poi = grp['poi'].get('pearson_r_loaded_mean') or 0
            r_uni = grp['uniform'].get('pearson_r_loaded_mean') or 0
            delta = r_uni - r_poi
            verdict = '→ uniform 显著高' if delta > 0.1 else ('→ uniform 略高' if delta > 0.03 else ('→ 几乎一致' if abs(delta) <= 0.03 else '→ uniform 反而低'))
            print(f'  {c}/{d}: r(uniform) - r(poi) = {delta:+.4f}  {verdict}')


if __name__ == '__main__':
    main()
