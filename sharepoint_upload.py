"""Deliver a file or folder to SharePoint via a OneDrive-synced folder or Microsoft Graph."""
from __future__ import annotations

import argparse
import base64
import os
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote

from veeva_download import HTTP, configure_proxy, load_env_file

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
# Microsoft Graph Command Line Tools: a Microsoft public client usable for delegated sign-in.
DEFAULT_PUBLIC_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"
USER_SCOPES = ["Files.ReadWrite.All"]
SIMPLE_UPLOAD_LIMIT = 4 * 1024 * 1024
CHUNK_SIZE = 320 * 1024 * 16
# SharePoint writes library metadata into Office files, so their stored size differs.
OFFICE_SUFFIXES = {".docx", ".docm", ".xlsx", ".xlsm", ".pptx", ".pptm", ".doc", ".xls", ".ppt"}
PROJECT = Path(__file__).resolve().parent
TOKEN_CACHE = PROJECT / ".msal_token_cache.json"
# SHAREPOINT_UPLOAD_METHOD values: graph = Microsoft Graph upload, sync = copy into OneDrive-synced folder, none = no upload.
UPLOAD_METHODS = ("graph", "sync", "none")


def upload_method(override: str | None = None) -> str:
    method = (override or os.environ.get("SHAREPOINT_UPLOAD_METHOD", "")).strip().lower()
    if method not in UPLOAD_METHODS:
        raise ValueError(f"Set SHAREPOINT_UPLOAD_METHOD in .env to one of {', '.join(UPLOAD_METHODS)} (got {method!r})")
    return method


def env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    return default if not value else value in ("1", "true", "yes", "on")


def deliver(source: Path, method: str | None = None, use_proxy: bool | None = None) -> str | None:
    """Upload source per SHAREPOINT_UPLOAD_METHOD (or the override); returns the destination, or None for 'none'."""
    method = upload_method(method)
    if method == "sync":
        return str(copy_to_synced_folder(source, Path(required_config("SHAREPOINT_SYNC_FOLDER"))))
    if method == "graph":
        if use_proxy is None:
            use_proxy = env_flag("SHAREPOINT_USE_PROXY", True)
        return upload_with_graph(source, os.environ.get("SHAREPOINT_AUTH", "user").strip() or "user", use_proxy)
    print("SHAREPOINT_UPLOAD_METHOD=none; skipping SharePoint upload")
    return None


