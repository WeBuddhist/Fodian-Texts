#!/usr/bin/env python3
"""
sheet-to-inbox — build one 0-INBOX markdown file per text row of the
"Pecha Upload List" Google Sheet.

Pipeline stages (run individually, or `all` for the whole chain):

    fetch-sheet   download the sheet as .xlsx into the work directory
    parse         turn the .xlsx into records.json (one record per text row)
    fetch-docs    download each linked Google Doc into the document cache
    build         write 0-INBOX/<slug>.md for every record
    all           fetch-sheet -> parse -> fetch-docs -> build

Only `fetch-docs` touches the network for document bodies; `build` is
offline and re-runnable, so the inbox can be regenerated after a metadata
correction without re-downloading anything.
"""

import argparse
import datetime as _dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

DEFAULT_SHEET_ID = "1qXWMyWun6t2Nqya6SWPcHKVwk9AwYCtz5VUjYQOlAhU"
SHEET_TAB = "Pecha Upload"

# Column order of the "Pecha Upload" tab. Index == column position (A=0).
COLUMNS = [
    "kumarajiva_no",     # A  Kumarajive No. / 圓滿法藏編號
    "bdrc_work",         # B  BDRC Work (of this document)
    "data_prep",         # C  Data Preparation / 文本準備負責人
    "name_short",        # D  Tibetan/Chinese Sutra Name (Short)
    "name_long",         # E  Tibetan/Chinese Sutra Name (Long)
    "name_en",           # F  English Sutra Name
    "toh_column",        # G  headed "Commentary of (Toh number)"
    "root_bdrc",         # H  BDRC Work (under the རྩ་བ། / root-text banner)
    "category",          # I  Category
    "author_orig",       # J  Author (Tibetan/Chinese)
    "author_en",         # K  Author (English)
    "source",            # L  Source: URL or site name
    "lang_column",       # M  Bo/Zh/Modern ZH
    "doc_link",          # N  Document link
    "pecha_no",          # O  Pecha no.
    "pecha_status",      # P  Pecha Status
    "align_file",        # Q  Alignment File
    "align_status",      # R  Alingment Status
    "todo_kv",           # S
    "todo_drupchen",     # T
    "remark_gz",         # U
    "same_segmentation", # V
    "seg_simplified_zh", # W
    "chen_huang_remark", # X
]

HEADER_ROWS = 4          # rows 1-4 are banner + header rows
FIRST_DATA_ROW = 5

# Section banner rows: a row whose only content is a group title.
# Detected structurally (see is_banner_row) — this map is only used to give
# the detected banners stable slugs.
GROUP_SLUGS = {
    "對讀項目_尚待parsing_gold standard": "gold-standard",
    "kumarajiva": "kumarajiva",
    "kumarajiva kangyur translations 新譯佛典藏漢對讀(宛真)": "kangyur-translations",
    "正持法師- for kumarajiva": "zhengchi",
}

# Category taxonomy, imported from the sheet's hidden "Categories" tab
# (itself an IMPORTRANGE of the Pecha Categories master sheet).
# code -> (bo, en, lzh)
CATEGORY_TAXONOMY = {
    "1":    ("1 མདོ་སྡེ།", "1 Discourses", "1. 經部"),
    "2.1":  ("2.1 ཤེར་ཕྱིན་གྱི་མདོ།", "2.1 Discourses on the Perfection of Wisdom", "2.1 般若經與相關釋論"),
    "2.2":  ("2.2 ཤེར་ཕྱིན་གྱི་བསྟན་བཅོས།", "2.2 Treatises on the Perfection of Wisdom", "2.2 般若論典"),
    "3":    ("3 དབུ་མ།", "3 Middle Way", "3. 中觀"),
    "4":    ("4 སེམས་ཙམ།", "4 Mind-only Treatises", "4. 唯識"),
    "5":    ("5 མངོན་པ།", "5 Systematic Treatises", "5. 阿毘達磨"),
    "6":    ("6 རྒྱུད་སྡེ།", "6 Tantras", "6. 密續"),
    "7":    ("7 ཚད་མ།", "7 Logic", "7. 因明邏輯"),
    "8":    ("8 ཞལ་འདོན།", "8 Liturgy", "8. 實修儀軌"),
    "9.1":  ("9.1 བློ་སྦྱོང་།", "9.1 Mind Trainings", "9.1.修心方法"),
    "9.2":  ("9.2 བསླབ་བྱ།", "9.2 Advices", "9.2 修身教法"),
    "10.1": ("10.1 ལོ་རྒྱུས།", "10.1 History", "10.1 歷史與傳記"),
    "10.2": ("10.2 སྒྲུང་།", "10.2 Stories", "10.2 佛教故事"),
    "11":   ("11 གསོ་བ་རིག་པ།", "11 Medicine", "11. 醫方明"),
    "12.1": ("12.1 འདུལ་བའི་མདོ།", "12.1 Discourses on Monastic Rules", "12.1 律經"),
    "12.2": ("12.2 འདུལ་བའི་བསྟན་བཅོས།", "12.2 Treatises on Monastic Rules", "12.1 律部論典"),
    "13":   ("13 རིག་གནས།", "13 Linguistics Treatises", "13. 佛教語言學論典"),
    "14":   ("14 སྣ་ཚོགས།", "14 Miscenaleous", "14. 其他"),
}

# Category branches whose contents are treatises/commentaries rather than
# discourses spoken by the Buddha.
COMMENTARY_BRANCHES = {"2.2", "3", "4", "5", "7", "12.2", "13"}

