import csv, math, os

results_dir = r'E:\Documents\Bahan Skripsi\Program EEWS\MDLBEEWS\tests\results'

def read_col(path, col):
    with open(path) as f:
        return [float(r[col]) for r in csv.DictReader(f)]

def stats(vals):
    n = len(vals)
    mean = sum(vals)/n
    std = math.sqrt(sum((v-mean)**2 for v in vals)/n)
    sorted_v = sorted(vals)
    p95 = sorted_v[int(0.95*n)-1]
    return mean, std, p95, min(vals), max(vals), n

print('=== REKAP PER RUN (NoMetrics API vs WithMetrics Docker_API) ===\n')
no_means, wi_means = [], []
no_stds, wi_stds = [], []

for r in [1,2,3]:
    no_cpu = read_col(f'{results_dir}/s2_overhead_no_metrics_api_metrics_run{r}.csv', 'pwave_aggregate_cpu_percent')
    wi_cpu = read_col(f'{results_dir}/s2_overhead_with_metrics_metrics_run{r}_docker_api.csv', 'pwave_aggregate_cpu_percent')
    no_ram = read_col(f'{results_dir}/s2_overhead_no_metrics_api_metrics_run{r}.csv', 'pwave_aggregate_mem_mb')
    wi_ram = read_col(f'{results_dir}/s2_overhead_with_metrics_metrics_run{r}_docker_api.csv', 'pwave_aggregate_mem_mb')

    nm, ns, np95, nmin, nmax, nn = stats(no_cpu)
    wm, ws, wp95, wmin, wmax, wn = stats(wi_cpu)
    nrm = sum(no_ram)/len(no_ram)
    wrm = sum(wi_ram)/len(wi_ram)

    diff = wm - nm
    pct = diff/nm*100
    pooled_std = (ns + ws) / 2
    significant = abs(diff) >= pooled_std

    no_means.append(nm)
    wi_means.append(wm)
    no_stds.append(ns)
    wi_stds.append(ws)

    sig_label = "YA -- mencurigakan" if significant else "TIDAK (dalam noise normal)"
    print(f'Run {r} (N={nn}/{wn}):')
    print(f'  NoMetrics  CPU: mean={nm:.1f}% +/-{ns:.1f}%  P95={np95:.1f}%  min={nmin:.1f}  max={nmax:.1f}  RAM={nrm:.0f} MB')
    print(f'  WithMetric CPU: mean={wm:.1f}% +/-{ws:.1f}%  P95={wp95:.1f}%  min={wmin:.1f}  max={wmax:.1f}  RAM={wrm:.0f} MB')
    print(f'  Selisih CPU mean: {diff:+.1f}% ({pct:+.1f}%) | Pooled Std: {pooled_std:.1f}%')
    print(f'  Signifikan secara statistik? {sig_label}')
    print()

grand_no = sum(no_means)/3
grand_wi = sum(wi_means)/3
grand_ns = sum(no_stds)/3
grand_ws = sum(wi_stds)/3

print('=== GRAND AVERAGE (3 run) ===')
print(f'  NoMetrics  mean CPU: {grand_no:.1f}% +/- {grand_ns:.1f}%')
print(f'  WithMetrics mean CPU: {grand_wi:.1f}% +/- {grand_ws:.1f}%')
selisih = grand_wi - grand_no
print(f'  Selisih grand mean: {selisih:+.1f}% ({selisih/grand_no*100:+.1f}%)')
print(f'  Pooled grand std: {(grand_ns+grand_ws)/2:.1f}%')
print(f'  Selisih vs std: {abs(selisih)/(grand_ns+grand_ws)*2:.2f}x std')
print()
print('=== KESIMPULAN VALIDITAS ===')
ratio = abs(selisih) / ((grand_ns + grand_ws) / 2)
if ratio < 0.5:
    print(f'  Selisih hanya {ratio:.2f}x pooled-std --> NOISE, bukan overhead nyata')
    print('  DATA VALID: CPU "lebih baik" adalah artefak variasi, bukan efek kausal Prometheus')
else:
    print(f'  Selisih {ratio:.2f}x pooled-std --> perlu investigasi lebih lanjut')

