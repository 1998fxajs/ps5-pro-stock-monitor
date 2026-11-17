"""Best-effort local OCR of public post images; no paid API or credentials."""
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

def recognize(data):
    command=shutil.which('tesseract')
    if not command:return '', 'OCR unavailable'
    if len(data)>4_000_000:return '', 'image exceeds OCR limit'
    with tempfile.TemporaryDirectory(prefix='ps5-ocr-') as folder:
        path=Path(folder)/'image';path.write_bytes(data)
        try:
            result=subprocess.run([command,str(path),'stdout','-l','kor+eng','--psm','11'],
                capture_output=True,timeout=8,env={**os.environ,'OMP_THREAD_LIMIT':'1'})
            if result.returncode:return '', 'OCR failed'
            text=result.stdout.decode('utf-8',errors='replace').strip()
            return text[:8000], 'OCR read' if text else 'OCR empty'
        except subprocess.TimeoutExpired:return '', 'OCR timed out'