# Column M (Bo/Zh/Modern ZH) -> (lang_tag, language, variant)
LANG_MAP = {
    "bo":               ("bo", "Tibetan", ""),
    "zh":               ("zh", "Classical Chinese", ""),
    "zh traditional":   ("zh-hant", "Classical Chinese", "traditional"),
    "簡":               ("zh-hans", "Chinese", "simplified"),
    "zh modern":        ("zh-modern", "Modern Chinese", "modern"),
    "註腳 with footnote": ("zh", "Classical Chinese", "with-footnote"),
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def log(msg):
    print(msg, file=sys.stderr, flush=True)


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def is_banner_row(rec):
    """A group banner: a title in the short-name column, nothing else."""
    if not rec["name_short"]:
        return False
    # A banner carries a title and nothing that identifies a text. Columns
    # like data_prep and align_status ARE filled on banner rows, so they
    # cannot be used as discriminators.
    other = ("kumarajiva_no", "lang_column", "doc_link", "name_long",
             "category", "author_orig")
    return not any(rec[c] for c in other)


def normalise_lang(raw, doc_title):
    """Resolve column M to (lang_tag, language, variant, mismatch).

    Column M is authoritative for the language. A document-link title may
    only *refine* that within the same language family — it can turn
    Classical Chinese into simplified Chinese, but it can never turn a
    Tibetan row into a Chinese one. Some rows in the sheet carry a title
    whose `_bo` / `_zh` suffix contradicts column M; that disagreement is
    reported as `mismatch` rather than silently resolved either way.
    """
    key = norm(raw).lower()
    tag, language, variant = LANG_MAP.get(key, ("", "", ""))
    if not tag:
        if key.startswith("bo"):
            tag, language = "bo", "Tibetan"
        elif key.startswith("zh"):
            tag, language = "zh", "Classical Chinese"

    title_raw = doc_title or ""
    title = title_raw.lower()
    is_chinese = tag.startswith("zh")

    # Variant markers refine only within the language column M declares.
    if is_chinese:
        if "simplified" in title or "简" in title_raw:
            tag, language, variant = "zh-hans", "Chinese", "simplified"
        elif "without footnote" in title:
            variant = "without-footnote"
        elif "with footnote" in title or "註腳" in title_raw:
            variant = "with-footnote"

    # Cross-check the title's own language suffix against column M.
    mismatch = ""
    m = re.search(r"[-_\u005f\uff3f](bo|zh)(?:[-_\u005f\uff3f.]|$)", title)
    if m:
        title_lang = m.group(1)
        col_lang = "bo" if tag == "bo" else ("zh" if is_chinese else "")
        if col_lang and title_lang != col_lang:
            mismatch = "column M says %s; document title says _%s" % (raw or "(blank)", title_lang)
    return tag, language, variant, mismatch


def parse_category(raw):
    """Return (code, branch, bo, en, lzh) for a raw category cell."""
    raw = norm(raw)
    if not raw:
        return "", "", "", "", ""
    m = re.match(r"^(\d+(?:\.\d+)?)", raw)
    code = m.group(1) if m else ""
    branch = code
    entry = CATEGORY_TAXONOMY.get(code)
    if entry is None and code:
        # fall back to the parent branch (e.g. "4.1" -> "4")
        branch = code.split(".")[0]
        entry = CATEGORY_TAXONOMY.get(branch)
    if entry is None:
        return code, branch, "", "", raw
    return code, branch, entry[0], entry[1], entry[2]


def extract_doc_id(url):
    m = re.search(r"/document/d/([A-Za-z0-9_-]{20,})", url or "")
    return m.group(1) if m else ""


TOH_RE = re.compile(r"(?<![a-z0-9])toh\s*(\d+)(?!\d)", re.I)
TAISHO_RE = re.compile(r"(?<![a-z0-9])tai\s*(\d+)(?!\d)", re.I)
KP_RE = re.compile(r"(?<![a-z0-9])kp\s*(\d+)(?!\d)", re.I)

# Language suffix a document-link title appends after the work ID.
LANG_SUFFIX_RE = re.compile(
    r"[-_\u005f\uff3f]+(bo|zh|simplified|traditional|modern)(?:[-_\u005f\uff3f]?\w+)?$", re.I)


def normalise_work_id(raw):
    """Canonical form: lowercase, `_` -> `-`, no trailing separator or lang tag."""
    wid = norm(raw).lower().replace("\uff3f", "-").replace("_", "-")
    wid = re.sub(r"[-\s.]+$", "", wid)
    wid = LANG_SUFFIX_RE.sub("", wid)
    wid = re.sub(r"-{2,}", "-", wid).strip("-")
    return wid


def derive_work_id(rec, cluster_id, doc_title):
    """Derive the per-row work ID.

    Cascade, most to least specific:
      1. an ID embedded in the document-link title (e.g. `... toh56to57-tai310-002_bo`)
      2. a `Toh####_kp####` pair in the document-link title
      3. the cluster ID from column A, carried down from the row that declared it
      4. the Toh number from column G
    """
    title = doc_title or ""

    # 1. explicit `tohNNN-taiNNN[-NN]` style id anywhere in the title.
    #    `[^\W_]` excludes the underscore so the trailing `_bo` / `_zh`
    #    language marker is not swallowed into the ID.
    m = re.search(r"(toh[^\W_]*\d[^\W_]*-tai[^\W_.]*\d[^\W_]*(?:-\d+)?)", title, re.I)
    if m:
        return normalise_work_id(m.group(1)), "doc-title"

    # 2. `Toh0023_kp0002_...`
    mt, mk = TOH_RE.search(title), KP_RE.search(title)
    if mt and mk:
        return "toh%s-kp%s" % (mt.group(1), mk.group(1)), "doc-title"
    if mt and not cluster_id:
        return "toh%s" % mt.group(1), "doc-title"

    # 3. the cluster ID carried down from column A
    if cluster_id:
        return normalise_work_id(cluster_id), "column-a"

    # 4. the Toh anchor in column G
    mt = TOH_RE.search(rec["toh_column"])
    if mt:
        return "toh%s" % mt.group(1), "column-g"

    return "", "none"


def clean_cluster_id(raw):
    """Column A sometimes holds a stray source URL instead of an ID."""
    raw = norm(raw)
    if not raw or raw.lower().startswith("http"):
        return ""
    return raw


def slugify(text):
    text = norm(text).lower()
    text = re.sub(r"[()（），,、《》\"'“”‘’]", "", text)
    text = re.sub(r"[^a-z0-9._-]+", "-", text)
    return re.sub(r"-{2,}", "-", text).strip("-._") or "untitled"


def strip_id_suffix(name, work_id):
    """Sheet name cells often repeat the work ID; drop it from the title.

    The ID is stripped in both its canonical and its as-written form, then
    any separator it was hanging off (`- `, `_`, `,`) is trimmed too, so
    "... Assembly - Xuanzang -toh56to57-tai310-008" ends at "Xuanzang".
    """
    out = norm(name)
    if not out:
        return out
    for candidate in filter(None, {work_id, norm(work_id).replace("-", "_")}):
        out = re.sub(re.escape(candidate) + r"\s*$", "", out, flags=re.I)
    out = re.sub(r"[\s\-_,\u005f\uff3f]+$", "", out)
    return norm(out)


# --------------------------------------------------------------------------
# Stage: fetch-sheet
# --------------------------------------------------------------------------

def stage_fetch_sheet(sheet_id, workdir):
    os.makedirs(workdir, exist_ok=True)
    dest = os.path.join(workdir, "pecha-upload.xlsx")
    url = "https://docs.google.com/spreadsheets/d/%s/export?format=xlsx" % sheet_id
    log("fetch-sheet: %s" % url)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if not data.startswith(b"PK"):
        raise SystemExit(
            "fetch-sheet: response is not an .xlsx file. The sheet is probably "
            "not link-readable. Export it manually and pass --xlsx."
        )
    with open(dest, "wb") as fh:
        fh.write(data)
    log("fetch-sheet: wrote %s (%d bytes)" % (dest, len(data)))
    return dest


# --------------------------------------------------------------------------
# Stage: parse
# --------------------------------------------------------------------------

def stage_parse(xlsx_path, workdir, sheet_id):
    os.makedirs(workdir, exist_ok=True)
    try:
        import openpyxl
    except ImportError:
        raise SystemExit("parse: openpyxl is required — pip install openpyxl")

    wb = openpyxl.load_workbook(xlsx_path)
    if SHEET_TAB not in wb.sheetnames:
        raise SystemExit("parse: tab %r not found (have: %s)" % (SHEET_TAB, wb.sheetnames))
    ws = wb[SHEET_TAB]

    raw_rows = []
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row):
        rec = {"_row": row[0].row}
        for i, name in enumerate(COLUMNS):
            cell = row[i] if i < len(row) else None
            val = cell.value if cell is not None else None
            rec[name] = norm("" if val is None else str(val))
            link = ""
            if cell is not None and cell.hyperlink and cell.hyperlink.target:
                link = cell.hyperlink.target
            rec[name + "_url"] = link
        raw_rows.append(rec)

    records = []
    group = ""
    cluster_id = ""
    base_cluster_id = ""
    cluster_names = {}
    cluster_split = 0
    for rec in raw_rows:
        if rec["_row"] < FIRST_DATA_ROW:
            continue
        if not any(rec[c] for c in COLUMNS):
            continue
        if is_banner_row(rec):
            group = GROUP_SLUGS.get(rec["name_short"].lower(), slugify(rec["name_short"]))
            cluster_id = ""
            base_cluster_id = ""
            cluster_names = {}
            cluster_split = 0
            continue

        cid = clean_cluster_id(rec["kumarajiva_no"])
        if cid:
            cluster_id = cid
            cluster_names = {}
            cluster_split = 0
        else:
            # A row with no ID of its own inherits the cluster above it. That
            # inheritance is wrong whenever the row has actually moved on to a
            # different work, which the sheet signals in two ways.
            #
            # (a) Column G names a different Toh number. Column G is real
            #     sheet data, so it wins and starts a new cluster.
            g_toh = TOH_RE.search(rec["toh_column"])
            c_toh = TOH_RE.search(cluster_id or "")
            if g_toh and c_toh and g_toh.group(1).lstrip("0") != c_toh.group(1).lstrip("0"):
                cluster_id = "toh%s" % g_toh.group(1)
                cluster_names = {}
                cluster_split = 0
            # (b) Otherwise the row stands on inheritance alone. Where the
            #     sheet gives the Tibetan rows no title at all, which of them
            #     belongs with which Chinese row is simply not recoverable —
            #     so the row keeps the inherited ID (that is what the sheet
            #     says) but claims no alignment. See link_alignment_pairs.

        doc_url = rec["doc_link_url"] or (rec["doc_link"] if rec["doc_link"].startswith("http") else "")
        doc_title = "" if rec["doc_link"].startswith("http") else rec["doc_link"]

        work_id, id_source = derive_work_id(rec, cluster_id, doc_title)
        _lang_key = "bo" if norm(rec["lang_column"]).lower().startswith("bo") else "zh"
        if rec["name_short"]:
            cluster_names.setdefault(_lang_key, rec["name_short"])
        # A row that brought no ID of its own and no column-G corroboration
        # is standing on inheritance alone.
        cluster_uncertain = bool(
            not cid and id_source == "column-a"
            and not rec["toh_column"] and not doc_title)
        lang_tag, language, variant, lang_mismatch = normalise_lang(rec["lang_column"], doc_title)
        cat_code, cat_branch, cat_bo, cat_en, cat_lzh = parse_category(rec["category"])

        mt = TOH_RE.search(rec["toh_column"] or work_id)
        ma = TAISHO_RE.search(work_id or doc_title)

        out = {
            "sheet_row": rec["_row"],
            "group": group,
            "cluster_id": cluster_id,
            "work_id": work_id,
            "work_id_source": id_source,
            "cluster_uncertain": cluster_uncertain,
            "lang_tag": lang_tag,
            "language": language,
            "variant": variant,
            "lang_column": rec["lang_column"],
            "lang_mismatch": lang_mismatch,
            "name_short": strip_id_suffix(rec["name_short"], work_id),
            "name_long": strip_id_suffix(rec["name_long"], work_id),
            "name_en": strip_id_suffix(rec["name_en"], work_id),
            "toh": ("toh%s" % mt.group(1)) if mt else "",
            "toh_column_raw": rec["toh_column"],
            "taisho": ("tai%s" % ma.group(1)) if ma else "",
            "bdrc_work": rec["bdrc_work"],
            "root_bdrc": rec["root_bdrc"],
            "category_raw": rec["category"],
            "category_code": cat_code,
            "category_branch": cat_branch,
            "category_bo": cat_bo,
            "category_en": cat_en,
            "category_lzh": cat_lzh,
            "author_orig": rec["author_orig"],
            "author_en": rec["author_en"],
            "source": rec["source"],
            "source_url": rec["source_url"] or (rec["source"] if rec["source"].startswith("http") else ""),
            "doc_title": doc_title,
            "doc_url": doc_url,
            "doc_id": extract_doc_id(doc_url),
            "pecha_no": rec["pecha_no"],
            "pecha_id": (rec["pecha_no"].split("-")[0].strip() if rec["pecha_no"] else ""),
            "pecha_status": rec["pecha_status"],
            "align_file": rec["align_file"],
            "align_file_url": rec["align_file_url"] or (rec["align_file"] if rec["align_file"].startswith("http") else ""),
            "align_status": rec["align_status"],
            "data_prep": rec["data_prep"],
            "remarks": {
                k: rec[k] for k in
                ("todo_kv", "todo_drupchen", "remark_gz", "same_segmentation",
                 "seg_simplified_zh", "chen_huang_remark") if rec[k]
            },
            "sheet_id": sheet_id,
        }

        # file_type: modern Chinese renderings are translations; treatise
        # branches are commentaries; everything else is a root text.
        if out["variant"] == "modern" or out["lang_tag"] == "zh-modern":
            out["file_type"] = "translation"
        elif cat_branch in COMMENTARY_BRANCHES or cat_code in COMMENTARY_BRANCHES:
            out["file_type"] = "commentary"
        else:
            out["file_type"] = "root-text"

        records.append(out)

    assign_slugs(records)
    link_alignment_pairs(records)

    out_path = os.path.join(workdir, "records.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(records, fh, ensure_ascii=False, indent=1)
    log("parse: %d text records -> %s" % (len(records), out_path))
    return out_path


def assign_slugs(records):
    """slug = <work-id>-<lang-tag>[-variant][-N]; unique across the run."""
    seen = {}
    for rec in records:
        base = rec["work_id"] or ("row%d" % rec["sheet_row"])
        parts = [base]
        if rec["lang_tag"]:
            parts.append(rec["lang_tag"])
        if rec["variant"] and rec["variant"] not in ("simplified", "modern", "traditional"):
            parts.append(rec["variant"])
        slug = slugify("-".join(parts))
        n = seen.get(slug, 0) + 1
        seen[slug] = n
        rec["slug"] = slug if n == 1 else "%s-%d" % (slug, n)


def link_alignment_pairs(records):
    """Rows sharing a work ID are the aligned language versions of one work.

    Rows flagged `cluster_uncertain` are excluded on both sides. Such a row
    inherited its ID from column A with nothing of its own to corroborate it
    — no ID, no Toh number, no document title — so asserting that it aligns
    with the rest of the cluster would be a guess. The sheet has to be fixed
    for those rows; until then they claim nothing.
    """
    by_work = {}
    for rec in records:
        if rec["work_id"] and not rec.get("cluster_uncertain"):
            by_work.setdefault(rec["work_id"], []).append(rec)
    for rec in records:
        if rec.get("cluster_uncertain"):
            rec["aligned_with"] = []
            continue
        peers = by_work.get(rec["work_id"], [])
        rec["aligned_with"] = [p["slug"] for p in peers if p is not rec]


# --------------------------------------------------------------------------
# Stage: fetch-docs
# --------------------------------------------------------------------------

def _convert_docx(path):
    """Convert a .docx to markdown with the shared converter."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from docx_to_markdown import docx_to_markdown
    return docx_to_markdown(path)


def get_access_token():
    """Best-effort OAuth token with Drive scope, via gcloud ADC.

    GOOGLE_APPLICATION_CREDENTIALS is cleared for the subprocess: when it
    points at a service-account key, gcloud mints a token for that account
    instead of the user credentials just created by
    `gcloud auth application-default login`, and the service account
    typically has no access to the shared documents at all.
    """
    env = dict(os.environ)
    env.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
    for cmd in (["gcloud", "auth", "application-default", "print-access-token"],
                ["gcloud", "auth", "print-access-token"]):
        try:
            tok = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
            if tok.returncode == 0 and tok.stdout.strip():
                return tok.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
    return ""


def _http_get(url, token=None, timeout=45):
    headers = {"User-Agent": "Mozilla/5.0"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


DOCX_MIME = ("application/vnd.openxmlformats-officedocument"
             ".wordprocessingml.document")


def _looks_like_docx(body):
    return body[:2] == b"PK"


_TOKEN_SCOPE_OK = [True]        # flipped off after the first scope rejection


def fetch_document(doc_id, token="", cachedir=""):
    """Return (text, method) or (None, reason).

    `.docx` is requested in preference to `text/plain`: Word numbering,
    footnotes and highlighting survive only in the `.docx`, and in this
    corpus the numbering IS the segmentation that aligns the Tibetan and
    Chinese witnesses. Plain text is kept as a fallback for documents whose
    `.docx` export fails.

    Anonymous export is tried first — it succeeds for link-readable
    documents and costs nothing. The Drive API with a Bearer token is the
    fallback for documents restricted to the signed-in account.
    """
    attempts = [
        ("https://docs.google.com/document/d/%s/export?format=docx" % doc_id, None, "anonymous-docx", True),
        ("https://docs.google.com/document/d/%s/export?format=txt" % doc_id, None, "anonymous-txt", False),
    ]
    if token and _TOKEN_SCOPE_OK[0]:
        attempts += [
            ("https://www.googleapis.com/drive/v3/files/%s/export?mimeType=%s"
             "&supportsAllDrives=true" % (doc_id, urllib.parse.quote(DOCX_MIME)),
             token, "drive-api-docx", True),
            ("https://www.googleapis.com/drive/v3/files/%s/export"
             "?mimeType=text/plain&supportsAllDrives=true" % doc_id,
             token, "drive-api-txt", False),
            ("https://www.googleapis.com/drive/v3/files/%s?alt=media"
             "&supportsAllDrives=true" % doc_id, token, "drive-api-media", True),
        ]

    last = "unreachable"
    for url, tok, method, want_docx in attempts:
        try:
            status, body = _http_get(url, token=tok)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read().decode())["error"]["message"]
            except Exception:
                pass
            last = "%s-%d%s" % (method, e.code, (": " + detail) if detail else "")
            if "insufficient authentication scopes" in detail.lower():
                # the scope will not change mid-run; stop paying for it
                _TOKEN_SCOPE_OK[0] = False
                return None, ("restricted: token lacks the Drive scope "
                              "(re-run `gcloud auth application-default login "
                              "--scopes=...drive.readonly`)")
            if e.code in (401, 403, 404):
                continue
            return None, last
        except (urllib.error.URLError, OSError) as e:
            return None, "network-error: %s" % e

        if status != 200:
            last = "%s-http-%d" % (method, status)
            continue
        if want_docx:
            if not _looks_like_docx(body):
                last = "%s-not-a-docx" % method
                continue
            path = os.path.join(cachedir or ".", doc_id + ".docx")
            with open(path, "wb") as fh:
                fh.write(body)
            try:
                return _convert_docx(path), method
            except Exception as e:
                last = "%s-convert-failed: %s" % (method, e)
                continue
        if body.lstrip()[:200].lower().startswith(b"<!doctype html"):
            last = "%s-sign-in-page" % method
            continue
        return body.decode("utf-8-sig", errors="replace"), method

    if not token and last.startswith("anonymous"):
        return None, "restricted-no-token (%s)" % last
    return None, last


def stage_fetch_docs(records_path, cachedir, delay, only_missing=True):
    os.makedirs(cachedir, exist_ok=True)
    records = json.load(open(records_path, encoding="utf-8"))
    token = get_access_token()
    log("fetch-docs: access token %s" % ("acquired" if token else "NOT available (anonymous only)"))

    status_path = os.path.join(cachedir, "_fetch-status.json")
    fetched = json.load(open(status_path, encoding="utf-8")) if os.path.exists(status_path) else {}

    todo = [r for r in records if r["doc_id"]]
    ok = skipped = failed = 0
    for i, rec in enumerate(todo, 1):
        doc_id = rec["doc_id"]
        dest = os.path.join(cachedir, doc_id + ".txt")
        if only_missing and os.path.exists(dest) and os.path.getsize(dest) > 0:
            skipped += 1
            continue
        text, method = fetch_document(doc_id, token, cachedir)
        if text is None:
            failed += 1
            fetched[doc_id] = {"ok": False, "reason": method}
            log("  [%3d/%3d] %-46s FAIL  %s" % (i, len(todo), rec["slug"], method))
        else:
            ok += 1
            with open(dest, "w", encoding="utf-8") as fh:
                fh.write(text)
            fetched[doc_id] = {"ok": True, "method": method, "chars": len(text)}
            log("  [%3d/%3d] %-46s ok    %s %d chars" % (i, len(todo), rec["slug"], method, len(text)))
        time.sleep(delay)

    with open(status_path, "w", encoding="utf-8") as fh:
        json.dump(fetched, fh, ensure_ascii=False, indent=1)
    log("fetch-docs: %d fetched, %d cached, %d failed (of %d linked docs)"
        % (ok, skipped, failed, len(todo)))
    return status_path


# --------------------------------------------------------------------------
# Stage: import-local
# --------------------------------------------------------------------------

DUP_SUFFIX_RE = re.compile(r"\s*\(\d+\)$")          # Chrome's " (1)" marker
# `Toh4054-Tai1606《阿毘達磨雜集論》01_bo`
TOH_TAI_PART_RE = re.compile(
    r"^toh\s*(\d+)\s*-\s*tai\s*(\d+).*?(\d{1,3})\s*[_\-\uff3f]\s*(bo|zh)", re.I)
# `T1605-1_大乘阿毘達磨集論_bo`
TAI_PART_RE = re.compile(r"^t\s*(\d+)\s*-\s*(\d{1,3})[_\-\uff3f].*?[_\-\uff3f](bo|zh)", re.I)


def _title_key(s):
    """Loose key for comparing a filename with a sheet link title."""
    s = re.sub(r"\.docx?$", "", norm(s), flags=re.I)
    s = s.replace("\uff3f", "_").replace("\u005f", "_")
    return re.sub(r"\s+", "", s).lower()


def _lang_matches(rec, lang):
    return rec["lang_tag"] == "bo" if lang.lower() == "bo" else rec["lang_tag"].startswith("zh")


def _resolve(basename, records, by_title):
    """Return (list_of_records, how) for one downloaded file."""
    k = _title_key(basename)
    if k in by_title:
        return by_title[k], "title"

    m = TOH_TAI_PART_RE.match(norm(basename))
    if m:
        toh, tai, part, lang = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        wid = "toh%s-tai%s-%d" % (toh, tai, part)
        hits = [r for r in records if r["work_id"] == wid and _lang_matches(r, lang)]
        if len(hits) == 1:
            return hits, "toh-tai-part"
        if hits:
            return [], "ambiguous:%s" % wid

    m = TAI_PART_RE.match(norm(basename))
    if m:
        tai, part, lang = m.group(1), int(m.group(2)), m.group(3)
        suffix = "tai%s-%d" % (tai, part)
        hits = [r for r in records
                if r["work_id"].endswith(suffix) and _lang_matches(r, lang)]
        if len(hits) == 1:
            return hits, "tai-part"
        if hits:
            return [], "ambiguous:%s" % suffix

    return [], "unmatched"


def stage_import_local(source, records_path, cachedir, since="", archive=True):
    """Import .docx files downloaded by hand into the document cache.

    Text is extracted and written to `<cachedir>/by-slug/<slug>.txt`, which
    `build` reads exactly like a downloaded document — so a hand-collected
    corpus and an API-fetched one produce identical output.

    The originals are also copied into `<cachedir>/original/` so the vault
    holds the raw material the markdown was derived from, not just the
    derivation. A browser's ` (1)` re-download is archived once, since those
    copies are verified text-identical before being collapsed.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from docx_to_markdown import docx_to_markdown

    records = json.load(open(records_path, encoding="utf-8"))
    by_title = {}
    for r in records:
        if r["doc_title"]:
            by_title.setdefault(_title_key(r["doc_title"]), []).append(r)

    cutoff = 0.0
    if since:
        cutoff = _dt.datetime.strptime(since, "%Y-%m-%d %H:%M").timestamp()

    paths = sorted(p for p in glob.glob(os.path.join(source, "**", "*.docx"), recursive=True)
                   if os.path.getmtime(p) >= cutoff and not os.path.basename(p).startswith("~$"))
    log("import-local: %d .docx under %s%s"
        % (len(paths), source, (" modified since " + since) if since else ""))

    # Collapse Chrome's duplicate downloads, but only when the TEXT agrees.
    groups = {}
    for p in paths:
        base = DUP_SUFFIX_RE.sub("", os.path.splitext(os.path.basename(p))[0])
        groups.setdefault(base, []).append(p)

    texts, conflicts, unreadable = {}, [], []
    for base, members in groups.items():
        variants = {}
        for p in members:
            try:
                variants.setdefault(docx_to_markdown(p), []).append(p)
            except Exception as e:
                unreadable.append((p, str(e)))
        if not variants:
            continue
        if len(variants) > 1:
            conflicts.append((base, [os.path.basename(x) for v in variants.values() for x in v]))
            # keep the longest extraction rather than guessing
            texts[base] = max(variants, key=len)
        else:
            texts[base] = next(iter(variants))

    if archive:
        archive_dir = os.path.join(cachedir, "original")
        os.makedirs(archive_dir, exist_ok=True)
        copied = 0
        for base, members in groups.items():
            if base not in texts:
                continue
            src = min(members, key=os.path.getsize)
            dst = os.path.join(archive_dir, os.path.basename(src))
            dst = re.sub(r"\s*\(\d+\)(\.docx)$", r"\1", dst)
            if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src):
                shutil.copy2(src, dst)
                copied += 1
        log("import-local: archived %d original .docx -> %s" % (copied, archive_dir))

    outdir = os.path.join(cachedir, "by-slug")
    os.makedirs(outdir, exist_ok=True)
    assigned, orphans, ambiguous = {}, [], []
    for base, text in sorted(texts.items()):
        hits, how = _resolve(base, records, by_title)
        if not hits:
            (ambiguous if how.startswith("ambiguous") else orphans).append((base, how))
            continue
        for r in hits:
            with open(os.path.join(outdir, r["slug"] + ".txt"), "w", encoding="utf-8") as fh:
                fh.write(text)
            assigned[r["slug"]] = {"file": base, "how": how, "chars": len(text)}

    # Files that are real documents but have no row in the sheet.
    orphan_dir = os.path.join(cachedir, "orphans")
    if orphans:
        os.makedirs(orphan_dir, exist_ok=True)
        for base, _ in orphans:
            with open(os.path.join(orphan_dir, slugify(base) + ".txt"), "w", encoding="utf-8") as fh:
                fh.write(texts[base])

    status = {"assigned": assigned,
              "orphans": [{"file": b, "slug": slugify(b)} for b, _ in orphans],
              "ambiguous": [{"file": b, "reason": h} for b, h in ambiguous],
              "text_conflicts": [{"file": b, "copies": c} for b, c in conflicts],
              "unreadable": [{"file": p, "error": e} for p, e in unreadable]}
    with open(os.path.join(cachedir, "_import-status.json"), "w", encoding="utf-8") as fh:
        json.dump(status, fh, ensure_ascii=False, indent=1)

    log("import-local: %d unique documents -> %d records matched"
        % (len(texts), len(assigned)))
    for label, items in (("no sheet row", orphans), ("ambiguous", ambiguous),
                         ("text differs between copies", conflicts),
                         ("unreadable", unreadable)):
        if items:
            log("import-local: %d %s" % (len(items), label))
            for it in items[:10]:
                log("    %s" % (it[0] if isinstance(it, tuple) else it))
    return status


