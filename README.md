# Veeva Vault End-to-End Document Export Automation

## 1. Purpose

This project automates retrieval and packaging of client-listed Veeva document versions. The workflow authenticates through the configured proxy, reads exact document IDs and major/minor versions from the workbook in `reference/`, downloads available source files, organizes them by document number, writes a manifest and exceptions report, and creates a verified delivery ZIP.

```text
Client version-list workbook
        ↓
Authenticate and download listed source versions
        ↓
Organize files by document number
        ↓
Manifest, tracker, exceptions report, and delivery ZIP
```

The automation reads Vault content only; it does not modify Vault records. Audit trails, PDF annotations, and SharePoint upload remain separate operator-performed steps.

---

## 2. Business process supported

The source process requires the following activities:

1. Create a Veeva report for requested documents.
2. Export source documents for all required major and minor versions.
3. Export audit trails.
4. Export annotations for each document version where available.
5. Organize exported files into folders named for the document number.
6. Rename annotation files using the document number and version number.
7. Prepare the content for delivery to the customer’s designated Teams channel.

The wrapper performs source-version download, local organization, and ZIP packaging from the version list. Vault bulk audit-trail and annotation exports remain user-performed steps when required by the request.

---

## 3. Scope

### Included

- Authenticate to the configured Vault through the configured proxy.
- Read exact document IDs and major/minor versions from the configured client workbook and download source files into document-number folders.
- Write a manifest of downloaded source versions.
- Resume interrupted downloads by reusing completed nonempty source files and checkpointing the manifest.
- Read manual export files from the input folder, including subfolders.
- Detect document numbers such as `DOC123456` and hyphenated Vault document numbers.
- Classify files as **Source**, **Audit_Trail**, or **Annotations**.
- Create one folder per document number.
- Rename annotation files.
- Create a collection tracker CSV.
- Create an exceptions report CSV for files without a document number.
- Create one ZIP package for the processed request.

### Not included

- Automatic Veeva bulk export of audit trails.
- Automatic PDF annotation export.
- Automatic creation of Veeva reports.
- PDF page splitting, OCR, or interpretation of document content.
- Validation that the Veeva export is complete.
- Checksum manifest generation.
- Automatic Microsoft Teams / SharePoint upload.
- Processing files that do not contain an identifiable document number unless manually renamed before execution.

---

## 4. Prerequisites

### Required software

- Windows 10 or Windows 11
- Python 3.10 or later

Check your Python version in PowerShell:

```powershell
python --version
```

The current downloader has been tested with:

```text
Python 3.10.x
```

### Required permissions

- Read access to the manually downloaded Veeva files.
- Write access to your local project folder.
- A Veeva account with API access and permission to retrieve the requested documents.
- Corporate network/proxy access and the corporate proxy root certificate trusted by Windows.

### Python dependencies

The API downloader requires `requests`. The workbook-driven workflow also requires `openpyxl`. Install both with `python -m pip install -r requirements.txt`.

---

## 5. Project files

After extracting this package, keep the following files together:

```text
veeva-vault-automation\
├── run_veeva_workflow.py
├── zip_creator.py
├── veeva_download.py
├── requirements.txt
├── .env
├── reference\ (local client files; not committed)
├── README.md
├── sample_files_note.txt
└── .gitignore
```

| File | Purpose |
|---|---|
| `zip_creator.py` | Main script that organizes files and creates the delivery ZIP. |
| `veeva_download.py` | Authenticates, queries all matching major/minor source versions, and downloads files. |
| `run_veeva_workflow.py` | Runs workbook-driven download, organization, ZIP creation, and integrity validation. |
| `reference/` | Client-supplied workbook listing the exact documents and versions to download. |
| `requirements.txt` | Python dependencies for the downloader and workbook workflow. |
| `.env` | Local credentials, Vault/proxy settings, search text, and paths. It is Git-ignored. |
| `sharepoint_upload.py` | Separate Microsoft Graph uploader for an approved delivery ZIP. |
| `README.md` | This operating guide. |
| `sample_files_note.txt` | Short filename examples. |
| `.gitignore` | Prevents generated `output` content from being added to Git. |

---

## 6. Prepare the local folders

### 6.1 Project folder

The project folder is the repository root:

```text
<project-folder>
```

### 6.2 Input folder

