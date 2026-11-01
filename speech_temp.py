"""Private, record-scoped transient audio; remove known files on restart/deletion."""
import hashlib,os,re,tempfile
from pathlib import Path

NAME=re.compile(r'[0-9a-f]{64}-[a-z0-9_]+\.(?:webm|mp3|wav|m4a|ogg|mp4|aac)')
EXTENSIONS={'.webm','.mp3','.wav','.m4a','.ogg','.mp4','.aac'}

def root(db):
    directory=Path(db.DB_PATH).resolve().parent/'.speech-temp'
    if directory.is_symlink() or directory.resolve()!=directory:raise RuntimeError('Temporary audio directory must not be a symlink')
    directory.mkdir(mode=0o700,exist_ok=True)
    return directory

def create(db,sid,ext):
    if ext not in EXTENSIONS:raise ValueError('Unsupported temporary audio format')
    prefix=hashlib.sha256((sid or 'unbound-test-upload').encode()).hexdigest()+'-'
    fd,path=tempfile.mkstemp(prefix=prefix,suffix=ext,dir=root(db));os.close(fd)
    return path

def cleanup(db,interview_ids=None):
    directory=root(db)
    hashes=None if interview_ids is None else {hashlib.sha256(sid.encode()).hexdigest() for sid in interview_ids}
    remaining=0
    for file in directory.iterdir():
        if not NAME.fullmatch(file.name) or file.is_symlink() or not file.is_file():continue
        # Every candidate resolves directly under the intended private directory.
        if file.resolve().parent!=directory.resolve():continue
        if hashes is not None and file.name.split('-',1)[0] not in hashes:continue
        try:file.unlink(missing_ok=True)
        except OSError:remaining+=1  # Windows can hold an in-flight decoder handle; request-finally retries.
    return remaining
