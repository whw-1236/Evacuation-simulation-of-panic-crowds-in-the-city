# Strict psychology semantics mechanism gate (R2)

Date: 2026-07-14

## Decision

**PASS for the formal strict-mode rerun.** This is a mechanism and output-contract audit only. It is not a manuscript effect-size dataset and must not be pooled with the formal N=800 multi-city results.

## Frozen contract

- Model contract: `ijdrr_strict_v1`
- Metric schema: `4`
- Psychology semantics used for paper evidence: `strict`
- Audit city/district: Xiamen / Siming
- Fixed seeds: 42-46
- Audit size: 24 residents, 3 enterprises, 180 steps, `dt=0.25 h`
- Outage trigger: step 2
- Graph modes: paired off/on within every seed
- Legacy outputs: separate mechanism-comparison tree only

## Verification

- Repository test suite: 107 passed.
- Static compilation: passed for `core`, `simulation`, `scripts`, `analysis`, and `tests`.
- Strict output validator: 5/5 run directories passed; 0 failed.
- Every accepted run contains paired graph-off/on manifests, strict semantics, schema 4, the same run configuration within the pair, finite bounded metrics, end-of-step metric phase, valid outage/recovery clocks, and the regional-pressure identity.
- Audit confidence intervals use two-sided Student-t intervals with `df=n-1`.

## Graph-on diagnostic results

Values below are seed means with 95% Student-t confidence intervals (`n=5`). They diagnose the semantic change and are not paper-facing performance claims.

| End-of-run metric | Strict mean [95% CI] | Strict minus legacy paired mean [95% CI] |
| --- | ---: | ---: |
| Unified stress | 0.4607 [0.4204, 0.5009] | 0.0935 [0.0119, 0.1750] |
| Derived panic | 0.5322 [0.4958, 0.5686] | 0.0910 [0.0116, 0.1704] |
| Regional psychological pressure, A_z | 0.2451 [0.2110, 0.2791] | 0.0609 [0.0171, 0.1047] |
| Expressed emotion | 0.00137 [0.00035, 0.00240] | -0.00125 [-0.00215, -0.00034] |
| Flee ratio | 0.3000 [0.2005, 0.3995] | 0.1500 [-0.0773, 0.3773] |
| Service-restoration ratio | 1.0000 [1.0000, 1.0000] | 0.0000 [0.0000, 0.0000] |

The flee-ratio paired interval includes zero, so this audit does not support a directional behavioral-effect statement. Stress, panic, and A_z differences confirm that strict and legacy paths are materially distinct; they do not establish external validity.

## Temporal plausibility checks

- The strict graph-on trace rises during the outage, peaks around partial restoration, and then recovers rather than resetting discontinuously.
- In seed 42, mean stress declines from 0.6652 at 27.5 h to 0.4388 at 44.75 h after service restoration progresses to 100%.
- The PTS share declines from 0.3333 at 27.5 h to 0.0417 at 44.75 h, consistent with hysteretic recovery.
- At the final step, mean cumulative outage exposure is 26.8646 h and mean time since service restoration is 17.1354 h; together they preserve the post-trigger exposure clock without the historical legacy reset.
- Expressed emotion approaches zero after restoration while latent stress and derived panic recover more slowly. This is consistent with the strict contract's distinction between outward emotional expression and the unified latent stress state.

## Evidence boundary and next gate

The formal matrix may now run under `psychology_strict`. Manuscript v7 can use only runs that pass the strict validator and share the frozen code fingerprint. The protected v6 manuscript remains unchanged until formal aggregation is complete.

Source artifacts:

- `trace_output/IJDRR_v7_strict_semantics_audit_20260714_r2/psychology_semantics_audit_summary.csv`
- `trace_output/IJDRR_v7_strict_semantics_audit_20260714_r2/psychology_semantics_audit_manifest.json`
- `trace_output/IJDRR_v7_strict_semantics_audit_20260714_r2/psychology_semantics_audit_curves.pdf`
- `analysis_outputs/strict_semantics/strict_semantics_audit_r2_validation.json`