# --------------------------------------------------------------------------
# Stage: build
# --------------------------------------------------------------------------

SEGMENT_ID_RE = re.compile(r"\s\^s([0-9a-z-]+)\s*$", re.M)

# A line that types its own segment number, e.g. "12. <text>".
# A bare "12." with no text is a deliberately EMPTY segment holding an
# alignment slot open — it must be counted, or the two witnesses stop
# matching. (Toh555/Tai665: 8367 filled + 172 empty in the Chinese, 8469 +
# 70 in the Tibetan, 8539 segments in both.)
LITERAL_SEG_RE = re.compile(r"^[ \t]*(\d{1,5})\.(?:[ \t]+\S|[ \t]*$)")


def annotate_literal_segments(text):
    """Add `^sN` anchors to documents that type their segment numbers.

    Two notations carry the segmentation in this corpus. Most documents use
    Word auto-numbering, which `docx_to_markdown` reconstructs. The rest type
    the number into the text (`12. …`) — there the number is already in the
    run, so nothing was lost, but it carries no anchor and cannot be
    addressed across languages.

    Only a document whose numbers form a genuinely sequential run is
    annotated: at least five of them, at least 80% each one greater than the
    last. That threshold keeps an incidental numbered list inside prose from
    being mistaken for a segmentation scheme.
    """
    lines = text.split("\n")
    hits = []
    for i, line in enumerate(lines):
        m = LITERAL_SEG_RE.match(line)
        if m:
            hits.append((i, int(m.group(1))))
    if len(hits) < 5:
        return text, 0
    ascending = sum(1 for (_, a), (_, b) in zip(hits, hits[1:]) if b == a + 1)
    if ascending / max(1, len(hits) - 1) < 0.8:
        return text, 0

    seen = {}
    for i, n in hits:
        if SEGMENT_ID_RE.search(lines[i]):
            continue
        seen[n] = seen.get(n, 0) + 1
        frag = str(n) if seen[n] == 1 else "%d-%d" % (n, seen[n])
        lines[i] = lines[i].rstrip() + " ^s%s" % frag
    return "\n".join(lines), len(hits)


