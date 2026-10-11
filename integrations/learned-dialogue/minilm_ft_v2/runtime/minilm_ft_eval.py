"""V2 pinned loader, used by isolated builder inference."""
import hashlib
import json
from pathlib import Path
from minilm_ft_core import Model,DOMAIN,AUX


def load_model(path,device='cpu'):
    from safetensors.torch import load_file
    path=Path(path);manifest=json.loads((path/'manifest.json').read_text(encoding='utf8'))
    for name,digest in manifest['files'].items():
        if '..' in Path(name).parts or Path(name).is_absolute():raise ValueError('Manifest path')
        if hashlib.sha256((path/name).read_bytes()).hexdigest()!=digest:raise ValueError('V2 model artifact pin '+name)
    if manifest['labels']!=DOMAIN+AUX or manifest['bank_authority'] is not False:raise ValueError('Output contract')
    architecture=json.loads((path/'architecture.json').read_text(encoding='utf8'))
    if architecture!={'version':2,'features':['current_global_mean','current_last_window','prior_observed_context'],'width':1152,'max_window_tokens':256,'stride':32}:raise ValueError('V2 architecture contract')
    model=Model(path/'encoder',device,False);model.head.load_state_dict(load_file(str(path/'head.safetensors')));model.head.eval();model.encoder.eval()
    return model,manifest