The API downloader writes source files into the configured input folder. Place the audit trail export and annotation PDFs in the same folder before organizing:

```text
input
```

You may use another input-folder path by changing `VEEVA_INPUT_FOLDER` in `.env`.

### 6.3 Output folder

The script creates the output folder automatically. The recommended local output location is:

```text
output
```

The client version-list workbook is kept under `reference/`. The configured input is `reference/US Litigation Activity_test document list_all_versions_repaired.xlsx`; it supplies the exact document IDs and major/minor versions to download.

---

## 7. Manual Veeva preparation

### Configure the end-to-end workflow

Create a local `.env` file. Keep credentials and proxy secrets out of source control:

```text
VEEVA_INPUT_FOLDER=input
VEEVA_REQUEST_ID=LIT-001
VEEVA_OUTPUT_FOLDER=output
VEEVA_VERSION_LIST=reference/<client-version-list.xlsx>
VEEVA_USERNAME=<Veeva username>
VEEVA_PASSWORD=<Veeva password>
AUTH_URL=https://<vault-host>/api/v26.2/auth
VEEVA_API_VERSION=v26.2
VEEVA_PROXY=http://<username>:<password>@<proxy-host>:<port>
```

Use `STAGE_AUTH_URL` instead of `AUTH_URL` when the approved Vault setup requires a separate Stage or discovery authentication URL. Do not set both unless the intended override is clear; `STAGE_AUTH_URL` takes precedence.

Install dependencies and run the full workflow:

```powershell
python -m pip install -r requirements.txt
python run_veeva_workflow.py --clean
```

The wrapper authenticates, validates metadata, downloads each workbook-listed version, checkpoints `veeva_download_manifest.csv`, organizes successful downloads, and creates a delivery ZIP. It uses Windows' trusted root and CA certificates for TLS verification; do not disable certificate verification.

The name-search mode remains available through `veeva_download.py`, but the client-list workflow uses exact document IDs and versions from `VEEVA_VERSION_LIST`.

### Vault API reference

The downloader uses Vault API `v26.2` and sends requests through `VEEVA_PROXY` when configured.

#### 1. Authenticate

```http
POST https://sbbayer-uat.veevavault.com/api/v26.2/auth
Accept: application/json
Content-Type: application/x-www-form-urlencoded

username=<Veeva username>&password=<Veeva password>
```

The response contains `sessionId`, `vaultId`, and `vaultIds[].url`. The downloader does not display or persist the session ID. It selects the API URL for the returned `vaultId` and uses that URL for subsequent requests. This is important because a session authenticated through a discovery or Stage URL may be bound to the Vault API host returned in the authentication response.

#### 2. Validate metadata

```http
GET {vault_api_url}/v26.2/metadata/vobjects/product__v
Authorization: <sessionId>
Accept: application/json
```

The request must return `responseStatus=SUCCESS` before document retrieval continues.

#### 3. Query all document versions

```http
POST {vault_api_url}/v26.2/query
Authorization: <sessionId>
Accept: application/json
Content-Type: application/x-www-form-urlencoded

q=SELECT id, name__v, filename__v, document_number__v,
major_version_number__v, minor_version_number__v
FROM allversions documents
WHERE name__v CONTAINS ('<search text>')
```

The downloader records these fields:

| Field | Use |
|---|---|
| `id` | Document resource identifier for file retrieval. |
| `name__v` | Document name returned by the search. |
| `filename__v` | Original Vault filename used as the local filename fallback. |
| `document_number__v` | Folder and delivery document number. |
| `major_version_number__v` | Major version path component. |
| `minor_version_number__v` | Minor version path component. |

Vault can return `responseStatus=WARNING` with valid data, for example when a duplicate query is detected. The downloader accepts both `SUCCESS` and `WARNING` when data is present.

#### 4. Download a specific version

```http
GET {vault_api_url}/v26.2/objects/documents/{id}/versions/{major}/{minor}/file
Authorization: <sessionId>
```

Binary content is written to:

```text
input/<document_number>/Source/<document_number>_v<major>.<minor>_<filename>
```

JSON responses from this endpoint are treated as Vault errors and recorded in `veeva_download_manifest.csv`. Common causes include missing content files and insufficient `Download Source` permission for the document lifecycle/status.

#### API security and connectivity