def segment_ids(text):
    """The `^sN` segment anchors in a body, in document order."""
    return SEGMENT_ID_RE.findall(text or "")


def yaml_scalar(v):
    if v is None:
        return '""'
    s = str(v)
    if s == "":
        return '""'
    if re.search(r'[:#\[\]{}&*!|>%@`"\']|^\s|\s$|^-\s|^[\d.]+$', s) or "\n" in s:
        return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')
    return s


def yaml_list(items):
    if not items:
        return "[]"
    return "[%s]" % ", ".join(yaml_scalar(i) for i in items)


def build_frontmatter(rec, body_status, retrieved, seg=None):
    title = rec["name_long"] or rec["name_short"] or rec["name_en"] or rec["work_id"]
    f = []
    a = f.append
    a("---")
    a("# --- identity ---")
    a("title: %s" % yaml_scalar(title))
    a("title_short: %s" % yaml_scalar(rec["name_short"]))
    a("title_long: %s" % yaml_scalar(rec["name_long"]))
    a("title_en: %s" % yaml_scalar(rec["name_en"]))
    a("work_id: %s" % yaml_scalar(rec["work_id"]))
    a("file_type: %s" % yaml_scalar(rec["file_type"]))
    a("language: %s" % yaml_scalar(rec["language"]))
    a("lang_tag: %s" % yaml_scalar(rec["lang_tag"]))
    a("edition_variant: %s" % yaml_scalar(rec["variant"]))
    a("")
    a("# --- catalogue ids ---")
    a("toh: %s" % yaml_scalar(rec["toh"]))
    a("taisho: %s" % yaml_scalar(rec["taisho"]))
    a("bdrc_work_id: %s" % yaml_scalar(rec["bdrc_work"]))
    a("root_bdrc_work_id: %s" % yaml_scalar(rec["root_bdrc"]))
    a("pecha_id: %s" % yaml_scalar(rec["pecha_id"]))
    a("pecha_no: %s" % yaml_scalar(rec["pecha_no"]))
    a("")
    a("# --- authorship ---")
    a("author: %s" % yaml_scalar(rec["author_orig"]))
    a("author_en: %s" % yaml_scalar(rec["author_en"]))
    a("")
    a("# --- classification ---")
    a("category: %s" % yaml_scalar(rec["category_raw"]))
    a("category_code: %s" % yaml_scalar(rec["category_code"]))
    a("category_en: %s" % yaml_scalar(rec["category_en"]))
    a("category_bo: %s" % yaml_scalar(rec["category_bo"]))
    a("category_lzh: %s" % yaml_scalar(rec["category_lzh"]))
    a("")
    a("# --- segmentation ---")
    a("segment_count: %d" % (seg or {}).get("count", 0))
    a("segment_scheme: %s" % yaml_scalar((seg or {}).get("scheme", "")))
    if seg and seg.get("peer_counts"):
        a("peer_segment_counts:")
        for k, v in sorted(seg["peer_counts"].items()):
            a("  %s: %s" % (k, v if v is not None else "null"))
        a("segments_aligned: %s" % ("true" if seg.get("aligned") else "false"))
    a("")
    a("# --- relations ---")
    a("aligned_with: %s" % yaml_list(rec["aligned_with"]))
    a("work_group: %s" % yaml_scalar(rec["group"]))
    a("cluster_id: %s" % yaml_scalar(rec["cluster_id"]))
    a("toh_column_raw: %s" % yaml_scalar(rec["toh_column_raw"]))
    a("")
    a("# --- provenance ---")
    a("source_description: %s" % yaml_scalar(rec["source"]))
    a("source_url: %s" % yaml_scalar(rec["source_url"]))
    a("document_link: %s" % yaml_scalar(rec["doc_url"]))
    a("document_title: %s" % yaml_scalar(rec["doc_title"]))
    a("google_doc_id: %s" % yaml_scalar(rec["doc_id"]))
    a("sheet_id: %s" % yaml_scalar(rec["sheet_id"]))
    a("sheet_row: %d" % rec["sheet_row"])
    a("work_id_source: %s" % yaml_scalar(rec["work_id_source"]))
    if rec.get("cluster_uncertain"):
        a("cluster_uncertain: true   # ID inherited from column A only — no ID, "
          "Toh number or document title of its own")
    a("")
    a("# --- workflow status ---")
    a("pecha_status: %s" % yaml_scalar(rec["pecha_status"]))
    a("alignment_status: %s" % yaml_scalar(rec["align_status"]))
    a("alignment_file: %s" % yaml_scalar(rec["align_file"]))
    a("alignment_file_url: %s" % yaml_scalar(rec["align_file_url"]))
    a("data_prep: %s" % yaml_scalar(rec["data_prep"]))
    if rec.get("lang_mismatch"):
        a("lang_mismatch: %s" % yaml_scalar(rec["lang_mismatch"]))
    a("ingest_status: %s" % yaml_scalar(body_status))
    a("retrieved: %s" % retrieved)
    if rec["remarks"]:
        a("")
        a("# --- sheet remarks ---")
        a("remarks:")
        for k, v in rec["remarks"].items():
            a("  %s: %s" % (k, yaml_scalar(v)))
    a("status: draft")
    a("---")
    return "\n".join(f)


