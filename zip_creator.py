"""Organize Veeva export files and create a delivery ZIP."""
from __future__ import annotations

import csv
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path

DOCUMENT_PATTERN = re.compile(r"^(?:DOC\d+|[A-Z0-9]+(?:[_-]+[A-Z0-9]+)+?)(?=_v\d|$|[ .])", re.IGNORECASE)
VERSION_PATTERN = re.compile(r"(?:^|[_ .-])v(\d+\.\d+(?:\.\d+)*)", re.IGNORECASE)
# Folders written by veeva_download.py: input/<document number>/<category>/
CATEGORIES = {"Source", "Audit_Trail", "Annotations"}


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def category_for(filename: str) -> str:
    name = filename.lower()
    if "annotation" in name:
        return "Annotations"
    if "audit" in name or "trail" in name:
        return "Audit_Trail"
    return "Source"


def manifest_exceptions(manifest: Path) -> list[dict[str, str]]:
    exceptions: list[dict[str, str]] = []
    audited: set[str] = set()
    with manifest.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            label = f"{row['document_number']} v{row['version']}"
            if row.get("status") != "DOWNLOADED":
                exceptions.append({"file": f"{label} Source", "reason": row.get("error") or row.get("status") or "Not downloaded"})
            annotation = row.get("annotation_status") or ""
            if annotation and annotation != "DOWNLOADED":
                exceptions.append({"file": f"{label} Annotation", "reason": annotation})
            audit = row.get("audit_status") or ""
            if audit and audit != "DOWNLOADED" and row["document_number"] not in audited:
                audited.add(row["document_number"])
                exceptions.append({"file": f"{row['document_number']} Audit Trail", "reason": audit})
    return exceptions


def process(input_folder: Path, request_id: str, output_root: Path, copy_files: bool = True) -> Path:
    if not input_folder.is_dir():
        raise FileNotFoundError(f"Input folder does not exist: {input_folder}")
    delivery_root = output_root / request_id
    rows: list[dict[str, str]] = []
    unmatched: list[dict[str, str]] = []
    archive_sources: list[tuple[Path, Path]] = []
    for source in input_folder.rglob("*"):
        if not source.is_file() or source.name == "veeva_download_manifest.csv" or source.name.endswith(".part"):
            continue
        category = source.parent.name
        if category in CATEGORIES and source.parent.parent.parent == input_folder:
            document_number = source.parent.parent.name
        else:
            doc_match = DOCUMENT_PATTERN.search(source.name)
            document_number = doc_match.group(0) if doc_match else ""
            category = category_for(source.name)
        if not document_number:
            relative_target = Path("Unmatched") / source.name
            target = delivery_root / relative_target
            if copy_files:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            archive_sources.append((source, relative_target))
            unmatched.append({"file": source.name, "reason": "Document number not found in filename"})
            continue
        version_match = VERSION_PATTERN.search(source.name)
        version = version_match.group(1).replace("_", ".") if version_match else ("ALL" if category == "Audit_Trail" else "UNKNOWN")
        target_name = f"{document_number}_v{version}_Annotation{source.suffix}" if category == "Annotations" else source.name
        relative_target = Path(document_number) / category / target_name
        target = delivery_root / relative_target
        if copy_files:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        archive_sources.append((source, relative_target))
        rows.append({"document_number": document_number, "version": version, "category": category, "source_file": str(source), "output_file": str(target)})

    delivery_root.mkdir(parents=True, exist_ok=True)
    manifest = input_folder / "veeva_download_manifest.csv"
    if manifest.is_file():
        unmatched.extend(manifest_exceptions(manifest))
        if copy_files:
            shutil.copy2(manifest, delivery_root / manifest.name)
        else:
            archive_sources.append((manifest, Path(manifest.name)))
    with (delivery_root / "collection_tracker.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["document_number", "version", "category", "source_file", "output_file"])
        writer.writeheader()
        writer.writerows(rows)
    with (delivery_root / "exceptions_report.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["file", "reason"])
        writer.writeheader()
        writer.writerows(unmatched)

    zip_path = delivery_root / f"{request_id}_delivery.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        if copy_files:
            files = [(file, file.relative_to(delivery_root)) for file in delivery_root.rglob("*") if file.is_file() and file != zip_path]
        else:
            files = archive_sources + [
                (delivery_root / "collection_tracker.csv", Path("collection_tracker.csv")),
                (delivery_root / "exceptions_report.csv", Path("exceptions_report.csv")),
            ]
        for source, archive_name in files:
            archive.write(source, archive_name)
    return delivery_root


def main() -> None:
    load_env_file(Path(__file__).with_name(".env"))
    if len(sys.argv) == 1:
        input_folder = os.environ.get("VEEVA_INPUT_FOLDER")
        request_id = os.environ.get("VEEVA_REQUEST_ID")
        output_folder = os.environ.get("VEEVA_OUTPUT_FOLDER")
    elif len(sys.argv) == 4:
        input_folder, request_id, output_folder = sys.argv[1:]
    else:
        print("Usage: python zip_creator.py [<input-folder> <request-id> <output-folder>]")
        raise SystemExit(2)
    if not input_folder or not request_id or not output_folder:
        print("Set VEEVA_INPUT_FOLDER, VEEVA_REQUEST_ID, and VEEVA_OUTPUT_FOLDER in .env.")
        raise SystemExit(2)
    output = process(Path(input_folder), request_id, Path(output_folder))
    print(f"Completed. Review: {output}")
    print(f"Delivery ZIP: {output / (request_id + '_delivery.zip')}")


if __name__ == "__main__":
    main()
