"""Download matching Veeva source versions, annotations, and audit trails, and create an input manifest."""
from __future__ import annotations

import csv
import io
import mimetypes
import os
import re
import ssl
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter

FILENAME_PATTERN = re.compile(r'filename="?([^";]+)"?')
MANIFEST_FIELDS = ["document_number", "document_name", "filename__v", "version", "document_id", "status", "downloaded_file", "error", "annotation_status", "annotation_file", "audit_status", "audit_file"]


def windows_trust_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    for store_name in ("ROOT", "CA"):
        for certificate, encoding, _trust in ssl.enum_certificates(store_name):
            if encoding == "x509_asn":
                context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(certificate))
    return context


class WindowsTrustAdapter(HTTPAdapter):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.ssl_context = windows_trust_context()
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections: int, maxsize: int, block: bool = False, **pool_kwargs: Any) -> None:
        pool_kwargs["ssl_context"] = self.ssl_context
        super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)

    def proxy_manager_for(self, proxy: str, **proxy_kwargs: Any) -> Any:
        proxy_kwargs["ssl_context"] = self.ssl_context
        return super().proxy_manager_for(proxy, **proxy_kwargs)


HTTP = requests.Session()
HTTP.mount("https://", WindowsTrustAdapter())


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ[name.strip()] = value.strip().strip('"').strip("'")