def build_body(rec, text, body_status):
    title = rec["name_long"] or rec["name_short"] or rec["name_en"] or rec["slug"]
    out = ["", "# %s" % title, ""]
    if rec["name_en"] and rec["name_en"] != title:
        out += ["*%s*" % rec["name_en"], ""]

    rel = []
    if rec["aligned_with"]:
        rel.append("- Aligned language versions: %s"
                   % ", ".join("[[%s]]" % s for s in rec["aligned_with"]))
    if rec["toh"]:
        rel.append("- Toh: `%s`" % rec["toh"])
    if rec["taisho"]:
        rel.append("- Taishō: `%s`" % rec["taisho"])
    if rec["doc_url"]:
        rel.append("- Source document: [%s](%s)"
                   % (rec["doc_title"] or "Google Doc", rec["doc_url"]))
    if rel:
        out += ["## Relations", ""] + rel + [""]

    out += ["## Text", ""]
    if text is not None:
        out += [text.rstrip(), ""]
    else:
        out += ["> [Ed: body not retrieved — `ingest_status: %s`. "
                "Re-run the `fetch-docs` stage once the document is readable.]" % body_status, ""]
    return "\n".join(out)


LANG_FOLDER = {"bo": "tibetan"}          # everything zh* goes to "chinese"


