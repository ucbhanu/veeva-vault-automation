# Veeva Vault End-to-End Document Export Automation

## 1. Purpose

This project automates retrieval and packaging of client-listed Veeva document versions. The workflow authenticates through the configured proxy, reads exact document IDs and major/minor versions from the workbook in `reference/`, downloads each version's source file, annotation PDF, and audit trail PDF, organizes them by document number, writes a manifest and exceptions report, and creates a verified delivery folder (no ZIP).

```text
Client version-list workbook
        ↓
Authenticate and download source, annotations, and audit trails
        ↓
Organize files by document number
        ↓
Manifest, tracker, exceptions report, and delivery folder
```

The automation reads Vault content only; it does not modify Vault records. After the delivery folder passes its copy check, the workflow uploads it to SharePoint using `SHAREPOINT_UPLOAD_METHOD` from `.env` (`graph`, `sync`, or `none`).

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

The wrapper performs steps 2–6 through the Vault API from the version list, then packages the result. Creating the Veeva report and the final Teams delivery remain user-performed steps.

---

## 3. Scope

### Included

- Authenticate to the configured Vault through the configured proxy.
- Read exact document IDs and major/minor versions from the configured client workbook and download source files into document-number folders.
- Export each listed version's annotations as `<Document Number>_v<Version>_Annotation.pdf`.
- Export each listed version's audit trail as `<Document Number>_v<Version>_audit_trail.pdf` (the document history is fetched once and filtered to that version's events).
- Write a manifest of source, annotation, and audit-trail results per version.
- Resume interrupted downloads by reusing completed nonempty files and checkpointing the manifest.
- Read additional manually exported files from the input folder, including subfolders.
- Detect document numbers such as `DOC123456` and hyphenated Vault document numbers.
- Classify files as **Source**, **Audit_Trail**, or **Annotations**.
- Create one folder per document number containing that document's source, annotation, and audit trail files.
- Rename annotation files.
- Create a collection tracker CSV.
- Create an exceptions report CSV for files without a document number and for every source file, annotation, or audit trail that could not be downloaded.
- Create one delivery folder for the processed request, including the download manifest. No ZIP is created.
- Upload that delivery folder (`output\<request-id>`) to the configured SharePoint folder.

### Not included

