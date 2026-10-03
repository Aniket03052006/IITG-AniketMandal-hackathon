"""Second look at the e5-base event result on every held-out set (run after evaluate.py; same rules, nothing tuned on gold or replay_check)."""
import sys, json
sys.path.insert(0,'experiments/embeddings'); sys.path.insert(0,'src')
import numpy as np
import evaluate as X
from pathlib import Path
from sklearn.linear_model import LogisticRegression
from eventshock.pipeline.config import load_event_model_config
from eventshock.pipeline.event_model import EventModel
from eventshock.modeling.event_eval import LABELS, K, gold_event_sets
from eventshock.modeling.sentiment_train import fit_temperature, softmax, nll
R=X.ROOT; emb=Path(sys.argv[1])
cfg=load_event_model_config(R/'configs'); prod=EventModel.load(R/cfg.model_dir)
rows=[json.loads(l) for l in (R/cfg.table).read_text().split('\n') if l.strip()]
lab={c:i for i,c in enumerate(LABELS)}
tr=[r for r in rows if r['split']=='train' and r['kind']=='annotated']
dev=[r for r in rows if r['split']=='dev' and prod.unscorable_reason(r['text']) is None]
rc=[r for r in rows if r['split']=='replay_check' and prod.unscorable_reason(r['text']) is None]
e=X.load_emb(emb,'intfloat__multilingual-e5-base')
f=lambda rs: np.stack([e[X.key(r['text'])] for r in rs])
ytr=np.array([lab[r['label']] for r in tr]); ydev=np.array([lab[r['label']] for r in dev])
best=None
for C in (0.3,1,3,10,30):
    for cw in (None,'balanced'):
        m=LogisticRegression(C=C,class_weight=cw,max_iter=3000).fit(f(tr),ytr)
        o=[list(m.classes_).index(c) for c in range(K)]
        z=m.decision_function(f(dev))[:,o]; T=fit_temperature(z,ydev,cfg.temperature_grid); ll=nll(softmax(z,T),ydev)
        if best is None or ll<best[0]: best=(ll,m,o,T,C,cw)
ll,m,o,T,C,cw=best; print('chosen',C,cw,T,ll)
g=gold_event_sets(R/'data/gold')
sets={'replay_check':([r['text'] for r in rc],np.array([lab[r['label']] for r in rc]),np.ones(len(rc)))}
sets['gold_tfn']=(g['tfn'][0],np.array([lab[c] for c in g['tfn'][1]]),np.array(g['tfn'][2]))
sets['gold_history']=(g['history'][0],np.array([lab[c] for c in g['history'][1]]),np.array(g['history'][2]))
sets['dev_history(selected on)']=([r['text'] for r in dev if r['population']=='history'],np.array([lab[r['label']] for r in dev if r['population']=='history']),np.array([r['pop_weight'] for r in dev if r['population']=='history']))
for name,(t,y,w) in sets.items():
    pt=prod.probabilities(t); pe=softmax(m.decision_function(np.stack([e[X.key(x)] for x in t]))[:,o],T)
    st,se=X.served(pt),X.served(pe)
    a,b=X.paired_boot(X.macro_f1,y,se,st,w); c,d=X.paired_boot(X.detect_f1,y,se,st,w)
    print(f"{name:26s} n={len(y):4d} served-macroF1 tfidf {X.macro_f1(y,st,w):.3f} e5 {X.macro_f1(y,se,w):.3f} diff CI [{a:+.3f},{b:+.3f}] | detection tfidf {X.detect_f1(y,st,w):.3f} e5 {X.detect_f1(y,se,w):.3f} CI [{c:+.3f},{d:+.3f}] | logloss tfidf {nll(pt,y):.3f} e5 {nll(pe,y):.3f}")
