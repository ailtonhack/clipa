"""Convenience launcher; load .env without printing or executing its contents."""
import os
from pathlib import Path
import uvicorn

root = Path(__file__).resolve().parent
os.chdir(root)
path = root / '.env'
if path.exists():
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        name, value = line.split('=', 1)
        name = name.strip()
        if name.replace('_', '').isalnum() and value.strip():
            os.environ.setdefault(name, value.strip().strip('\"\''))
if __name__ == '__main__':
    uvicorn.run('backend.app:app', host=os.getenv('CLIPA_BIND', '127.0.0.1'), port=int(os.getenv('PORT', '8000')), access_log=False)
