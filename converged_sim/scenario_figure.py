"""Compare checked offline scenario predictions; no fitted models or new trials."""
import argparse
import csv
import json
from pathlib import Path
from ns3_validation.renewal_cli import digest
from .scientific_figures import start, text, line, save


def plot(inputs, out):
    cohorts=[]
    for folder in inputs:
        source=Path(folder); receipt=json.loads((source/'audit.json').read_text())
        if receipt['status']!='PASS' or digest(source/'runs.csv')!=receipt['outputs_sha256']['runs.csv']:
            raise ValueError('SHA-checked prediction table required')
        with (source/'runs.csv').open() as handle: rows=list(csv.DictReader(handle))
        if len(rows)!=receipt['runs']:raise ValueError('run coverage')
        cohorts.append((receipt['evaluation_scope'],rows))
    svg=start(1080,530,'Offline scenario predictions versus native ns-3 control tails')
    colors={'development':'#888888','heldout':'#0072B2'}
    allrows=[row for _,rows in cohorts for row in rows]
    limit=max(2.,max(float(row['observed_control_p99_T']) for row in allrows)*1.08)
    for panel,model in enumerate(('packet','fluid')):
        x0,y0,w,h=70+panel*540,83,425,325
        def xx(v):return x0+v/limit*w
        def yy(v):return y0+h-v/limit*h
        text(svg,x0,y0-28,'Frame-start rate' if model=='packet' else 'Continuously integrated rate',15)
        text(svg,x0,y0-8,'Predicted control P99 / T',12)
        line(svg,x0,y0,x0,y0+h);line(svg,x0,y0+h,x0+w,y0+h)
        line(svg,xx(0),yy(0),xx(limit),yy(limit),'#aaa',True)
        line(svg,xx(1),y0,xx(1),y0+h,'#bbb',True)
        line(svg,x0,yy(1),x0+w,yy(1),'#bbb',True)
        for v in (0,.5,1,1.5,2):
            if v<=limit:
                text(svg,xx(v),y0+h+17,f'{v:g}',11,'middle')
                text(svg,x0-8,yy(v)+4,f'{v:g}',11,'end')
        false_safe=0
        for scope,rows in cohorts:
            for row in rows:
                x=xx(float(row['observed_control_p99_T']));y=yy(float(row[model+'_control_p99_T']))
                wrong=row[model+'_joint_pass']=='True' and row['observed_joint_pass']!='True'
                false_safe+=wrong
                svg.append(f'<circle cx="{x:.3f}" cy="{y:.3f}" r="{4 if wrong else 2.7}" fill="{colors[scope]}" opacity=".65"/>')
                if wrong:
                    line(svg,x-5,y-5,x+5,y+5,'#D55E00');line(svg,x-5,y+5,x+5,y-5,'#D55E00')
        text(svg,x0+12,y0+20,f'False-safe runs: {false_safe}',12)
        text(svg,x0+w/2,y0+h+37,'Observed control P99 / T',12,'middle')
    text(svg,70,467,'Gray: 120 development reanalyses. Blue: 120 new held-out native runs. Points may overlap.',12)
    text(svg,70,491,'Orange crosses: false-safe under the joint rule P99 &lt; 1T AND miss fraction &lt; 1%.',12)
    text(svg,70,515,'Full prescribed service and generated arrivals available: OFFLINE planning, not online safety or novelty proof.',11)
    save(svg,out)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',nargs='+',required=True);parser.add_argument('--out',required=True)
    args=parser.parse_args();plot(args.input,args.out)