- Use a local `.env` file for credentials and proxy settings; never commit it.
- Keep TLS certificate verification enabled.
- The Windows trusted `ROOT` and `CA` certificate stores are loaded for corporate proxy TLS inspection.
- Use a Vault API access token or another approved production authentication method instead of embedding passwords in scheduled jobs.
- Do not include session IDs, passwords, proxy credentials, or API tokens in logs, screenshots, manifests, or support tickets.

### Manual audit trail and annotation export

Before running `zip_creator.py`, complete these Vault steps:

1. Create or open the requested document report and enter each requested document name individually.
2. Confirm the requested document numbers.
3. Select all requested documents with the bulk action and choose **Document Export**.
4. Choose **Source Documents** for all major and minor versions and **Audit Trails**, then select the requested document naming rule.
5. Finish the export and download the ZIP from the Vault notification.
6. For every document and every major/minor version, open the version and export its PDF annotations individually.
7. Rename each annotation `<Document Number>_v<Version Number>_Annotation.pdf`.
8. Extract the bulk export and place it, plus annotation PDFs, under the input folder.

The organizer expects individual files in the input folder. If Veeva gives you a ZIP file, manually extract that ZIP into:

```text
C:\Users\EFDDQ\Downloads\Veeva_Export
```

The script scans all subfolders inside the input folder.

---

## 8. Filename requirements

### 8.1 Document number

Each file should contain its document number in the filename using this pattern:

```text
DOC followed by digits
```

Examples:

```text
DOC123456_v1.0_source.pdf
DOC123456_v1.0_annotation.pdf
DOC123456_v1.0_audit.csv
DOC234567_v2.1_source.msg
```

The organizer recognizes `DOC123456` and hyphenated Veeva document numbers such as `PP-QLA-CR-0004`.

### 8.2 Version number

For an annotation, include the version where possible:

```text
DOC123456_v2.1_annotation.pdf
```

The script looks for a version in this form:

```text
v1.0
v2.1
v3_0
```

An underscore in a version is converted to a decimal point. For example:

```text
v2_1 → v2.1
```

If no version is found in an annotation filename, the script uses `UNKNOWN`:

```text
DOC123456_vUNKNOWN_Annotation.pdf
```

Review such files manually before delivery.

---

## 9. File classification rules

The script classifies each file using its filename.

| Filename contains | Target folder | Example |
|---|---|---|
| `annotation` | `Annotations` | `DOC123456_v1.0_annotation.pdf` |
| `audit` or `trail` | `Audit_Trail` | `DOC123456_v1.0_audit.csv` |
| Any other filename with a document number | `Source` | `DOC123456_v1.0_source.pdf` |

Classification is case-insensitive. For example, `ANNOTATION`, `Annotation`, and `annotation` are treated the same way.

---

## 10. Annotation naming rule

The source process requires this naming convention:

```text
<Document Number>_v<Version Number>_Annotation.<extension>
```

Example input:

```text
DOC123456_v2.1_annotation.pdf
```

Example output:

```text
DOC123456_v2.1_Annotation.pdf
```

The original file extension is retained. This allows the script to work with PDF, TXT, or another manually exported annotation format.

---

## 11. End-to-end execution

Run these steps in **PowerShell** from the project folder. The downloader reads credentials and paths from `.env`; keep that file local and never paste its secrets into commands or logs.

### 11.0 Quick start (execution steps)

1. Open PowerShell in the project folder and create/activate the virtual environment:

   ```powershell
   cd <project-folder>\automation\veeva-vault-poc
   python -m venv .venv
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
   .\.venv\Scripts\Activate.ps1
   ```

2. Create `.env` as shown in section 7 (including `VEEVA_PROXY`) and place the client workbook under `reference/`.

3. Install dependencies through the corporate proxy. The proxy is read from `.env` so the credentials are not typed or echoed:

   ```powershell
   $px = ((Select-String -Path .env -Pattern '^VEEVA_PROXY=(.+)$').Matches[0].Groups[1].Value).Trim()
   python -m pip install --isolated --proxy $px -r requirements.txt
   Remove-Variable px
   ```

   `--isolated` ignores a global `pip.ini`; use it if pip fails with `Failed to parse: http://[user:passwd@]proxy.server:port`.