- Automatic creation of Veeva reports.
- PDF page splitting, OCR, or interpretation of document content.
- Validation that a downloaded annotation PDF actually contains annotations (Vault returns the viewable rendition with any annotations applied).
- Checksum manifest generation.
- Uploading to a Teams chat (files go to the channel's SharePoint folder).
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

- Write access to your local project folder.
- A Veeva account with API access and permission to download source, export annotations, and read audit trails for the requested documents (for example, Download Source for each lifecycle/status in scope).
- Corporate network/proxy access and the corporate proxy root certificate trusted by Windows.

### Python dependencies

The API downloader requires `requests`; audit trail PDFs are generated with `fpdf2` (using the Windows Arial font when available). The workbook-driven workflow also requires `openpyxl`. The SharePoint Graph upload requires `msal[broker]` (Microsoft sign-in through the Windows account broker). Install all with `python -m pip install -r requirements.txt` (through the proxy, see section 11.0).

---

## 5. Project files

After extracting this package, keep the following files together:

```text
veeva-vault-automation\
├── run_veeva_workflow.py
├── zip_creator.py
├── veeva_download.py
├── sharepoint_upload.py
├── requirements.txt
├── .env.example
├── .env (local; not committed)
├── reference\ (local client files; not committed)
├── README.md
├── sample_files_note.txt
└── .gitignore
```

| File | Purpose |
|---|---|
| `zip_creator.py` | Organizes files into the delivery folder (the name is historical; it no longer creates a ZIP). |
| `veeva_download.py` | Authenticates, downloads source versions, annotation PDFs, and audit trails. |
| `run_veeva_workflow.py` | Runs workbook-driven download, organization into the delivery folder, copy verification, and the SharePoint upload. |
| `reference/` | Client-supplied workbook listing the exact documents and versions to download. |
| `requirements.txt` | Python dependencies for the downloader, workbook workflow, and SharePoint upload. |
| `.env.example` | Template for `.env` with every setting and placeholder values. |
| `.env` | Local credentials, Vault/proxy/SharePoint settings, and paths. It is Git-ignored. |
| `sharepoint_upload.py` | Uploads the delivery folder to SharePoint (Microsoft Graph or OneDrive-synced folder); called by the workflow and usable on its own. |
| `README.md` | This operating guide. |
| `sample_files_note.txt` | Short filename examples. |
| `.gitignore` | Keeps `.env`, the sign-in token cache, `input`, `output`, and `reference` out of Git. |

---

## 6. Prepare the local folders

### 6.1 Project folder

The project folder is the repository root:

```text
<project-folder>
```

### 6.2 Input folder

The API downloader writes source files, annotation PDFs, and audit trails into the configured input folder as `input/<document-number>/{Source,Annotations,Audit_Trail}/`. Any additional manually exported files may be placed in the same folder before organizing:

```text
input
```

You may use another input-folder path by changing `VEEVA_INPUT_FOLDER` in `.env`.

### 6.3 Output folder

The script creates the output folder automatically. The recommended local output location is:

```text
output
```

The client version-list workbook is kept under `reference/`. `VEEVA_VERSION_LIST` selects the workbook; it supplies the exact document IDs and major/minor versions to download. For testing, use a small workbook (for example, 10 versions) rather than the full client list.

---

## 7. Configuration and Vault API

### Configure the end-to-end workflow

Copy `.env.example` to `.env` and fill in the values. Keep credentials and proxy secrets out of source control:

```text
# Veeva Vault credentials
VEEVA_USERNAME=<Veeva username>
VEEVA_PASSWORD=<Veeva password>

# Reference details (use a new VEEVA_REQUEST_ID per run)
VEEVA_INPUT_FOLDER=input
VEEVA_REQUEST_ID=CLIENT-LIST-YYYY-MM-DD
VEEVA_OUTPUT_FOLDER=output
VEEVA_VERSION_LIST=reference/<client-version-list.xlsx>

# Veeva Vault authentication details
AUTH_URL=https://bayer-content-factory.veevavault.com/api/v26.2/auth
#AUTH_URL=https://sbbayer-uat.veevavault.com/api/v26.2/auth
VEEVA_API_VERSION=v26.2

# Proxy details
VEEVA_PROXY=http://<username>:<password>@<proxy-host>:<port>

# SharePoint details
SHAREPOINT_UPLOAD_METHOD=graph          # graph, sync, or none
SHAREPOINT_SYNC_FOLDER=<OneDrive shortcut path>   # sync only
SHAREPOINT_SHARE_URL=<"Copy link" URL of the target SharePoint folder>
SHAREPOINT_AUTH=user
SHAREPOINT_LOGIN=broker
SHAREPOINT_LOGIN_HINT=<your company e-mail>
SHAREPOINT_USE_PROXY=true
```

`AUTH_URL` selects the Vault: production (`bayer-content-factory`) or UAT (`sbbayer-uat`). Keep the other one commented out. UAT needs an account with UAT access.

If the user has no access to the `AUTH_URL` Vault, Vault silently signs in to the user's default Vault instead. The downloader stops in that case and lists the Vaults available to the user. To use a listed Vault deliberately (for example when signing in through a discovery host), set `VEEVA_VAULT_ID=<id>`.

Install dependencies and run the full workflow:

```powershell
python -m pip install -r requirements.txt
python run_veeva_workflow.py --clean                     # download, build delivery, upload per SHAREPOINT_UPLOAD_METHOD
python run_veeva_workflow.py --clean --upload none       # one-off override: graph, sync, or none
python run_veeva_workflow.py --clean --upload-no-proxy   # one-off override of SHAREPOINT_USE_PROXY for Graph
```

The workflow uploads only the folder it generated (`output\<request-id>`), and only after it passes its copy check. Use a new `VEEVA_REQUEST_ID` for each run; an existing folder with the same name in SharePoint is never overwritten. See [Upload to Teams-connected SharePoint](#upload-to-teams-connected-sharepoint) for the settings.

The wrapper authenticates, validates metadata, downloads each workbook-listed version's source and annotation PDF and each document's audit trail, checkpoints `veeva_download_manifest.csv`, organizes the files, and creates the delivery folder. It uses Windows' trusted root and CA certificates for TLS verification; do not disable certificate verification.

The name-search mode remains available through `veeva_download.py`, but the client-list workflow uses exact document IDs and versions from `VEEVA_VERSION_LIST`.

### Vault API reference

The downloader uses Vault API `v26.2` and sends requests through `VEEVA_PROXY` when configured. At startup it prints `Using proxy from VEEVA_PROXY: <host>:<port>` (credentials are never printed).

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

#### 5. Export version annotations

```http
GET {vault_api_url}/v26.2/objects/documents/{id}/versions/{major}/{minor}/annotations/file
Authorization: <sessionId>
```

The PDF is written to:

```text
input/<document_number>/Annotations/<document_number>_v<major>.<minor>_Annotation.pdf
```

A version without a viewable rendition returns `INVALID_DATA: Cannot find rendition [viewable_rendition__v]`; this is recorded in the manifest and exceptions report.

#### 6. Export document audit trail

```http
GET {vault_api_url}/v26.2/objects/documents/{id}/audittrail?limit=1000
Authorization: <sessionId>
Accept: application/json
```

All pages are followed through `responseDetails.next_page`. The history is fetched once per document, filtered by each event's `version`, sorted by timestamp, and written per version as a PDF (timestamp, user, action, description, field, old and new value):

```text
input/<document_number>/Audit_Trail/<document_number>_v<major>.<minor>_audit_trail.pdf
```

#### API security and connectivity

- Use a local `.env` file for credentials and proxy settings; never commit it.
- Keep TLS certificate verification enabled.
- The Windows trusted `ROOT` and `CA` certificate stores are loaded for corporate proxy TLS inspection.
- Use a Vault API access token or another approved production authentication method instead of embedding passwords in scheduled jobs.
- Do not include session IDs, passwords, proxy credentials, or API tokens in logs, screenshots, manifests, or support tickets.

### Optional: manual Vault export

The workflow downloads source files, annotations, and audit trails automatically. Use these UI steps only as a fallback (for example, for versions the API account cannot access) and place the results under the input folder before running `zip_creator.py`:

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

   Expected: `Authenticated`, `Metadata OK`, per-row `FAILED` lines only for Vault content/permission errors, `Delivery check: OK`, and a `SharePoint (graph): <url>` line. The first Graph upload opens a Microsoft sign-in window; later runs reuse the cached sign-in. The exit code is `1` whenever fewer than all workbook rows are downloaded, so a partial batch returns `1` even when it worked.

5. Run the full list (in one go or in batches, see 11.1), then review `input/veeva_download_manifest.csv`, `output/<request-id>/collection_tracker.csv`, and `output/<request-id>/exceptions_report.csv`.

6. Check the uploaded `<request-id>` folder in SharePoint (the workflow uploads it automatically per `SHAREPOINT_UPLOAD_METHOD`).

Common download failures recorded in the manifest:

| Vault message | Meaning |
|---|---|
| `INVALID_DATA: Content file does not exist` | The version has no source file in Vault. |
| `INSUFFICIENT_ACCESS: Not authorized for permission [Download Source]` | The account lacks Download Source permission for that lifecycle/status (for example, Expired). |
| `INVALID_DATA: Cannot find rendition [viewable_rendition__v]` | No viewable rendition exists, so annotations cannot be exported for that version. |
| `INVALID_DOCUMENT` | The document ID is not visible to the account or no longer exists. |

### 11.1 Download source, annotations, and audit trails

Set the values from section 7 in `.env` before starting (`VEEVA_DOCUMENT_NAME_CONTAINS` is only needed for the standalone name-search mode).

Install dependencies once. For a client-supplied version list, run the end-to-end wrapper from PowerShell:

```powershell
python -m pip install -r requirements.txt
python run_veeva_workflow.py --clean
```

The wrapper authenticates through `VEEVA_PROXY`, reads each version from `VEEVA_VERSION_LIST`, downloads its source into `input/<document-number>/Source/`, its annotation PDF into `input/<document-number>/Annotations/`, and the version's audit trail PDF into `input/<document-number>/Audit_Trail/`. It checkpoints `input/veeva_download_manifest.csv` every 25 processed rows, organizes the files into `output/<request-id>/<document-number>/`, verifies that every copied file exists with the same size as its source, and then uploads `output/<request-id>/` to SharePoint per `SHAREPOINT_UPLOAD_METHOD`. With `--no-package`, nothing is organized or uploaded. No ZIP is created. Close the manifest in Excel before running; an open file blocks the checkpoint.

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

### 11.2 Review missing audit trails and annotations

Annotations and audit trails are downloaded automatically. Anything Vault could not return is listed in `exceptions_report.csv` and in the manifest's `annotation_status` / `audit_status` columns. Export those items manually if required (see "Optional: manual Vault export" in section 7) and place them under the input folder using the filename rules in sections 8 and 10, then rerun without `--clean`.

### 11.3 Organize files into the delivery folder

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

The organizer copies files into `output\\<request-id>`, writes `collection_tracker.csv` and `exceptions_report.csv`, and copies the download manifest. It does not create a ZIP and does not delete or modify the source files. Use a new request ID for each run (or `--clean`) so an earlier delivery is not mixed with a rerun.

Review the tracker and exceptions report and the document folders before delivery.

### Upload to Teams-connected SharePoint

The workflow calls `sharepoint_upload.py` automatically after the delivery check. Run it on its own to upload `output\<request-id>` (or a file/folder passed as an argument) again, for example after an upload error. It never overwrites: if a folder with the same name already exists at the destination, it stops. Files placed in a Teams channel's SharePoint folder appear in the channel's Files tab.

The upload mode is set in `.env`; command-line options only override it for one run:

| Setting | Values | Meaning |
|---|---|---|
| `SHAREPOINT_UPLOAD_METHOD` | `graph` / `sync` / `none` | Microsoft Graph upload / copy into the OneDrive-synced folder / no upload. Required. |
| `SHAREPOINT_USE_PROXY` | `true` (default) / `false` | `graph` only: route Microsoft Graph calls through `VEEVA_PROXY`. |
| `SHAREPOINT_AUTH` | `user` (default) / `app` | `graph` only: your own sign-in (Method 2) or app registration (Method 3). |

```powershell
python sharepoint_upload.py                      # upload output\<request-id> per SHAREPOINT_UPLOAD_METHOD
python sharepoint_upload.py --method sync        # one-off override
python sharepoint_upload.py "<path>" --method graph --no-proxy
```

#### Method 1: OneDrive-synced folder (`SHAREPOINT_UPLOAD_METHOD=sync`)

1. Open the target SharePoint/Teams folder in the browser and choose **Add shortcut to OneDrive** (or **Sync**).
2. Wait until the folder appears in File Explorer, for example `C:\Users\<user>\OneDrive - Bayer\Shortcuts\CF Internal - Veeva-valt-test`.
3. Set it in `.env`:

   ```text
   SHAREPOINT_UPLOAD_METHOD=sync
   SHAREPOINT_SYNC_FOLDER=C:\Users\<user>\OneDrive - Bayer\Shortcuts\CF Internal - Veeva-valt-test
   ```

4. Run `python sharepoint_upload.py`. The script copies the folder and verifies every file size locally; the OneDrive client then syncs it. Confirm in SharePoint that the folder appears (OneDrive must be running and signed in).

#### Method 2: Microsoft Graph with your own sign-in (`SHAREPOINT_UPLOAD_METHOD=graph`, `SHAREPOINT_AUTH=user`)

No app registration is needed. The script uses the Microsoft Graph Command Line Tools public client (override with `SHAREPOINT_PUBLIC_CLIENT_ID`) and signs you in with your company account. `SHAREPOINT_LOGIN` selects how: `broker` (default; Windows account broker, satisfies device-based conditional access, requires `msal[broker]`), `browser` (system browser), or `device` (device code; often blocked by conditional access). The token is cached in `.msal_token_cache.json` (git-ignored; delete it to sign out). Uploads use the `VEEVA_PROXY` proxy unless `SHAREPOINT_USE_PROXY=false` (direct connection also tested on the Bayer network).

```text
SHAREPOINT_SHARE_URL=<"Copy link" URL of the target SharePoint folder>
SHAREPOINT_LOGIN=broker
SHAREPOINT_LOGIN_HINT=<your company e-mail>
```

If your organization's conditional-access policy still blocks sign-in for this client, use Method 1 or Method 3.

Graph uploads verify each file's size in SharePoint. Office files (`.docx`, `.xlsx`, `.pptx`, ...) are exempt because SharePoint writes library metadata into them on upload. If an upload stops midway, delete the partial folder in SharePoint before rerunning.

#### Method 3: Microsoft Graph with an app registration (`SHAREPOINT_UPLOAD_METHOD=graph`, `SHAREPOINT_AUTH=app`)

For unattended use. Requires an approved Microsoft Entra app with Graph application permission `Sites.Selected` (granted on the site) or `Files.ReadWrite.All`, with admin consent:

```text
AZURE_TENANT_ID=<Microsoft Entra tenant ID>
AZURE_CLIENT_ID=<app registration client ID>
AZURE_CLIENT_SECRET=<app registration client secret>
SHAREPOINT_SHARE_URL=<folder link>   # or SHAREPOINT_DRIVE_ID + SHAREPOINT_FOLDER_PATH
```

### Command parameters

| Parameter | Example | Meaning |
|---|---|---|
| Input folder | `input` | API downloads (source, annotations, audit trails) plus any manually exported files. |
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
├── AN-KYL-US-0234\
│   ├── AN-KYL-US-0234_v0.1_Annotation.pdf
│   ├── AN-KYL-US-0234_v0.1_audit_trail.pdf
│   └── AN-KYL-US-0234_v0.1_Use Before Approval Form.pdf
├── CA-CON-AL-0001\
│   ├── CA-CON-AL-0001_v1.0_Annotation.pdf
│   ├── CA-CON-AL-0001_v1.0_audit_trail.pdf
│   ├── CA-CON-AL-0001_v1.0_Untitled.png
│   ├── CA-CON-AL-0001_v1.1_Annotation.pdf
│   ├── CA-CON-AL-0001_v1.1_audit_trail.pdf
│   └── CA-CON-AL-0001_v1.1_Untitled.png
├── Unmatched\
│   └── file_without_document_number.pdf
├── collection_tracker.csv
├── exceptions_report.csv
└── veeva_download_manifest.csv
```

Each document folder holds three files per version: `<Document Number>_v<Version>_Annotation.pdf`, `<Document Number>_v<Version>_audit_trail.pdf`, and `<Document Number>_v<Version>_<original source filename>`.

---

## 13. Output files explained

### 13.1 Document folders

Each identified document number gets one folder in the delivery folder, and all of that document's files sit directly inside it (no subfolders):

```text
DOC123456\
```

The category (`Source`, `Audit_Trail`, `Annotations`) is still recorded in `collection_tracker.csv`. Locally, the input folder keeps `Source\`, `Audit_Trail\`, and `Annotations\` subfolders so the organizer can classify each file.

### 13.2 `collection_tracker.csv`

This file records successfully classified files.

Columns:

| Column | Meaning |
|---|---|
| `document_number` | Document number detected in the filename. |
| `version` | Version detected in the filename, `ALL` for a manually supplied audit trail without a version, or `UNKNOWN`. |
| `category` | `Source`, `Audit_Trail`, or `Annotations`. |
| `source_file` | Original local file path. |
| `output_file` | New organized local file path. |

Open it in Excel to review the collection result.

`veeva_download_manifest.csv` is written to the input folder and copied into the delivery folder. It has one row per version with `status` (`DOWNLOADED`, `FAILED`, or `NOT_ATTEMPTED`), `error`, `annotation_status`, and `audit_status`, plus the Vault document ID and local file paths.

### 13.3 `exceptions_report.csv`

This file lists everything that needs review:

- Files that could not be matched to a document number (`Document number not found in filename`).
- Source files, annotations, or audit trails that were not downloaded, with the Vault reason (for example, `Content file does not exist`).

Example reason:

```text
Document number not found in filename
```

Correct those filenames manually, then rerun the script using a new request ID or remove the prior output folder first.

### 13.4 `Unmatched` folder

Files without a document number are copied to this folder. They are not deleted or ignored.

### 13.5 Delivery folder

The final delivery is the folder:

```text
output\LIT-001\
```

It contains document folders, the tracker, the exceptions report, and the download manifest. No ZIP is created. The workflow uploads this folder to SharePoint per `SHAREPOINT_UPLOAD_METHOD`; review it there.

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
output\LIT-DEMO\DOC123456\DOC123456_v1.0_source.pdf
output\LIT-DEMO\DOC123456\DOC123456_v1.0_audit.csv
output\LIT-DEMO\DOC123456\DOC123456_v1.0_Annotation.pdf
output\LIT-DEMO\DOC234567\DOC234567_v2.1_source.pdf
output\LIT-DEMO\Unmatched\notes.txt
output\LIT-DEMO\collection_tracker.csv
output\LIT-DEMO\exceptions_report.csv
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

Rerunning with the same request ID copies files into the existing delivery folder; files from an earlier run are not removed. Use a new request ID to preserve earlier deliveries. To discard the current working set before a fresh run, use `--clean` after confirming the configured input and output folders can be removed:

```powershell
python run_veeva_workflow.py --clean
```

### Error: `Signed in at <host> but Vault returned <other host>`

The account has no access to the Vault in `AUTH_URL`, so Vault signed in to the account's default Vault. Nothing is downloaded. Request access to that Vault, use another account, or switch `AUTH_URL` (see section 7).

### Error: `Already exists in SharePoint folder` / Graph `409 nameAlreadyExists`

A folder named `<request-id>` already exists at the SharePoint destination; uploads never overwrite. Set a new `VEEVA_REQUEST_ID`, or delete the old folder in SharePoint, then upload the existing delivery without re-downloading:

```powershell
python sharepoint_upload.py
```

### Microsoft sign-in: `You don't have access to this`

Conditional access blocked the sign-in method. Keep `SHAREPOINT_LOGIN=broker` (device-code sign-in is blocked on Bayer devices), or use `SHAREPOINT_UPLOAD_METHOD=sync`. Delete `.msal_token_cache.json` to sign in again.

### Error: `Set SHAREPOINT_UPLOAD_METHOD in .env`

The setting is missing or misspelled. Use `graph`, `sync`, or `none`.

---

## 16. Validation before delivery

After the workflow uploads the delivery folder to SharePoint, complete this checklist:

- [ ] Requested document numbers are present.
- [ ] Required source documents and versions are present.
- [ ] Audit trails are present where required.
- [ ] Required annotations are present.
- [ ] Annotation names use the required document/version format.
- [ ] `exceptions_report.csv` is reviewed and resolved or accepted.
- [ ] `collection_tracker.csv` is reviewed.
- [ ] The delivery folder contains one folder per requested document.
- [ ] The output is uploaded only to the approved customer destination (`SHAREPOINT_SHARE_URL` / `SHAREPOINT_SYNC_FOLDER`).

---

## 17. Security and handling guidance

- Keep Veeva and proxy credentials only in the local, Git-ignored `.env`; never commit them or paste them into logs.
- The Microsoft sign-in token is cached in `.msal_token_cache.json` (Git-ignored); delete it to sign out.
- Treat manually exported litigation content according to applicable Bayer access, retention, and information-handling requirements.
- Keep the input folder and output folder in approved local/network locations.
- Point the SharePoint settings only at approved destinations.
- Do not share the delivery folder through unapproved channels.

---

## 18. Operator-performed steps

The automation does not create the Veeva report. Items Vault cannot return (listed in `exceptions_report.csv`) must be exported manually when required. Review the manifest, tracker, exceptions report, and uploaded delivery folder.

---

## 19. Summary

The end-to-end automation retrieves the source versions, annotations, and audit trails listed by the client, prepares a verified delivery folder, and uploads it to SharePoint:

```text
Read the client version list
        ↓
Download source, annotations, and audit trails through the proxy
        ↓
Organize input files into a verified delivery folder
        ↓
Upload output\<request-id> to SharePoint (SHAREPOINT_UPLOAD_METHOD: graph / sync / none)
        ↓
Review tracker and exceptions in SharePoint
```