def required_config(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or value.startswith("your-"):
        raise ValueError(f"Set a real value for {name} in .env")
    return value


def copy_to_synced_folder(source: Path, sync_folder: Path) -> Path:
    if not sync_folder.is_dir():
        raise FileNotFoundError(f"OneDrive sync folder not found: {sync_folder}")
    destination = sync_folder / source.name
    if destination.exists():
        raise FileExistsError(f"Already exists in SharePoint folder, not overwriting: {destination}")

    if source.is_dir():
        shutil.copytree(source, destination)
        pairs = [(p, destination / p.relative_to(source)) for p in source.rglob("*") if p.is_file()]
    else:
        shutil.copy2(source, destination)
        pairs = [(source, destination)]

    for original, copied in pairs:
        if not copied.is_file() or copied.stat().st_size != original.stat().st_size:
            raise RuntimeError(f"Copy verification failed: {copied}")
    print(f"Verified {len(pairs)} file(s); OneDrive will sync them to SharePoint.")
    return destination


def user_token() -> str:
    import msal

    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE.is_file():
        cache.deserialize(TOKEN_CACHE.read_text(encoding="utf-8"))
    tenant = os.environ.get("AZURE_TENANT_ID", "").strip() or "organizations"
    login = os.environ.get("SHAREPOINT_LOGIN", "broker").strip().lower()
    app = msal.PublicClientApplication(
        os.environ.get("SHAREPOINT_PUBLIC_CLIENT_ID", "").strip() or DEFAULT_PUBLIC_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{tenant}",
        token_cache=cache,
        http_client=HTTP,
        enable_broker_on_windows=login == "broker",
    )
    accounts = app.get_accounts()
    result = app.acquire_token_silent(USER_SCOPES, account=accounts[0]) if accounts else None
    if not result and login == "device":
        flow = app.initiate_device_flow(scopes=USER_SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"Could not start sign-in: {flow.get('error_description', flow)}")
        print(flow["message"], flush=True)
        result = app.acquire_token_by_device_flow(flow)
    elif not result:
        print("Opening Microsoft sign-in window...", flush=True)
        result = app.acquire_token_interactive(
            USER_SCOPES,
            parent_window_handle=app.CONSOLE_WINDOW_HANDLE,
            login_hint=os.environ.get("SHAREPOINT_LOGIN_HINT") or None,
        )
    if "access_token" not in result:
        raise RuntimeError(f"Sign-in failed: {result.get('error')}: {result.get('error_description')}")
    if cache.has_state_changed:
        TOKEN_CACHE.write_text(cache.serialize(), encoding="utf-8")
    return result["access_token"]


def app_token() -> str:
    tenant_id = required_config("AZURE_TENANT_ID")
    response = HTTP.post(
        f"https://login.microsoftonline.com/{quote(tenant_id, safe='')}/oauth2/v2.0/token",
        data={
            "client_id": required_config("AZURE_CLIENT_ID"),
            "client_secret": required_config("AZURE_CLIENT_SECRET"),
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["access_token"]


class Graph:
    def __init__(self, token: str) -> None:
        self.headers = {"Authorization": f"Bearer {token}"}

    def call(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        if not url.startswith("https://"):
            url = GRAPH_ROOT + url
        response = HTTP.request(method, url, headers={**self.headers, **kwargs.pop("headers", {})}, timeout=300, **kwargs)
        if not response.ok:
            raise RuntimeError(f"Graph {method} {url} failed ({response.status_code}): {response.text}")
        return response.json() if response.content else {}

    def resolve_target(self) -> tuple[str, str]:
        share_url = os.environ.get("SHAREPOINT_SHARE_URL", "").strip()
        if share_url:
            encoded = base64.urlsafe_b64encode(share_url.encode("utf-8")).decode("ascii").rstrip("=")
            item = self.call("GET", f"/shares/u!{encoded}/driveItem")
            return item["parentReference"]["driveId"], item["id"]
        drive_id = required_config("SHAREPOINT_DRIVE_ID")
        folder = os.environ.get("SHAREPOINT_FOLDER_PATH", "").strip("/")
        path = f"/root:/{quote(folder)}" if folder else "/root"
        return drive_id, self.call("GET", f"/drives/{quote(drive_id, safe='')}{path}")["id"]

    def create_folder(self, drive_id: str, parent_id: str, name: str) -> str:
        body = {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
        return self.call("POST", f"/drives/{drive_id}/items/{parent_id}/children", json=body)["id"]

    def upload_file(self, drive_id: str, parent_id: str, file: Path) -> dict[str, Any]:
        target = f"/drives/{drive_id}/items/{parent_id}:/{quote(file.name)}:"
        size = file.stat().st_size
        if size <= SIMPLE_UPLOAD_LIMIT:
            item = self.call("PUT", f"{target}/content?@microsoft.graph.conflictBehavior=fail", data=file.read_bytes())
        else:
            body = {"item": {"@microsoft.graph.conflictBehavior": "fail"}}
            session_url = self.call("POST", f"{target}/createUploadSession", json=body)["uploadUrl"]
            with file.open("rb") as handle:
                start = 0
                while start < size:
                    chunk = handle.read(CHUNK_SIZE)
                    end = start + len(chunk) - 1
                    # Upload URLs are pre-authenticated and reject the Authorization header.
                    response = HTTP.put(session_url, data=chunk, timeout=300, headers={"Content-Range": f"bytes {start}-{end}/{size}"})
                    if not response.ok:
                        raise RuntimeError(f"Chunk upload failed for {file} ({response.status_code}): {response.text}")
                    start = end + 1
            item = response.json()
        if item.get("size") != size and not (file.suffix.lower() in OFFICE_SUFFIXES and item.get("size")):
            raise RuntimeError(f"Upload size mismatch for {file}")
        return item


def upload_with_graph(source: Path, auth: str, use_proxy: bool = True) -> str:
    if use_proxy:
        configure_proxy()
    else:
        HTTP.proxies.clear()
        print("Not using VEEVA_PROXY for Microsoft Graph")
    graph = Graph(user_token() if auth == "user" else app_token())
    drive_id, parent_id = graph.resolve_target()

    if source.is_file():
        return graph.upload_file(drive_id, parent_id, source).get("webUrl", "")

    folder_ids = {source: graph.create_folder(drive_id, parent_id, source.name)}
    count = 0
    for path in sorted(source.rglob("*")):
        parent = folder_ids[path.parent]
        if path.is_dir():
            folder_ids[path] = graph.create_folder(drive_id, parent, path.name)
        else:
            graph.upload_file(drive_id, parent, path)
            count += 1
            print(f"Uploaded {path.relative_to(source.parent)}")
    print(f"Verified {count} file(s) uploaded through Microsoft Graph.")
    return graph.call("GET", f"/drives/{drive_id}/items/{folder_ids[source]}").get("webUrl", "")


def main() -> None:
    load_env_file(PROJECT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", help="File or folder to deliver (default: <VEEVA_OUTPUT_FOLDER>/<VEEVA_REQUEST_ID>)")
    parser.add_argument("--method", choices=UPLOAD_METHODS, help="Override SHAREPOINT_UPLOAD_METHOD from .env")
    parser.add_argument("--no-proxy", action="store_true", help="Override SHAREPOINT_USE_PROXY: do not route Graph calls through VEEVA_PROXY")
    args = parser.parse_args()

    source = Path(args.source) if args.source else PROJECT / required_config("VEEVA_OUTPUT_FOLDER") / required_config("VEEVA_REQUEST_ID")
    if not source.exists():
        raise FileNotFoundError(f"Delivery does not exist: {source}")

    destination = deliver(source, args.method, False if args.no_proxy else None)
    if destination:
        print(f"Delivered: {source}")
        print(f"Destination: {destination}")


if __name__ == "__main__":
    main()
