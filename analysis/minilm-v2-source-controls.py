"""Bounded actual CUDA gradient and input controls; no quality evaluation."""
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'integrations/learned-dialogue/minilm_ft_v2/runtime'))
from minilm_ft_core import Model,observed_parts
import torch

torch.set_num_threads(4)
started=time.monotonic()
model=Model(ROOT/'integrations/learned-dialogue/minilm_ft_v1/model/encoder','cuda',True)
rows=[{'input':{'current_utterance':'randevu '*1600+' Son sözüm: önceki sözü geri alıyorum.',
 'previous_utterances':[{'speaker':'USER','text':'Ödeyeceğimi söyledim.'},{'speaker':'ASSISTANT','text':'Hâlâ onaylıyor musunuz?'}]}} for _ in range(4)]
model.encoder.train()
with torch.autocast('cuda',dtype=torch.bfloat16):
 features=model.encode(rows);loss=model.head(features).square().mean()
loss.backward()
gradient=sum(float(p.grad.float().abs().sum()) for p in model.encoder.parameters() if p.grad is not None)
assert features.shape==(4,1152) and torch.isfinite(features).all() and gradient>0
assert not torch.allclose(features[:,:384],features[:,384:768])
assert not model.encoder.is_gradient_checkpointing
model.encoder.eval()
with torch.inference_mode():
 blank=model.encode([{'input':{'current_utterance':'Okay','previous_utterances':[]}}])
 noctx=model.encode(rows[:1],no_context=True)
 notail=model.encode(rows[:1],no_tail=True)
assert (blank[:,768:]==0).all() and (noctx[:,768:]==0).all() and (notail[:,384:768]==0).all()
try:observed_parts({'input':{'current_utterance':'yes','previous_utterances':[],'phase':'consent'}})
except ValueError:pass
else:raise AssertionError('Oracle feature admitted')
x=torch.zeros(4,requires_grad=True)
bce=torch.nn.functional.binary_cross_entropy_with_logits(x,torch.ones_like(x))
full=torch.autograd.grad(bce,x,retain_graph=True)[0]
quarter=torch.autograd.grad(.25*bce,x)[0]
assert torch.allclose(quarter,full*.25)
r={'status':'ACTUAL_CUDA_SOURCE_CONTROLS_PASS','tests':8,'GPU':torch.cuda.get_device_name(),
 'gradient_abs_sum':gradient,'large_current_characters':len(rows[0]['input']['current_utterance']),
 'overflow_windows':len(model.tokenizer([observed_parts(r)[0] for r in rows],truncation=True,max_length=256,stride=32,return_overflowing_tokens=True)['input_ids']),
 'peak_GPU_bytes':torch.cuda.max_memory_allocated(),'seconds':time.monotonic()-started,
 'model_quality_claim':False,'cloud_launches':0,
 'source_sha256':hashlib.sha256((ROOT/'integrations/learned-dialogue/minilm_ft_v2/runtime/minilm_ft_core.py').read_bytes()).hexdigest()}
(ROOT/'analysis/minilm-v2-source-controls.json').write_text(json.dumps(r,indent=2)+'\n',encoding='utf8')
print(json.dumps(r))
