"""Add explicit conversation/split reset boundaries to the frozen batch reader.

This wrapper does not modify any corpus, split, label, input or frozen manifest.
Reset and weighting metadata are operational metadata, never model features.
"""
import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('sgd_frozen_batches',ROOT/'batches.py')
reader=importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def iter_batches(manifest_path,batch_size=128,seed=20261011,split='TRAIN',allow_heldout=False):
    previous=None
    stream=reader.iter_batches(manifest_path,batch_size,seed,split,allow_heldout)
    try:
        for batch in stream:
            for row in batch:
                boundary=(row['ancestry']['split'],row['ancestry']['dialogue_id'])
                row['sampling']['state_reset_before_row']=boundary!=previous
                row['sampling']['schema_input_protocol']='all_TRAIN_service_schemas; never gold-frame-selected'
                previous=boundary
            yield batch
    finally:
        stream.close()


def input_view(row):
    """The complete utterance/context feature view; targets are separate."""
    return row['input']
