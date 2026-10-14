"""Fixed ridge predictors: load/PMR vs load/PMR plus burst/service timescales.

Fit on completed v2 FIFO cell medians; evaluate new v3 FIFO cells only after
raw audit. No hyperparameter search or refitting on v3 outcomes.
"""
import argparse
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path


def features(row,extended):
    rho,pmr,tau_b,tau_s = (float(row[k]) for k in ("rho","pmr","tau_b","tau_s"))
    values=[rho,pmr-1]
    if extended:
        burst_work=(rho-.03)*(1-1/pmr)*tau_b
        values.extend((math.log1p(burst_work),math.log1p(.3*tau_s)))
    return values


def solve(matrix,vector):
    rows=[list(a)+[b] for a,b in zip(matrix,vector)]
    n=len(rows)
    for i in range(n):
        pivot=max(range(i,n),key=lambda k:abs(rows[k][i]))
        rows[i],rows[pivot]=rows[pivot],rows[i]
        if abs(rows[i][i])<1e-12: raise ValueError("singular regression")
        scale=rows[i][i]; rows[i]=[v/scale for v in rows[i]]
        for j in range(n):
            if j!=i:
                factor=rows[j][i]
                rows[j]=[a-factor*b for a,b in zip(rows[j],rows[i])]
    return [row[-1] for row in rows]


def fit_model(cells,extended):
    x=[features(row,extended) for row in cells]
    y=[math.log(float(row["p99"])) for row in cells]
    means=[statistics.mean(col) for col in zip(*x)]
    scales=[statistics.pstdev(col) or 1. for col in zip(*x)]
    design=[[1.]+[(v-m)/s for v,m,s in zip(row,means,scales)] for row in x]
    n=len(design[0]); ridge=.1
    matrix=[[sum(row[i]*row[j] for row in design)+(ridge if i==j and i else 0.) for j in range(n)] for i in range(n)]
    vector=[sum(row[i]*target for row,target in zip(design,y)) for i in range(n)]
    return dict(extended=extended,means=means,scales=scales,coefficients=solve(matrix,vector),ridge=ridge,training_cells=len(cells))


def predict(model,row):
    design=[1.]+[(v-m)/s for v,m,s in zip(features(row,model["extended"]),model["means"],model["scales"])]
    return math.exp(sum(a*b for a,b in zip(design,model["coefficients"])))


def fit(source,output):
    source,output=Path(source),Path(output)
    if output.exists(): raise FileExistsError(output)
    manifest=json.loads((source/"manifest.json").read_text())
    if manifest["status"]!="COMPLETE": raise ValueError("training incomplete")
    run_bytes=(source/"runs.csv").read_bytes()
    if hashlib.sha256(run_bytes).hexdigest()!=manifest["outputs_sha256"]["runs.csv"]:
        raise ValueError("training receipt mismatch")
    with (source/"runs.csv").open() as handle: rows=list(csv.DictReader(handle))
    groups=defaultdict(list)
    for row in rows:
        if row["policy"]!="fifo": continue
        if float(row["pmr"])==1 and float(row["tau_b"])!=.5: continue
        groups[tuple(row[k] for k in ("rho","pmr","tau_b","tau_s"))].append(row)
    cells=[]
    for key,group in groups.items():
        cell=dict(zip(("rho","pmr","tau_b","tau_s"),key))
        cell["p99"]=statistics.median(float(r["p99"]) for r in group)
        cells.append(cell)
    result=dict(purpose="exploratory new-family/new-seed evaluation, not Lcrit certification",
        source_sha256=manifest["outputs_sha256"]["runs.csv"],
        predictor_code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        training_seeds=manifest["spec"]["seeds"],
        baseline=fit_model(cells,False),timescale=fit_model(cells,True),
        frozen_before_v3_endpoint_inspection=True)
    output.write_text(json.dumps(result,indent=2))
    return result


def evaluate(model_path,source,analysis,output):
    output=Path(output)
    if output.exists(): raise FileExistsError(output)
    model=json.loads(Path(model_path).read_text())
    manifest=json.loads((Path(source)/"manifest.json").read_text())
    receipt=json.loads((Path(analysis)/"audit.json").read_text())
    if receipt["status"]!="PASS" or receipt["source_receipt"]!=manifest["outputs_sha256"]:
        raise ValueError("held-out data not audited")
    if set(model["training_seeds"]) & set(manifest["spec"]["seeds"]): raise ValueError("seed leakage")
    with (Path(analysis)/"points.csv").open() as handle: points=list(csv.DictReader(handle))
    predictions=[]
    for row in points:
        if row["policy"]!="fifo" or row["bucket"]: continue
        row=dict(row)
        row["baseline_prediction"]=predict(model["baseline"],row)
        row["timescale_prediction"]=predict(model["timescale"],row)
        predictions.append(row)
    metrics=[]
    for family in ("False","True"):
        cells=[row for row in predictions if row["jitter_service"]==family]
        for name in ("baseline","timescale"):
            error=[math.log(float(r[name+"_prediction"])/float(r["control_p99_latency_median"])) for r in cells]
            true_failure=[float(r["control_p99_latency_median"])>=1 or float(r["control_deadline_miss_ratio_median"])>=.01 for r in cells]
            pred_failure=[float(r[name+"_prediction"])>=1 for r in cells]
            metrics.append(dict(jittered=family,model=name,cells=len(cells),
                log_rmse=math.sqrt(statistics.mean(v*v for v in error)),
                median_absolute_log_error=statistics.median(abs(v) for v in error),
                false_safe=sum(t and not p for t,p in zip(true_failure,pred_failure)),
                false_alarm=sum(not t and p for t,p in zip(true_failure,pred_failure)),
                failure_cells=sum(true_failure)))
    output.mkdir(parents=True)
    with (output/"predictions.csv").open("w",newline="") as handle:
        writer=csv.DictWriter(handle,fieldnames=list(predictions[0]));writer.writeheader();writer.writerows(predictions)
    (output/"metrics.json").write_text(json.dumps(dict(metrics=metrics,
        model_sha256=hashlib.sha256(Path(model_path).read_bytes()).hexdigest(),
        source_receipt=receipt["source_receipt"]),indent=2))
    return metrics


if __name__=="__main__":
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("fit");p.add_argument("--input",required=True);p.add_argument("--out",required=True)
    p=sub.add_parser("evaluate");p.add_argument("--model",required=True);p.add_argument("--input",required=True);p.add_argument("--analysis",required=True);p.add_argument("--out",required=True)
    args=parser.parse_args()
    print(json.dumps(fit(args.input,args.out) if args.command=="fit" else evaluate(args.model,args.input,args.analysis,args.out)))
