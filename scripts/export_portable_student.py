"""Package a verified frozen student closure without training tensors.

This packages trained artifacts, not a phone workflow. It cannot enable the
unqualified student or modify its weights, runtime, calibration or thresholds.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--source-sha256',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    source=a.source.resolve(strict=True)
    if a.output.exists():raise ValueError('Never overwrite a frozen export')
    if digest(source/'manifest.json')!=a.source_sha256:raise ValueError('Source manifest pin')
    manifest=json.loads((source/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('bank_authority') is not False or manifest.get('default_enabled') is not False:
        raise ValueError('Only shadow-only non-authoritative bundles are allowed')
    for name,pin in manifest['files'].items():
        path=(source/name).resolve(strict=True)
        if path.parent!=source or path.name!=name or digest(path)!=pin:
            raise ValueError('Source closure changed: '+name)
    a.output.mkdir(parents=True)
    for name in ('runtime.py','model.json'):shutil.copyfile(source/name,a.output/name)
    provenance=dict(source_manifest_sha256=a.source_sha256,
                    source_schema=manifest['schema'],teacher_manifest_sha256=manifest.get('teacher_manifest_sha256'),
                    TRAIN_rows_seen=manifest.get('TRAIN_rows_seen'),epochs=manifest.get('epochs'),
                    promotion=manifest.get('promotion'),risk_qualified=False,
                    model_kind=manifest.get('model_kind','PORTABLE_STUDENT_NOT_MINILM'),
                    full_encoder_embedded=False,bank_authority=False,default_enabled=False)
    (a.output/'training-provenance.json').write_bytes((json.dumps(provenance,indent=2)+'\n').encode('utf-8'))
    exported=dict(schema='portable-student-export.v1',model_kind=provenance['model_kind'],
                  default_enabled=False,bank_authority=False,promotion='NONE_DIAGNOSTIC_SHADOW',
                  files={name:digest(a.output/name) for name in ('runtime.py','model.json','training-provenance.json')},
                  source_manifest_sha256=a.source_sha256)
    (a.output/'manifest.json').write_bytes((json.dumps(exported,indent=2)+'\n').encode('utf-8'))
    if digest(source/'manifest.json')!=a.source_sha256:raise ValueError('Source manifest changed')
    print(json.dumps(dict(manifest_sha256=digest(a.output/'manifest.json'),files=exported['files'])))


if __name__=='__main__':main()