4. Check free disk space, then run a smoke test with the first 10 workbook rows:

   ```powershell
   [math]::Round((Get-PSDrive C).Free/1GB,2)
   python run_veeva_workflow.py --clean --start-index 1 --end-index 10
   ```

   Expected: `Authenticated`, `Metadata OK`, per-row `FAILED` lines only for Vault content/permission errors, and `ZIP integrity: OK`. The exit code is `1` whenever fewer than all workbook rows are downloaded, so a partial batch returns `1` even when it worked.

5. Run the full list (in one go or in batches, see 11.1), then review `input/veeva_download_manifest.csv`, `output/<request-id>/collection_tracker.csv`, and `output/<request-id>/exceptions_report.csv`.

6. Deliver `output/<request-id>/<request-id>_delivery.zip` after review (optionally with `sharepoint_upload.py`).

Common download failures recorded in the manifest:

| Vault message | Meaning |
|---|---|
| `INVALID_DATA: Content file does not exist` | The version has no source file in Vault. |
| `INSUFFICIENT_ACCESS: Not authorized for permission [Download Source]` | The account lacks Download Source permission for that lifecycle/status (for example, Expired). |

### 11.1 Prepare and download source versions

Set these values in `.env` before starting:

```text
VEEVA_INPUT_FOLDER=input
VEEVA_REQUEST_ID=LIT-001
VEEVA_OUTPUT_FOLDER=output
VEEVA_VERSION_LIST=reference/US Litigation Activity_test document list_all_versions_repaired.xlsx
VEEVA_USERNAME=<Veeva username>
VEEVA_PASSWORD=<Veeva password>
VEEVA_DOCUMENT_NAME_CONTAINS=<narrow document name search text>
AUTH_URL=https://<vault-host>/api/v26.2/auth
VEEVA_API_VERSION=v26.2
```

Install dependencies once. For a client-supplied version list, run the end-to-end wrapper from PowerShell:

```powershell
python -m pip install -r requirements.txt
python run_veeva_workflow.py --clean
```

The wrapper authenticates through `VEEVA_PROXY`, reads each version from `VEEVA_VERSION_LIST`, downloads its source into `input/<document-number>/Source/`, checkpoints `input/veeva_download_manifest.csv` every 25 rows, organizes the files, creates `output/<request-id>/<request-id>_delivery.zip`, and checks ZIP integrity. It writes source files directly into the ZIP rather than making another full copy under `output/`.

`--clean` clears only the configured project input/output contents before running; it refuses to clean paths outside the project folder. If a run is interrupted, rerun without `--clean`: the wrapper skips nonempty files already downloaded and continues the version list. For a long list, process bounded batches and package on the final batch:

```powershell
python run_veeva_workflow.py --clean --start-index 1 --end-index 100 --no-package
python run_veeva_workflow.py --start-index 101 --end-index 200 --no-package
python run_veeva_workflow.py --start-index 201 --end-index 300 --no-package
python run_veeva_workflow.py --start-index 301 --end-index 400 --no-package
python run_veeva_workflow.py --start-index 401 --end-index 500 --no-package
python run_veeva_workflow.py --start-index 501 --end-index 545
```

Vault content or permission failures stay in the manifest, and a local storage error stops further downloads while retaining completed files for packaging. Review the manifest and output reports before delivery. `input/`, `output/`, `reference/`, `.env`, and `.venv/` are local-only and excluded from Git; keep client workbooks and downloaded files out of commits.

To download without cleaning existing input/output contents, omit `--clean`. A document-name search remains available as a separate downloader mode:

```powershell
python veeva_download.py "narrow document name search"
```

Do not use a broad search such as `Test` for a client delivery; it can match hundreds of versions.

### 11.2 Add audit trails and annotations

The downloader does not export audit trails or annotations. Complete the manual Vault export steps in section 7, extract the bulk export, and place the resulting files and annotation PDFs under the same input folder. Include document numbers and version identifiers in filenames as described in sections 8 and 10.

### 11.3 Organize files and create the ZIP

Set a unique `VEEVA_REQUEST_ID` in `.env` for this delivery, then run:

```powershell
python zip_creator.py
```

Alternatively, pass the input folder, request ID, and output folder explicitly:

```powershell
python zip_creator.py `
        "C:\Users\<user>\Documents\veeva\input" `
        "LIT-001" `
        "output"
