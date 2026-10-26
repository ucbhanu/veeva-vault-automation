# Databricks notebook source
"""Upload a delivery ZIP to a Teams-connected SharePoint library."""
from __future__ import annotations

import json
import mimetypes
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def required_config(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value or value.startswith("your-"):
        raise ValueError(f"Set a real value for {name} in .env")
    return value


def get_access_token() -> str:
    tenant_id = required_config("AZURE_TENANT_ID")
    form = urlencode({
        "client_id": required_config("AZURE_CLIENT_ID"),
        "client_secret": required_config("AZURE_CLIENT_SECRET"),
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }).encode("utf-8")
    token_url = f"https://login.microsoftonline.com/{quote(tenant_id, safe='')}/oauth2/v2.0/token"
    request = Request(token_url, data=form, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urlopen(request) as response:
        return json.load(response)["access_token"]


def upload_zip(zip_path: Path) -> str:
    if not zip_path.is_file():
        raise FileNotFoundError(f"ZIP file does not exist: {zip_path}")

    site_id = required_config("SHAREPOINT_SITE_ID")
    drive_id = required_config("SHAREPOINT_DRIVE_ID")
    folder = os.environ.get("SHAREPOINT_FOLDER_PATH", "").strip("/")
    remote_path = "/".join(part for part in (folder, zip_path.name) if part)
    upload_url = (
        f"{GRAPH_ROOT}/sites/{quote(site_id, safe='')}/drives/"
        f"{quote(drive_id, safe='')}/root:/{quote(remote_path, safe='/')}:/content"
    )
    request = Request(upload_url, data=zip_path.read_bytes(), method="PUT")
    request.add_header("Authorization", f"Bearer {get_access_token()}")
    request.add_header("Content-Type", mimetypes.guess_type(zip_path.name)[0] or "application/zip")
    with urlopen(request) as response:
        return json.load(response).get("webUrl", upload_url)


def main() -> None:
    load_env_file(Path(__file__).with_name(".env"))

    if len(sys.argv) == 2:
        zip_path = Path(sys.argv[1])
    elif len(sys.argv) == 1:
        request_id = required_config("VEEVA_REQUEST_ID")
        output_folder = required_config("VEEVA_OUTPUT_FOLDER")
        zip_path = Path(output_folder) / request_id / f"{request_id}_delivery.zip"
    else:
        print("Usage: python sharepoint_upload.py [<zip-file>]")
        raise SystemExit(2)

    try:
        destination = upload_zip(zip_path)
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"SharePoint upload failed ({error.code}): {detail}") from error

    print(f"Uploaded: {zip_path}")
    print(f"SharePoint URL: {destination}")


if __name__ == "__main__":
    main()