def language_folder(lang_tag):
    """Inbox subfolder for a record. Proofreaders work one language at a time."""
    if not lang_tag:
        return "unsorted"
    return LANG_FOLDER.get(lang_tag, "chinese" if lang_tag.startswith("zh") else "unsorted")


def stage_build(records_path, cachedir, inboxdir, retrieved=None):
    records = json.load(open(records_path, encoding="utf-8"))
    os.makedirs(inboxdir, exist_ok=True)
    retrieved = retrieved or _dt.date.today().isoformat()

    status_path = os.path.join(cachedir, "_fetch-status.json")
    fetch_status = json.load(open(status_path, encoding="utf-8")) if os.path.exists(status_path) else {}

    counts = {"with-body": 0, "link-restricted": 0, "no-link": 0}
    manifest = []

    # First pass: resolve every body, so a record's segment count can be
    # compared against its aligned peers in the second pass.
    bodies, seginfo = {}, {}
    for rec in records:
        local = os.path.join(cachedir, "by-slug", rec["slug"] + ".txt")
        text = None
        if os.path.exists(local) and os.path.getsize(local) > 0:
            text = open(local, encoding="utf-8").read()
        elif rec["doc_id"]:
            cached = os.path.join(cachedir, rec["doc_id"] + ".txt")
            if os.path.exists(cached) and os.path.getsize(cached) > 0:
                text = open(cached, encoding="utf-8").read()
        scheme = ""
        if text is not None:
            ids = segment_ids(text)
            if ids:
                scheme = "word-auto-numbering"
            else:
                text, n = annotate_literal_segments(text)
                if n:
                    scheme = "literal-numbering"
                    ids = segment_ids(text)
                else:
                    scheme = "none"
        else:
            ids = []
        bodies[rec["slug"]] = text
        seginfo[rec["slug"]] = {"count": len(ids), "scheme": scheme}
    for rec in records:
        info = seginfo[rec["slug"]]
        peers = {p: seginfo[p]["count"] if bodies.get(p) is not None else None
                 for p in rec["aligned_with"]}
        info["peer_counts"] = peers
        known = [v for v in peers.values() if v]
        info["aligned"] = bool(info["count"]) and all(v == info["count"] for v in known)

    for rec in records:
        # A hand-imported document wins: it was collected deliberately, and
        # for rows with no document link it is the only body there is.
        text = bodies[rec["slug"]]
        if text is not None:
            body_status = "with-body"
        elif not rec["doc_id"]:
            body_status = "no-link"
        else:
            reason = (fetch_status.get(rec["doc_id"]) or {}).get("reason", "not-fetched")
            body_status = "link-restricted"
            if reason == "not-fetched":
                body_status = "not-fetched"
        counts[body_status] = counts.get(body_status, 0) + 1

        folder = language_folder(rec["lang_tag"])
        os.makedirs(os.path.join(inboxdir, folder), exist_ok=True)
        path = os.path.join(inboxdir, folder, rec["slug"] + ".md")
        content = (build_frontmatter(rec, body_status, retrieved, seginfo[rec["slug"]])
                   + "\n" + build_body(rec, text, body_status))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(content)
        manifest.append({"slug": rec["slug"], "path": path, "folder": folder,
                         "sheet_row": rec["sheet_row"],
                         "work_id": rec["work_id"], "lang_tag": rec["lang_tag"],
                         "ingest_status": body_status, "aligned_with": rec["aligned_with"],
                         "segment_count": seginfo[rec["slug"]]["count"],
                         "segments_aligned": seginfo[rec["slug"]].get("aligned", False)})

    # Documents that were imported locally but have no row in the sheet.
    # They are real material the contributor collected deliberately, so they
    # are written out — but marked plainly, never folded in as if the sheet
    # had described them.
    import_status_path = os.path.join(cachedir, "_import-status.json")
    if os.path.exists(import_status_path):
        imp = json.load(open(import_status_path, encoding="utf-8"))
        orphan_dir = os.path.join(cachedir, "orphans")
        for o in imp.get("orphans", []):
            src = os.path.join(orphan_dir, o["slug"] + ".txt")
            if not os.path.exists(src):
                continue
            text = open(src, encoding="utf-8").read()
            fm = "\n".join([
                "---",
                "# --- identity ---",
                "title: %s" % yaml_scalar(o["file"]),
                "work_id: \"\"",
                "file_type: \"\"",
                "lang_tag: \"\"",
                "",
                "# --- provenance ---",
                "source_description: \"imported from a local .docx\"",
                "local_file: %s" % yaml_scalar(o["file"] + ".docx"),
                "sheet_row: null",
                "sheet_row_missing: true",
                "",
                "# --- workflow status ---",
                "ingest_status: with-body",
                "retrieved: %s" % retrieved,
                "status: draft",
                "---",
            ])
            body = "\n".join([
                "", "# %s" % o["file"], "",
                "> [Ed: this document was downloaded locally but has no matching row "
                "in the Pecha Upload List. Its identity, language, and relations are "
                "therefore unverified. Confirm against the sheet before promoting it "
                "out of the inbox.]", "",
                "## Text", "", text.rstrip(), "",
            ])
            os.makedirs(os.path.join(inboxdir, "unsorted"), exist_ok=True)
            path = os.path.join(inboxdir, "unsorted", o["slug"] + ".md")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(fm + "\n" + body)
            manifest.append({"slug": o["slug"], "path": path, "folder": "unsorted",
                             "sheet_row": None,
                             "work_id": "", "lang_tag": "",
                             "ingest_status": "with-body", "aligned_with": [],
                             "sheet_row_missing": True})
            counts["no-sheet-row"] = counts.get("no-sheet-row", 0) + 1

    mpath = os.path.join(inboxdir, "_manifest.json")
    with open(mpath, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    log("build: wrote %d files -> %s" % (len(manifest), inboxdir))
    log("build: %s" % ", ".join("%s=%d" % kv for kv in sorted(counts.items())))
    return mpath


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices=["fetch-sheet", "parse", "fetch-docs",
                                     "import-local", "build", "all"])
    p.add_argument("--sheet-id", default=DEFAULT_SHEET_ID)
    p.add_argument("--xlsx", default="", help="use this .xlsx instead of downloading")
    p.add_argument("--workdir", default="0-INBOX/raw-data/pecha-sheet")
    p.add_argument("--cachedir", default="", help="default: <workdir>/documents")
    p.add_argument("--inbox", default="0-INBOX/texts")
    p.add_argument("--delay", type=float, default=0.4, help="seconds between document fetches")
    p.add_argument("--refetch", action="store_true", help="re-download documents already cached")
    p.add_argument("--source", default=os.path.expanduser("~/Downloads"),
                   help="import-local: directory holding hand-downloaded .docx files")
    p.add_argument("--since", default="",
                   help='import-local: only files modified at/after this "YYYY-MM-DD HH:MM"')
    p.add_argument("--no-archive", action="store_true",
                   help="import-local: do not copy the source .docx into the vault")
    args = p.parse_args(argv)

    workdir = args.workdir
    cachedir = args.cachedir or os.path.join(workdir, "documents")
    records = os.path.join(workdir, "records.json")
    xlsx = args.xlsx or os.path.join(workdir, "pecha-upload.xlsx")

    if args.stage in ("fetch-sheet", "all") and not args.xlsx:
        xlsx = stage_fetch_sheet(args.sheet_id, workdir)
    if args.stage in ("parse", "all"):
        records = stage_parse(xlsx, workdir, args.sheet_id)
    if args.stage in ("fetch-docs", "all"):
        stage_fetch_docs(records, cachedir, args.delay, only_missing=not args.refetch)
    if args.stage == "import-local":
        stage_import_local(args.source, records, cachedir, args.since,
                           archive=not args.no_archive)
    if args.stage in ("build", "all"):
        stage_build(records, cachedir, args.inbox)
    return 0


if __name__ == "__main__":
    sys.exit(main())