```

The organizer copies files into `output\\<request-id>`, writes `collection_tracker.csv` and `exceptions_report.csv`, and creates `<request-id>_delivery.zip`. It does not delete or modify the source files. Use a new request ID for each run so an earlier delivery is not mixed with a rerun.

Review the tracker and exceptions report, then verify the ZIP can be read:

```powershell
python -c "import zipfile; p=r'output\\LIT-001\\LIT-001_delivery.zip'; z=zipfile.ZipFile(p); print('ZIP OK' if z.testzip() is None else 'ZIP CORRUPT')"
```

Replace `LIT-001` in the verification command with the request ID used for this run. Review the ZIP contents and resolve exceptions before delivery.

### Upload the ZIP to Teams-connected SharePoint

The upload is optional and separate from the end-to-end local packaging steps above. Only proceed after reviewing and approving the ZIP. Add these settings to the local `.env` file:

```text
AZURE_TENANT_ID=<Microsoft Entra tenant ID>
AZURE_CLIENT_ID=<app registration client ID>
AZURE_CLIENT_SECRET=<app registration client secret>
SHAREPOINT_SITE_ID=<SharePoint site ID>
SHAREPOINT_DRIVE_ID=<document library drive ID>
SHAREPOINT_FOLDER_PATH=Approved/Veeva Deliveries
```

The app registration must have approved Microsoft Graph application permission `Files.ReadWrite.All` (or a more restricted approved permission) with admin consent. Upload the ZIP generated by the `.env` configuration:

```powershell
python sharepoint_upload.py
```

Or upload a specific ZIP:

```powershell
python sharepoint_upload.py "output\LIT-001\LIT-001_delivery.zip"
```

The uploader uses the SharePoint document library associated with the configured site and drive. It does not upload to a Teams chat directly; files in the channel's SharePoint folder appear in the Teams channel.

### Command parameters

| Parameter | Example | Meaning |
|---|---|---|
| Input folder | `input` | API source downloads plus manually exported audit and annotation files. |
| Request ID | `LIT-001` | Identifier for this litigation collection or delivery run. |
| Output folder | `output` | Local root folder where the script creates results. |

Use a unique request ID for each collection, for example:

```text
LIT-001
LIT-2026-09-21
DR-SCHOLLS-REQUEST-01
```

---

## 12. Expected output

For request ID `LIT-001`, the result is created here:

```text
output\LIT-001
```

Example structure:

```text
output\LIT-001\
├── veeva_download_manifest.csv (in the input folder before organization)
├── DOC123456\
│   ├── Source\
│   │   └── DOC123456_v1.0_source.pdf
│   ├── Audit_Trail\
│   │   └── DOC123456_v1.0_audit.csv
│   └── Annotations\
│       └── DOC123456_v1.0_Annotation.pdf
├── DOC234567\
│   └── Source\
│       └── DOC234567_v2.1_source.msg
├── Unmatched\
│   └── file_without_document_number.pdf
├── collection_tracker.csv
├── exceptions_report.csv
└── LIT-001_delivery.zip
```

---

## 13. Output files explained

### 13.1 Document folders

Each identified document number gets one folder:

```text
DOC123456\
```

The script creates the applicable subfolders as it finds files:

```text
Source\
Audit_Trail\
Annotations\
```

### 13.2 `collection_tracker.csv`

This file records successfully classified files.

Columns:

| Column | Meaning |
|---|---|
| `document_number` | Document number detected in the filename. |
| `version` | Version detected in the filename or `UNKNOWN`. |
| `category` | `Source`, `Audit_Trail`, or `Annotations`. |
| `source_file` | Original local file path. |
| `output_file` | New organized local file path. |

Open it in Excel to review the collection result.

`veeva_download_manifest.csv` is created by `veeva_download.py` in the input folder. It records each downloaded document number, version, Vault document ID, and source-file path.

### 13.3 `exceptions_report.csv`

This file records files that could not be matched to a document number.

Example reason:

```text
Document number not found in filename
```

Correct those filenames manually, then rerun the script using a new request ID or remove the prior output folder first.

### 13.4 `Unmatched` folder

Files without a document number are copied to this folder. They are not deleted or ignored.

### 13.5 Delivery ZIP

The final ZIP is created here:

```text
output\LIT-001\LIT-001_delivery.zip
```

It contains document folders, the tracker, and the exceptions report. Review the output before manually uploading the ZIP or its contents to the required customer Teams/SharePoint location.

---

## 14. Example end-to-end run

### Input files

```text
C:\Users\EFDDQ\Downloads\Veeva_Export\DOC123456_v1.0_source.pdf
C:\Users\EFDDQ\Downloads\Veeva_Export\DOC123456_v1.0_annotation.pdf
C:\Users\EFDDQ\Downloads\Veeva_Export\DOC123456_v1.0_audit.csv
C:\Users\EFDDQ\Downloads\Veeva_Export\DOC234567_v2.1_source.pdf
C:\Users\EFDDQ\Downloads\Veeva_Export\notes.txt
```

### Command

```powershell
python zip_creator.py `
  "C:\Users\EFDDQ\Downloads\Veeva_Export" `
  "LIT-DEMO" `
  "output"
```

