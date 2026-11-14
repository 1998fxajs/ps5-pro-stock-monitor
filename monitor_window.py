"""PS5 Pro watch expires after 2026-11-19 23:59:59 Korea time."""
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.request import Request, urlopen
from urllib.error import HTTPError

KST = ZoneInfo("Asia/Seoul")
END_EXCLUSIVE = datetime(2026, 11, 20, 0, 0, tzinfo=KST)

def is_active_at(now=None):
    now = now or datetime.now(KST)
    return now.astimezone(KST) < END_EXCLUSIVE

def disable_own_workflow():
    """Best-effort GitHub disable to stop scheduled runs after cutoff."""
    name = os.environ.get("WORKFLOW_FILENAME", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not (name and repo and token):
        print("Disable unavailable: missing GitHub workflow context")
        return False
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{name}/disable"
    req = Request(url, method="PUT", headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urlopen(req, timeout=15) as r:
            print(f"Disabled expired workflow {name}: HTTP {r.status}")
            return True
    except HTTPError as exc:
        print(f"Could not disable workflow {name} (HTTP {exc.code}), but monitoring remains gated.")
        return False
    except Exception as exc:
        print(f"Could not disable workflow {name}: {type(exc).__name__}. Monitoring remains gated.")
        return False

def main():
    current = datetime.now(KST)
    active = is_active_at(current)
    print(f"Monitoring active={active}; now={current.isoformat()} cutoff={END_EXCLUSIVE.isoformat()}")
    if not active:
        disable_own_workflow()
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as f:
            f.write(f"active={'true' if active else 'false'}\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
