"""One ephemeral H100 training job; explicit public/synthetic uploads only."""
import io, json, os, sys, time, zipfile
from pathlib import Path

def remote_train(seconds,epochs,batch_size):
    sys.path.insert(0,'/opt/ft')
    from minilm_ft_core import train_both
    result=train_both('/opt/ft/train.jsonl.gz','/opt/ft/cal.jsonl.gz','/opt/ft/encoder','/tmp/ft-output',seconds,epochs,batch_size)
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as archive:
        for p in Path('/tmp/ft-output').rglob('*'):
            if p.is_file():archive.write(p,p.relative_to('/tmp/ft-output').as_posix())
    return {'reports':result,'archive':stream.getvalue()}

def create_app(train_file,cal_file,encoder,compute_seconds=1800,app_name='freya-minilm-real-finetune-v1'):
    import modal
    if not 1<=compute_seconds<=2400:raise ValueError('bounded compute required')
    image=modal.Image.debian_slim(python_version='3.11').pip_install('torch==2.6.0','transformers==4.48.3','safetensors==0.5.2','numpy==2.2.6').env({'PYTHONPATH':'/opt/ft','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1','TOKENIZERS_PARALLELISM':'false'})
    image=image.add_local_file(str(Path(__file__).with_name('minilm_ft_core.py')),remote_path='/opt/ft/minilm_ft_core.py',copy=True)
    image=image.add_local_file(str(Path(__file__)),remote_path='/opt/ft/minilm_ft_modal.py',copy=True)
    for filename,path in [('train.jsonl.gz',train_file),('cal.jsonl.gz',cal_file)]:
        image=image.add_local_file(str(path),remote_path='/opt/ft/'+filename,copy=True)
    # No directory discovery: encoder file names are fixed and copied after pin checks.
    for name in ['config.json','model.safetensors','tokenizer.json','tokenizer_config.json','special_tokens_map.json','vocab.txt']:
        image=image.add_local_file(str(Path(encoder)/name),remote_path='/opt/ft/encoder/'+name,copy=True)
    app=modal.App(app_name,include_source=False)
    # Modal's own large-result upload requires network; model loading stays local/offline.
    function=app.function(image=image,serialized=True,include_source=False,gpu='H100',cpu=(4,4),memory=(16384,16384),retries=0,timeout=compute_seconds+60,startup_timeout=240,min_containers=0,buffer_containers=0,max_containers=1,scaledown_window=2,single_use_containers=True,secrets=[],volumes={},schedule=None)(remote_train)
    return app,function
