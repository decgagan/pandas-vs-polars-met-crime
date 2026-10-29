import glob, statistics, time, gc
from pathlib import Path
import pandas as pd, polars as pl
PROC = Path('data/processed')
files = sorted(glob.glob('data/raw_all/*-street.csv'))
schema = {c: pl.Utf8 for c in ['Crime ID','Month','Reported by','Falls within','Location','LSOA code','LSOA name','Crime type','Last outcome category','Context']}
all_ = pl.concat([pl.read_csv(f, schema_overrides=schema, infer_schema_length=0).with_columns(pl.col('Longitude','Latitude').cast(pl.Float64, strict=False)) for f in files], how='diagonal_relaxed')
CSV, PQ = PROC/'all_street.csv', PROC/'all_street.parquet'
all_.write_csv(CSV); all_.write_parquet(PQ)
print('rows', all_.height, 'forces', all_['Falls within'].n_unique(), 'months', all_['Month'].min(), all_['Month'].max(), flush=True)
monthly = all_.group_by('Month').len('n').sort('Month'); del all_; gc.collect()
CATEGORY = {'Violence and sexual offences':'Violent','Robbery':'Violent','Possession of weapons':'Violent','Burglary':'Property','Vehicle crime':'Property','Theft from the person':'Property','Bicycle theft':'Property','Shoplifting':'Property','Other theft':'Property','Criminal damage and arson':'Property','Anti-social behaviour':'Public order','Public order':'Public order','Drugs':'Other','Other crime':'Other'}
lookup_pd = pd.DataFrame({'Crime type': list(CATEGORY), 'Category': list(CATEGORY.values())}); lookup_pl = pl.from_pandas(lookup_pd)
def pd_load_csv(): return pd.read_csv(CSV, low_memory=False)
def pd_load_parquet(): return pd.read_parquet(PQ)
def pd_clean(df):
    df = df.drop(columns=['Context'], errors='ignore').dropna(subset=['Crime type'])
    df['Month'] = pd.to_datetime(df['Month'], format='%Y-%m')
    df['Borough'] = df['LSOA name'].str.rsplit(' ', n=1).str[0]
    return df
def pd_group(df): return df.groupby(['Borough','Crime type']).size().reset_index(name='n')
def pd_join(df): return df.merge(lookup_pd, on='Crime type', how='left')
def pd_full(): return pd_group(pd_join(pd_clean(pd_load_parquet())))
def pl_load_csv(): return pl.read_csv(CSV, infer_schema_length=10000)
def pl_load_parquet(): return pl.read_parquet(PQ)
def pl_clean_expr(lf):
    return (lf.drop('Context', strict=False).drop_nulls('Crime type')
              .with_columns(pl.col('Month').str.strptime(pl.Date, '%Y-%m'), pl.col('LSOA name').str.replace(r' \S+$', '').alias('Borough')))
def pl_clean(df): return pl_clean_expr(df.lazy()).collect()
def pl_group(df): return df.group_by(['Borough','Crime type']).len('n')
def pl_join(df): return df.join(lookup_pl, on='Crime type', how='left')
def pl_full(): return pl_group(pl_join(pl_clean(pl_load_parquet())))
def pl_full_lazy():
    return pl_clean_expr(pl.scan_parquet(PQ)).join(lookup_pl.lazy(), on='Crime type', how='left').group_by(['Borough','Crime type']).len('n').collect()
def timeit(fn, r=3):
    ts=[]
    for _ in range(r):
        gc.collect(); t=time.perf_counter(); fn(); ts.append(time.perf_counter()-t)
    return statistics.median(ts)
rows=[]
def run(name, fpd, fpl):
    rows.append({'task':name,'pandas_s':timeit(fpd),'polars_s':timeit(fpl)}); print(rows[-1], flush=True)
run('Load CSV', pd_load_csv, pl_load_csv)
run('Load Parquet', pd_load_parquet, pl_load_parquet)
run('Clean', lambda: pd_clean(pd_load_parquet()), lambda: pl_clean(pl_load_parquet()))
pdf = pd_clean(pd_load_parquet()); pldf = pl_clean(pl_load_parquet())
run('Group', lambda: pd_group(pdf), lambda: pl_group(pldf))
run('Join', lambda: pd_join(pdf), lambda: pl_join(pldf))
del pdf, pldf; gc.collect()
run('Full pipeline', pd_full, pl_full)
rows.append({'task':'Full pipeline (Polars lazy)','pandas_s':None,'polars_s':timeit(pl_full_lazy)}); print(rows[-1], flush=True)
res = pd.DataFrame(rows); res['speedup'] = res['pandas_s']/res['polars_s']
res.to_csv('results/timings_all_forces.csv', index=False); print(res.to_string())
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
res.dropna(subset=['pandas_s']).set_index('task')[['pandas_s','polars_s']].plot.bar(figsize=(9,4.5), rot=20, title='All forces: median time per task (seconds, lower is better)')
plt.tight_layout(); plt.savefig('charts/timings_all_forces.png', dpi=150)