def required_config(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Set a value for {name} in .env")
    return value


def configure_proxy() -> None:
    proxy = os.environ.get("VEEVA_PROXY", "").strip()
    if proxy:
        HTTP.proxies.update({"http": proxy, "https": proxy})
        print(f"Using proxy from VEEVA_PROXY: {urlparse(proxy).hostname}:{urlparse(proxy).port}")
    else:
        print("VEEVA_PROXY not set; connecting without an explicit proxy")


def authenticate(auth_url: str, username: str, password: str) -> tuple[str, str]:
    response = HTTP.post(auth_url, data={"username": username, "password": password}, headers={"Accept": "application/json"}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if payload.get("responseStatus") != "SUCCESS":
        raise RuntimeError(f"Authentication failed: {payload}")
    session_id = payload["sessionId"]
    vault_id = str(payload.get("vaultId", ""))
    vaults = payload.get("vaultIds", [])
    vault = next((item for item in vaults if str(item.get("id")) == vault_id), None)
    if vault is None and len(vaults) == 1:
        vault = vaults[0]
    if not vault or not vault.get("url"):
        raise RuntimeError("Authentication succeeded without a Vault API URL")
    api_root = vault["url"].rstrip("/")
    if not api_root.endswith("/api"):
        api_root += "/api"
    print(f"Authenticated. vaultId={vault_id}; API host={urlparse(api_root).hostname}")
    return session_id, api_root


def api_request(response: requests.Response, context: str) -> dict[str, Any]:
    response.raise_for_status()
    payload = response.json()
    if payload.get("responseStatus") not in {"SUCCESS", "WARNING"}:
        raise RuntimeError(f"{context} failed: {payload.get('errors', payload)}")
    return payload


def fetch_all_pages(first: dict[str, Any], api_root: str, headers: dict[str, str], context: str) -> list[dict[str, Any]]:
    records = list(first.get("data", []))
    next_page = first.get("responseDetails", {}).get("next_page")
    host_root = api_root[:-4] if api_root.endswith("/api") else api_root
    while next_page:
        page = api_request(HTTP.get(f"{host_root}{next_page}", headers=headers, timeout=120), context)
        records.extend(page.get("data", []))
        next_page = page.get("responseDetails", {}).get("next_page")
    return records


def write_file(destination: Path, content: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(destination.name + ".part")
    try:
        partial.write_bytes(content)
        partial.replace(destination)
    except OSError:
        partial.unlink(missing_ok=True)
        raise


def get_metadata(api_root: str, api_version: str, session_id: str, object_name: str = "product__v") -> dict[str, Any]:
    response = HTTP.get(f"{api_root}/{api_version}/metadata/vobjects/{object_name}", headers={"Authorization": session_id, "Accept": "application/json"}, timeout=30)
    payload = api_request(response, "Metadata request")
    print(f"Metadata OK for object: {object_name}")
    return payload


def query_documents(api_root: str, api_version: str, session_id: str, name_contains: str) -> list[dict[str, Any]]:
    escaped_name = name_contains.replace("'", "\\'")
    query = "SELECT id, name__v, filename__v, document_number__v, major_version_number__v, minor_version_number__v " + f"FROM allversions documents WHERE name__v CONTAINS ('{escaped_name}')"
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json", "Authorization": session_id}
    first = api_request(HTTP.post(f"{api_root}/{api_version}/query", data={"q": query}, headers=headers, timeout=30), "Document query")
    records = fetch_all_pages(first, api_root, headers, "Document query page")
    print(f"Query matched {len(records)} document version(s).")
    for row in records[:10]:
        filename = row.get("filename__v") or "(not set)"
        printable = filename.encode("ascii", errors="backslashreplace").decode("ascii")
        print(f"filename__v: {printable}")
    if len(records) > 10:
        print(f"... {len(records) - 10} more filename__v values are in the manifest")
    return records


def download_document_version(api_root: str, api_version: str, session_id: str, document: dict[str, Any], input_folder: Path, verbose: bool = True) -> Path:
    major = document.get("major_version_number__v")
    minor = document.get("minor_version_number__v")
    if major is None or minor is None:
        raise ValueError(f"Missing major/minor version fields for document {document.get('id')}")
    version = f"{major}.{minor}"
    url = f"{api_root}/{api_version}/objects/documents/{document['id']}/versions/{major}/{minor}/file"
    response = HTTP.get(url, headers={"Authorization": session_id}, timeout=120)
    response.raise_for_status()
    if "application/json" in response.headers.get("Content-Type", ""):
        payload = response.json()
        raise RuntimeError(f"Download failed for {document['id']} v{version}: {payload.get('errors', payload)}")
    match = FILENAME_PATTERN.search(response.headers.get("Content-Disposition", ""))
    original_name = Path(match.group(1).strip()).name if match else Path(str(document.get("filename__v") or "")).name
    if not original_name:
        content_type = response.headers.get("Content-Type", "")
        extension = mimetypes.guess_extension(content_type.split(";")[0].strip()) or ".bin"
        original_name = f"{document.get('name__v', document['id'])}{extension}"
    doc_number = str(document.get("document_number__v", document["id"]))
    prefix = f"{doc_number}_v{version}_"
    filename = original_name if original_name.casefold().startswith(prefix.casefold()) else prefix + original_name
    destination = input_folder / doc_number / "Source" / filename
    write_file(destination, response.content)
    printable = str(document.get("filename__v") or "(not set)").encode("ascii", errors="backslashreplace").decode("ascii")
    if verbose:
        print(f"Downloaded {doc_number} v{version}: filename__v={printable}")
    return destination


def annotation_path(input_folder: Path, document: dict[str, Any]) -> Path:
    number = str(document.get("document_number__v", document["id"]))
    version = f"{document['major_version_number__v']}.{document['minor_version_number__v']}"
    return input_folder / number / "Annotations" / f"{number}_v{version}_Annotation.pdf"


def audit_trail_path(input_folder: Path, document: dict[str, Any]) -> Path:
    number = str(document.get("document_number__v", document["id"]))
    return input_folder / number / "Audit_Trail" / f"{number}_audit_trail.csv"


def download_annotations(api_root: str, api_version: str, session_id: str, document: dict[str, Any], input_folder: Path) -> Path:
    major = document.get("major_version_number__v")
    minor = document.get("minor_version_number__v")
    url = f"{api_root}/{api_version}/objects/documents/{document['id']}/versions/{major}/{minor}/annotations/file"
    response = HTTP.get(url, headers={"Authorization": session_id}, timeout=120)
    response.raise_for_status()
    if "application/json" in response.headers.get("Content-Type", ""):
        payload = response.json()
        raise RuntimeError(f"Annotation export failed for {document['id']} v{major}.{minor}: {payload.get('errors', payload)}")
    destination = annotation_path(input_folder, document)
    write_file(destination, response.content)
    return destination


def download_audit_trail(api_root: str, api_version: str, session_id: str, document: dict[str, Any], input_folder: Path) -> Path:
    headers = {"Authorization": session_id, "Accept": "application/json"}
    url = f"{api_root}/{api_version}/objects/documents/{document['id']}/audittrail"
    first = api_request(HTTP.get(url, params={"limit": 1000}, headers=headers, timeout=120), "Audit trail request")
    entries = fetch_all_pages(first, api_root, headers, "Audit trail page")
    fields: list[str] = []
    for entry in entries:
        fields.extend(key for key in entry if key not in fields)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields or ["timestamp", "user_name", "action"])
    writer.writeheader()
    writer.writerows(entries)
    destination = audit_trail_path(input_folder, document)
    write_file(destination, buffer.getvalue().encode("utf-8-sig"))
    return destination


def write_download_manifest(rows: list[dict[str, str]], input_folder: Path) -> None:
    input_folder.mkdir(parents=True, exist_ok=True)
    with (input_folder / "veeva_download_manifest.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Download manifest: {input_folder / 'veeva_download_manifest.csv'}")


def main() -> None:
    load_env_file(Path(__file__).with_name(".env"))
    configure_proxy()
    auth_url = os.environ.get("STAGE_AUTH_URL", "").strip() or required_config("AUTH_URL")
    api_version = os.environ.get("VEEVA_API_VERSION", "v26.2").strip()
    username = required_config("VEEVA_USERNAME")
    password = required_config("VEEVA_PASSWORD")
    input_folder = Path(required_config("VEEVA_INPUT_FOLDER"))
    search = sys.argv[1] if len(sys.argv) == 2 else os.environ.get("VEEVA_DOCUMENT_NAME_CONTAINS", "").strip()
    if not search:
        print('Usage: python veeva_download.py "<document name search text>"')
        raise SystemExit(2)
    session_id, api_root = authenticate(auth_url, username, password)
    get_metadata(api_root, api_version, session_id)
    documents = query_documents(api_root, api_version, session_id, search)
    if not documents:
        print(f"No document versions matched: {search}")
        return
    errors = (requests.RequestException, RuntimeError, ValueError, OSError)
    rows: list[dict[str, str]] = []
    audits: dict[str, tuple[str, str]] = {}
    downloaded = 0
    for document in documents:
        filename_v = str(document.get("filename__v") or "")
        doc_number = str(document.get("document_number__v", ""))
        version = f"{document.get('major_version_number__v')}.{document.get('minor_version_number__v')}"
        row = {"document_number": doc_number, "document_name": str(document.get("name__v", "")), "filename__v": filename_v, "version": version, "document_id": str(document.get("id", "")), "status": "FAILED", "downloaded_file": "", "error": "", "annotation_status": "", "annotation_file": "", "audit_status": "", "audit_file": ""}
        try:
            destination = download_document_version(api_root, api_version, session_id, document, input_folder)
            row["status"] = "DOWNLOADED"
            row["downloaded_file"] = str(destination)
            downloaded += 1
        except errors as error:
            row["error"] = str(error)
            printable = filename_v.encode("ascii", errors="backslashreplace").decode("ascii")
            print(f"Skipped {doc_number} v{version} filename__v={printable or '(not set)'}: {error}")
        try:
            row["annotation_file"] = str(download_annotations(api_root, api_version, session_id, document, input_folder))
            row["annotation_status"] = "DOWNLOADED"
        except errors as error:
            row["annotation_status"] = f"FAILED: {error}"
        if row["document_id"] not in audits:
            try:
                audits[row["document_id"]] = ("DOWNLOADED", str(download_audit_trail(api_root, api_version, session_id, document, input_folder)))
            except errors as error:
                audits[row["document_id"]] = (f"FAILED: {error}", "")
        row["audit_status"], row["audit_file"] = audits[row["document_id"]]
        rows.append(row)
    write_download_manifest(rows, input_folder)
    annotations = sum(row["annotation_status"] == "DOWNLOADED" for row in rows)
    audit_count = sum(status == "DOWNLOADED" for status, _ in audits.values())
    print(f"Finished: {downloaded} downloaded, {len(rows) - downloaded} failed/unavailable out of {len(rows)} versions.")
    print(f"Annotations: {annotations}/{len(rows)} versions; audit trails: {audit_count}/{len(audits)} documents.")


if __name__ == "__main__":
    main()