### Result

```text
output\LIT-DEMO\DOC123456\Source\DOC123456_v1.0_source.pdf
output\LIT-DEMO\DOC123456\Audit_Trail\DOC123456_v1.0_audit.csv
output\LIT-DEMO\DOC123456\Annotations\DOC123456_v1.0_Annotation.pdf
output\LIT-DEMO\DOC234567\Source\DOC234567_v2.1_source.pdf
output\LIT-DEMO\Unmatched\notes.txt
output\LIT-DEMO\collection_tracker.csv
output\LIT-DEMO\exceptions_report.csv
output\LIT-DEMO\LIT-DEMO_delivery.zip
```

---

## 15. Troubleshooting

### Error: `python is not recognized`

Python is not installed or is not available in the Windows PATH.

Actions:

1. Install Python 3.10 or later.
2. During installation, select **Add Python to PATH**.
3. Close and reopen PowerShell.
4. Run:

```powershell
python --version
```

### Error: `Input folder does not exist`

The input-folder path passed to the script is not correct.

Actions:

1. Confirm the folder exists in File Explorer.
2. Copy the path from File Explorer.
3. Put the path in double quotes in PowerShell.

### File is in `Unmatched`

The filename does not contain a recognized `DOC` plus digits or hyphenated Veeva document number.

Action: Rename the source file before running the script, for example:

```text
old_file_name.pdf
```

to:

```text
DOC123456_v1.0_source.pdf
```

### Annotation is named `vUNKNOWN`

The filename did not contain a detectable version.

Action: Rename the original file before running the script, for example:

```text
DOC123456_annotation.pdf
```

to:

```text
DOC123456_v2.1_annotation.pdf
```

### Existing output must be replaced

The workflow replaces the delivery ZIP when the same request ID is reused. Use a new request ID to preserve earlier deliveries. To discard the current working set before a fresh run, use `--clean` after confirming the configured input and output folders can be removed:

```powershell
python run_veeva_workflow.py --clean
```

---

## 16. Validation before delivery

Before manually uploading the final package to Teams/SharePoint, complete this checklist:

- [ ] Requested document numbers are present.
- [ ] Required source documents and versions are present.
- [ ] Audit trails are present where required.
- [ ] Required annotations are present.
- [ ] Annotation names use the required document/version format.
- [ ] `exceptions_report.csv` is reviewed and resolved or accepted.
- [ ] `collection_tracker.csv` is reviewed.
- [ ] The delivery ZIP opens successfully.
- [ ] The output is uploaded only to the approved customer destination.

---

## 17. Security and handling guidance

- Do not store Veeva passwords, session cookies, or API tokens in this project.
- Treat manually exported litigation content according to applicable Bayer access, retention, and information-handling requirements.
- Keep the input folder and output folder in approved local/network locations.
- Review the delivery package before transferring it to Teams/SharePoint.
- Do not share the output ZIP through unapproved channels.

---

## 18. Operator-performed steps

The automation does not export audit trails or annotations and does not upload to SharePoint. Complete those tasks manually when required, then review the manifest, tracker, exceptions report, and ZIP before delivery.

---

## 19. Summary

The end-to-end automation retrieves the source versions listed by the client and prepares a local delivery package. Audit trails, annotations, and final transfer remain under operator control:

```text
Read the client version list and download source versions
        ↓
Optionally export audit trails and annotations manually
        ↓
Organize input files and build a verified ZIP
        ↓
Review tracker and exceptions
        ↓
Use the delivery ZIP for approved manual Teams/SharePoint delivery
```
