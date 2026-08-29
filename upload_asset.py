"""上传 exe 到已存在的 Release"""
import json, urllib.request, urllib.error, os, sys

from net_guard import guarded_urlopen

REPO = "BYDXDM/transformed-desktop"
TAG = "v1.6.1"
EXE = "dist/transformed.exe"

def main():
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "transformed-upload",
    }
    # 获取现有 release 的 upload_url
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}",
        headers=headers, method="GET"
    )
    try:
        with guarded_urlopen(req) as r:
            release = json.loads(r.read())
            upload_url = release["upload_url"].split("{")[0]
            print(f"Release found: {release['html_url']}")
    except urllib.error.HTTPError as e:
        print(f"ERROR get release: {e.code} {e.read().decode()}")
        sys.exit(1)

    # 检查 exe 是否已存在，存在则先删除
    for asset in release.get("assets", []):
        if asset["name"] == "transformed.exe":
            print("Old asset exists, deleting...")
            del_req = urllib.request.Request(
                f"https://api.github.com/repos/{REPO}/releases/assets/{asset['id']}",
                headers=headers, method="DELETE"
            )
            guarded_urlopen(del_req)

    exe_path = os.path.join(os.path.dirname(__file__), EXE)
    if not os.path.exists(exe_path):
        print(f"File not found: {exe_path}")
        sys.exit(1)
    size_mb = os.path.getsize(exe_path) / 1024 / 1024
    print(f"Uploading transformed.exe ({size_mb:.1f} MB)...")

    with open(exe_path, "rb") as f:
        data = f.read()
        upload_req = urllib.request.Request(
            f"{upload_url}?name=transformed.exe",
            data=data,
            headers={**headers, "Content-Type": "application/octet-stream"},
            method="POST"
        )
        try:
            with guarded_urlopen(upload_req, timeout=300) as r:
                asset = json.loads(r.read())
                print(f"UPLOAD OK: {asset['browser_download_url']}")
        except urllib.error.HTTPError as e:
            print(f"ERROR upload: {e.code} {e.read().decode()}")
            sys.exit(1)
        except Exception as e:
            print(f"ERROR: {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()
