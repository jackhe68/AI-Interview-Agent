"""Download pinned public weights for local evaluation; uploads no user audio."""
import hashlib
import json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1] / 'models/emotion2vec-plus-base-onnx'
ROOT.mkdir(parents=True, exist_ok=True)
REV='334d4376993c381f059cc36d2c6ed05cbfec5ca1'
REPO='pankotaro/emotion2vec-plus-base-onnx'
manifest={'repository':REPO,'revision':REV,'files':{}}
for name in ['LICENSE','README.md','emotion2vec_head.json','emotion2vec_plus_base.onnx']:
    path=ROOT/name
    if not path.exists():
        url=f'https://huggingface.co/{REPO}/resolve/{REV}/{name}'
        with requests.get(url, stream=True, timeout=(15,45)) as response:
            response.raise_for_status()
            with path.with_suffix(path.suffix+'.part').open('wb') as f:
                for chunk in response.iter_content(1024*1024): f.write(chunk)
        path.with_suffix(path.suffix+'.part').replace(path)
    digest=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): digest.update(chunk)
    manifest['files'][name]={'sha256':digest.hexdigest(),'bytes':path.stat().st_size}
    print('Downloaded/verified',name,path.stat().st_size,flush=True)
(ROOT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
