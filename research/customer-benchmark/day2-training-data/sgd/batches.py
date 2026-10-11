"""CPU-only, bounded SGD dialogue/group minibatch reader; no training or metrics.

TRAIN is the default and only training split. Heldout streaming requires an
explicit allow flag. Shuffle closure groups/dialogues, preserve turn order in a
dialogue, and detach any caller-owned state when dialogue_id changes. Only
row['input'] plus the separately declared all-service schema are features.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[3]


def sha(value):
    return hashlib.sha256(value).hexdigest()


def index_for(manifest_path,split):
    manifest_path=Path(manifest_path).resolve()
    raw=manifest_path.read_bytes();manifest=json.loads(raw)
    if manifest['status']!='ready_for_streaming_publisher_head_minibatch_training':
        raise ValueError('Packet is not fit-ready; full closure must freeze first')
    shards=[x for x in manifest['outputs'] if x['split']==split]
    if not shards:raise ValueError('No shards for split '+split)
    directory=REPO/Path(shards[0]['path']).parent
    path=directory/('.batch-index-'+split.lower()+'-'+sha(raw)[:16]+'.sqlite3')
    db=sqlite3.connect(path)
    db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY,value TEXT)')
    previous=dict(db.execute('SELECT key,value FROM metadata'))
    if previous.get('complete')=='1':
        if previous.get('manifest_sha256')!=sha(raw):raise ValueError('Stale batch index')
        return db,manifest
    db.execute('DROP TABLE IF EXISTS records')
    db.execute('CREATE TABLE records (group_id TEXT,dialogue_id TEXT,turn_index INTEGER,path TEXT,offset INTEGER,length INTEGER)')
    db.execute('DELETE FROM metadata')
    for spec in shards:
        source=REPO/spec['path'];digest=hashlib.sha256();count=size=0
        with source.open('rb') as handle:
            while True:
                offset=handle.tell();data=handle.readline()
                if not data:break
                digest.update(data);size+=len(data);count+=1
                row=json.loads(data);ancestry=row['ancestry']
                if ancestry['split']!=split:raise ValueError('Wrong split in shard')
                db.execute('INSERT INTO records VALUES (?,?,?,?,?,?)',(ancestry['group_id'],ancestry['dialogue_id'],ancestry['source_turn_index'],spec['path'],offset,len(data)))
        if digest.hexdigest()!=spec['sha256'] or count!=spec['rows'] or size!=spec['bytes']:
            db.rollback();db.close();raise ValueError('Shard hash/count mismatch')
    db.execute('CREATE INDEX records_group_dialogue_turn ON records (group_id,dialogue_id,turn_index)')
    db.executemany('INSERT INTO metadata VALUES (?,?)',[('manifest_sha256',sha(raw)),('complete','1'),('split',split)])
    db.commit()
    return db,manifest


def iter_batches(manifest_path,batch_size=128,seed=20261011,split='TRAIN',allow_heldout=False):
    if split not in ('TRAIN','CAL','EVAL') or split!='TRAIN' and not allow_heldout:
        raise ValueError('Heldout data is not a training stream; opt in separately')
    if not 1<=batch_size<=512:raise ValueError('Batch size must be1..512')
    db,manifest=index_for(manifest_path,split)
    groups=[x[0] for x in db.execute('SELECT DISTINCT group_id FROM records')]
    groups.sort(key=lambda x:sha((str(seed)+':group:'+x).encode()))
    files={};batch=[]
    try:
        for group in groups:
            conversations=[x[0] for x in db.execute('SELECT DISTINCT dialogue_id FROM records WHERE group_id=?',(group,))]
            conversations.sort(key=lambda x:sha((str(seed)+':dialogue:'+x).encode()))
            group_rows=db.execute('SELECT COUNT(*) FROM records WHERE group_id=?',(group,)).fetchone()[0]
            for dialogue in conversations:
                for path,offset,length in db.execute('SELECT path,offset,length FROM records WHERE group_id=? AND dialogue_id=? ORDER BY turn_index',(group,dialogue)):
                    if path not in files:files[path]=(REPO/path).open('rb')
                    handle=files[path];handle.seek(offset);row=json.loads(handle.read(length))
                    # Sampling metadata is deliberately outside feature input.
                    row['sampling']={'group_rows':group_rows,'row_group_loss_weight':1/group_rows,'detach_state_on_dialogue_change':True}
                    batch.append(row)
                    if len(batch)==batch_size:
                        yield batch;batch=[]
        if batch:yield batch
    finally:
        for handle in files.values():handle.close()
        db.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',required=True)
    p.add_argument('--batch-size',type=int,default=128)
    p.add_argument('--seed',type=int,default=20261011)
    p.add_argument('--split',choices=['TRAIN','CAL','EVAL'],default='TRAIN')
    p.add_argument('--allow-heldout-read',action='store_true')
    p.add_argument('--max-batches',type=int,default=2)
    args=p.parse_args();counts=Counter();groups=set();conversations=set()
    stream=iter_batches(args.manifest,args.batch_size,args.seed,args.split,args.allow_heldout_read)
    try:
        for number,batch in enumerate(stream,1):
            counts['batches']+=1;counts['examples']+=len(batch)
            for row in batch:
                groups.add(row['ancestry']['group_id']);conversations.add(row['ancestry']['dialogue_id'])
                counts['publisher_frames']+=len(row['targets']['frames'])
            if number>=args.max_batches:break
    finally:stream.close()
    print(json.dumps({'status':'actual_minibatch_read_passed','split':args.split,'counts':dict(counts),'closure_groups_seen':len(groups),'dialogues_seen':len(conversations),'model_fits':0,'features':'input only; all-service schema separately','caller_state':'detach on dialogue changes; no cross-split caches'},sort_keys=True))


if __name__=='__main__':main()
