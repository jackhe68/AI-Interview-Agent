"""Build a code-only release. Runtime data is never a packaging input."""
import argparse
import hashlib
import io
import json
import tarfile
from pathlib import Path

# Explicit paths avoid accidentally including new databases, credentials or uploads.
RELEASE_FILES = (
    'app.py', 'account_migration.py', 'accounts.py', 'ai_limits.py', 'api_guard.py',
    'asset_delivery.py', 'audio_analysis.py', 'candidate_background.py', 'database.py',
    'deletion_journal.py', 'interview_catalog.py', 'interview_time.py', 'observability.py',
    'practice_feedback.py', 'public_test.py', 'reanswer.py', 'report_jobs.py',
    'report_pdf.py', 'speech.py', 'speech_review.py', 'speech_temp.py',
    'index.html', 'account.html', 'interview.html', 'history.html', 'report.html',
    'privacy.html', 'error.html',
    'static/js/account.js', 'static/js/account-page.js', 'static/js/drafts.js',
    'static/js/history.js', 'static/js/interview.js', 'static/js/main.js',
    'static/js/navigation.js', 'static/js/reanswer.js', 'static/js/report.js',
    'static/css/style.css', 'static/css/account.css', 'static/css/home.css',
    'assets/fonts/InterviewSans-Regular.ttf', 'assets/fonts/OFL.txt', 'assets/fonts/README.md',
    'deploy/wsgi.py', 'deploy/requirements.txt', 'deploy/bootstrap.sh',
    'deploy/nginx.conf', 'deploy/aiinterview.service', 'deploy/README.md',
    'deploy/package_release.py', 'tools/account_store.py',
    'docs/accounts-and-operations.md', 'README.md', '.env.example',
)


def build_release(root, output):
    root = Path(root).resolve()
    output = Path(output).absolute()
    if not output.name.endswith('.tar.gz'):
        raise ValueError('Release output must end in .tar.gz')
    if output.exists() or output.is_symlink():
        raise ValueError('Release output must be a new file')
    selected = []
    for name in RELEASE_FILES:
        path = root / name
        # Reject symlinks/junctions, including links inside an otherwise allowed directory.
        if path.resolve() != path.absolute() or path.is_symlink() or not path.is_file():
            raise ValueError('Missing or unsafe release source: ' + name)
        selected.append((name, path))
    output.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        with output.open('xb') as destination:
            created = True
            with tarfile.open(fileobj=destination, mode='w:gz', format=tarfile.PAX_FORMAT) as archive:
                entries = []
                for name, path in selected:
                    content = path.read_bytes()
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    info.mode = 0o755 if name.endswith('.sh') else 0o644
                    archive.addfile(info, io.BytesIO(content))
                    entries.append(dict(path=name, bytes=len(content), sha256=hashlib.sha256(content).hexdigest()))
                manifest = json.dumps(dict(schema='code-release-v1', files=entries), indent=2).encode('utf-8')
                info = tarfile.TarInfo('release-manifest.json')
                info.size = len(manifest)
                info.mode = 0o644
                archive.addfile(info, io.BytesIO(manifest))
    except BaseException:
        if created:
            output.unlink(missing_ok=True)  # Only this invocation's incomplete, newly created output.
        raise
    return len(selected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    count = build_release(Path(__file__).resolve().parents[1], args.output)
    print(json.dumps(dict(files=count, runtime_data_included=False)))


if __name__ == '__main__':
    main()
