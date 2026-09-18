---
name: sheet-to-inbox
description: Ingest the "Pecha Upload List" Google Sheet into `0-INBOX/texts/` — one markdown file per text row, with the document body converted from its Google Doc or .docx, preserving the Word auto-numbering that carries the Tibetan–Chinese segment alignment plus footnotes and highlighting, and every sheet column, catalogue ID, and cross-language relation recorded in YAML frontmatter. Use whenever the sheet gains rows, changes status, or needs re-syncing into the vault.
---

# sheet-to-inbox

Turns the Tibetan/Chinese parallel-text tracking sheet into vault files. Each row of the sheet's `Pecha Upload` tab describes **one language version of one work** — a Tibetan Kangyur/Tengyur text or its Chinese counterpart — together with its catalogue numbers, workflow status, and a link to the Google Doc holding the actual text. This skill downloads the sheet, resolves the row structure into explicit records, fetches each linked document, and writes one inbox file per row.

The failure mode it prevents is **losing the relations**. The sheet encodes which Tibetan text pairs with which Chinese text positionally — an ID appears once in column A and the rows beneath it inherit it — so naive row-by-row extraction silently breaks the Bo↔Zh alignment that is the entire point of the dataset. This skill reconstructs those relations, writes them into every file as `aligned_with:`, and refuses to invent an ID it cannot derive.

Output lands in `0-INBOX/` and is therefore **scratch, never authoritative**. Files carry `status: draft`. Promoting a text to `1-SOURCES/` is a separate, human-directed step using `format-root-text` / `format-commentary` and the matching frontmatter skill.

---

## Inputs

| Input | Description | Default |
|---|---|---|
| Sheet ID | The Google Sheet to ingest. Its `Pecha Upload` tab must match the column order in `reference/sheet-schema.md`. | `1qXWMyWun6t2Nqya6SWPcHKVwk9AwYCtz5VUjYQOlAhU` |
| Google credentials | Needed only for documents not shared link-readable. See **Document access** below. | none (anonymous) |
| `openpyxl` | Python package used to read the `.xlsx` export with its hyperlinks intact. | must be installed |

If the sheet's column order has changed, stop and update `reference/sheet-schema.md` and `COLUMNS` in the script together — do not guess a new mapping mid-run.

## Output

| Path | Contents |
|---|---|
| `0-INBOX/texts/tibetan/<slug>.md` | Tibetan witnesses. `<slug>` = `<work-id>-<lang-tag>[-variant]`. |
| `0-INBOX/texts/chinese/<slug>.md` | Chinese witnesses, all scripts and variants. |
| `0-INBOX/texts/unsorted/<slug>.md` | Files with no language of their own (e.g. imported documents with no sheet row). |
| `0-INBOX/texts/aligned/<work-id>.md` | One bilingual table per work, pairing segments by `^sN` id. |
| `0-INBOX/texts/_manifest.json` | Every slug with its sheet row, work ID, language, ingest status, and aligned peers. |
| `0-INBOX/raw-data/pecha-sheet/pecha-upload.xlsx` | The downloaded sheet. |
| `0-INBOX/raw-data/pecha-sheet/records.json` | Parsed records — the intermediate the build stage reads. |
| `0-INBOX/raw-data/pecha-sheet/documents/<doc-id>.txt` | Document body cache, keyed by Google Doc ID. |
| `0-INBOX/raw-data/pecha-sheet/documents/_fetch-status.json` | Per-document fetch outcome and failure reason. |
| `0-INBOX/raw-data/pecha-sheet/documents/by-slug/<slug>.txt` | Text extracted from hand-downloaded `.docx` files, keyed by slug. |
| `0-INBOX/raw-data/pecha-sheet/documents/orphans/<slug>.txt` | Imported documents with no matching sheet row. |
| `0-INBOX/raw-data/pecha-sheet/documents/original/<name>.docx` | The hand-downloaded originals, archived unchanged. |
| `0-INBOX/raw-data/pecha-sheet/documents/_import-status.json` | What each local file matched, and everything that did not match. |

---

## Output file format

```markdown
---
# --- identity ---
title: <name_long, else name_short, else name_en>
title_short: <column D>
title_long: <column E>
title_en: <column F>
work_id: toh4054-tai1606-1
file_type: root-text | commentary | translation
language: Tibetan | Classical Chinese | Chinese | Modern Chinese
lang_tag: bo | zh | zh-hant | zh-hans | zh-modern
edition_variant: "" | simplified | traditional | modern | with-footnote | without-footnote

# --- catalogue ids ---
toh: toh4054
taisho: tai1606
bdrc_work_id: WA0RT3393-1
root_bdrc_work_id: WA0RK0056-2
pecha_id: I83E829AF
pecha_no: "I83E829AF - <title as recorded in the sheet>"

# --- authorship ---
author: <column J, original script>
author_en: <column K>

# --- classification ---
category: "4.1. 唯識宗阿毗達磨釋論"
category_code: "4.1"
category_en: 4 Mind-only Treatises
category_bo: 4 སེམས་ཙམ།
category_lzh: 4. 唯識

# --- segmentation ---
segment_count: 21
segment_scheme: word-auto-numbering | none
peer_segment_counts:
  toh0028-zh: 21
segments_aligned: true

# --- relations ---
aligned_with: [toh4054-tai1606-1-zh]
work_group: gold-standard | kumarajiva | kangyur-translations | zhengchi
cluster_id: <the column-A ID this row inherits>
toh_column_raw: <column G verbatim>

# --- provenance ---
source_description: CBETA | Esukhia | བཀའ་འགྱུར། | <url>
source_url: <column L link, when it is a url>
document_link: https://docs.google.com/document/d/<id>/edit
document_title: <the link text shown in the sheet>
google_doc_id: <id>
sheet_id: <sheet this came from>
sheet_row: 6
work_id_source: column-a | doc-title | column-g | none

# --- workflow status ---
pecha_status: Ready | Staging | Published | Blocked | Pased | fodian.org | Needs improvement | Alignment Checking
alignment_status: Alignment Checking | Ready
alignment_file: <name or url of the alignment spreadsheet/folder>
alignment_file_url: <url when column Q is a link>
data_prep: <column C>
ingest_status: with-body | link-restricted | no-link
retrieved: YYYY-MM-DD
lang_mismatch: <only when column M and the document title disagree>

# --- sheet remarks ---   (only when the sheet has any)
remarks:
  todo_kv: ...
  same_segmentation: ...
status: draft
---

# <title>

*<English title, when distinct>*

## Relations

- Aligned language versions: [[toh4054-tai1606-1-zh]]
- Toh: `toh4054`
- Taishō: `tai1606`
- Source document: [<document title>](<url>)

## Text

1. <segment one> ^s1
2. <segment two, carrying a footnote>[^1] ^s2
3. <segment three, with ==flagged text==> ^s3

[^1]: <footnote text>
```

When the body could not be retrieved, the `## Text` section holds a single editorial note instead:

```markdown
> [Ed: body not retrieved — `ingest_status: link-restricted`. Re-run the `fetch-docs` stage once the document is readable.]
```

---

## Annotations — what the body preserves

The source documents carry an annotation layer that a naive text extraction
destroys. `docx_to_markdown.py` (standard library only) preserves it:

| Annotation | In the source | In the output | Why it matters |
|---|---|---|---|
| **Segment numbering (Word)** | Word auto-numbering (`<w:numPr>` + `numbering.xml`) — generated by a counter, present **nowhere** in the text runs | `3. <text> ^s3` — the number visibly, plus an Obsidian block ID | **This is the Tibetan–Chinese alignment.** Paired witnesses carry the same segment count, so segment *n* of the Tibetan corresponds to segment *n* of the Chinese. Reading only `<w:t>` discards the whole alignment layer while appearing to succeed. |
| **Segment numbering (typed)** | The number typed into the text: `12. …` | `^s12` appended; the number is already in the text | The same alignment layer in a second notation. A **bare `12.` with no text is an empty segment holding an alignment slot open** and must be counted — miss those and the two witnesses stop matching (Toh555/Tai665 has 172 empty slots in the Chinese and 70 in the Tibetan, reaching 8539 segments in both). |
| **Footnotes** | `word/footnotes.xml` + `<w:footnoteReference>` | `[^1]` inline, definitions at the end | Scholarly notes citing Tibetan originals and open questions — irreplaceable. |
| **Highlighting** | `<w:highlight>` | `==text==` | Marks passages someone flagged. |
| **Inline markers** | Literal text, e.g. `{D4054-A approx 117a.6-178b.}` | Unchanged | Derge folio references and segment braces are already plain text. |
| **Tabs / line breaks** | `<w:tab/>`, `<w:br/>` | Preserved within the paragraph | |

Cross-language addressing works directly off the block IDs:
`[[toh0028-zh#^s5]]` from the Tibetan file reaches segment 5 of the Chinese.

**There are no Word Heading styles or TOC fields anywhere in this corpus** — the
structure *is* the numbered segmentation. Do not synthesise headings the source
does not have; a TOC is added later, in `1-SOURCES/`, by the `add-toc` skill.

`.docx` is requested in preference to `text/plain` for exactly this reason:
the plain-text export renders numbering inconsistently and drops footnotes and
highlighting entirely.

**Typed numbering is only recognised as a scheme when it is genuinely
sequential** — at least five numbers, at least 80% of them one greater than
the last. That keeps an incidental numbered list inside prose from being
mistaken for segmentation.

Each file records what it found:

```yaml
segment_count: 21
segment_scheme: word-auto-numbering | literal-numbering | none
peer_segment_counts:
  toh0028-zh: 21
segments_aligned: true                # every aligned peer has the same count
```

`segments_aligned: false` on a pair with bodies on both sides means the two
witnesses disagree about segmentation — report it, do not reconcile it.

---

## Rules

1. **Never write outside `0-INBOX/`.** This skill does not touch `1-SOURCES/`, `2-RAILS/`, or `3-TRANSFORMATIONS/`. Inbox output is scratch and is never cited from elsewhere.
2. **Every file carries `status: draft`.** Nothing this skill produces is authoritative. Only a human contributor promotes a text out of the inbox.
3. **Column M is authoritative for language.** A document-link title may refine the language within its own family (Classical → simplified Chinese) but may never change it across families. When the title's `_bo` / `_zh` suffix contradicts column M, record `lang_mismatch:` and keep column M's value. Do not silently pick one.
4. **Never invent a work ID.** The ID cascade is: an ID embedded in the document-link title → the cluster ID inherited from column A → the Toh number in column G. If all three fail, leave `work_id` empty and slug the file `row<N>`; do not guess from the title text.
5. **Relations come from shared work IDs only.** `aligned_with` lists exactly the other rows carrying the same `work_id`. Do not infer alignment from similar titles or adjacent rows.
6. **A row standing on inherited ID alone claims no alignment.** Column A's ID is inherited by the rows beneath it, but that inheritance is wrong once the rows have moved on to a different work. Two signals correct it: a *different* Toh number in column G starts a new cluster (column G is real sheet data, so it wins); otherwise the row is marked `cluster_uncertain: true` and its `aligned_with` is emptied. Where the sheet leaves the Tibetan rows untitled, which Tibetan row belongs with which Chinese row is not recoverable — record the uncertainty and leave it for a human, never invent sub-clusters to paper over it.
7. **Preserve the sheet verbatim in frontmatter.** Derived fields (`category_en`, `toh`, `work_id`) sit *alongside* the raw cell values (`category`, `toh_column_raw`, `cluster_id`), never in place of them. A reader must be able to recover what the sheet actually said.
8. **Never flatten the annotation layer.** Segment numbers, footnotes and highlighting are content, not formatting. A body extracted without them is not a lesser version of the document — it is a different one, missing the alignment. Never emit a body from `<w:t>` alone.
9. **Never fabricate a document body.** A text that could not be downloaded gets the editorial note and an honest `ingest_status`. Do not substitute a body from another source, and do not translate or summarise.
10. **The document cache is keyed by Google Doc ID and is re-used.** `fetch-docs` skips documents already cached unless `--refetch` is passed, so re-running the pipeline after a metadata fix costs no downloads.
11. **Collapse duplicate downloads by extracted text, never by bytes.** `.docx` zips embed modification timestamps, so two byte-different files routinely hold identical text. Compare the extraction; when copies genuinely differ, report both rather than silently picking one.
12. **An imported file that matches no sheet row is never folded in.** It is written with `sheet_row: null`, `sheet_row_missing: true`, and an editorial note saying its identity and relations are unverified. Do not guess which row it belongs to.
13. **Never pair segments by position.** The alignment file joins witnesses on their `^sN` ids. A blank cell means that witness has no segment with that id — it is not evidence of correspondence, and must never be filled by sliding rows together.
14. **Language folders are routing, not judgement.** A record goes to `tibetan/` or `chinese/` by its `lang_tag`, which comes from column M. A record with no language goes to `unsorted/`; do not guess one from the content.
15. **Column G is headed "Commentary of (Toh number)" but is used as the Toh anchor** for the row's own work, not as a commentary relation. Emit it as `toh:` plus the verbatim `toh_column_raw:`; do not read a commentary relation out of it.

---

## Procedure

### Step 1 — Preconditions

1. Confirm `openpyxl` is importable: `python3 -c "import openpyxl"`. If not, `pip install openpyxl`.
2. Decide whether authenticated document access is needed (see **Document access**). Anonymous access is enough for link-readable documents.

### Step 2 — Download the sheet

```bash
python3 4-SYSTEM/Skills/sheet-to-inbox/sheet_to_inbox.py fetch-sheet
```

Writes `0-INBOX/raw-data/pecha-sheet/pecha-upload.xlsx`. If the response is not a `.xlsx` the sheet is not link-readable — export it by hand and pass `--xlsx <path>` to the next step.

### Step 3 — Parse rows into records

```bash
python3 4-SYSTEM/Skills/sheet-to-inbox/sheet_to_inbox.py parse
```

This stage does all the structural reasoning:

a. Skips rows 1–4 (banner and header rows).
b. Detects **group banner rows** — a title in column D with no language, document link, long name, or category — and assigns the following rows to that group.
c. Carries the **column-A cluster ID** down through the rows that inherit it, ignoring cells that hold a stray source URL instead of an ID. A differing Toh number in column G breaks the inheritance and starts a new cluster; a row inheriting with no corroboration of its own is flagged `cluster_uncertain: true` and claims no alignment.
d. Derives each row's **work ID** by the cascade in Rule 4, normalising to lowercase with `_` → `-` and any trailing `_bo` / `_zh` marker removed.
e. Resolves **language** from column M per Rule 3.
f. Maps the **category** to its Tibetan / English / Classical-Chinese labels via the taxonomy in `reference/sheet-schema.md`.
g. Links **aligned peers**: rows sharing a work ID.
h. Assigns a unique **slug** per row, appending `-2`, `-3` … on collision.

Review the reported counts before continuing. Language totals and group totals must match the sheet; investigate any row reported with `work_id_source: none`.

### Step 4 — Fetch the documents

```bash
python3 4-SYSTEM/Skills/sheet-to-inbox/sheet_to_inbox.py fetch-docs
```

For each linked document: anonymous export first, then the Drive API with a Bearer token if one is available. Results are cached and every failure is recorded with its reason in `_fetch-status.json`. Re-run after fixing access — cached documents are skipped.

### Step 4b — Import documents downloaded by hand

Documents that `fetch-docs` could not reach can be downloaded manually — in a
browser already signed in to the right Google account — and imported:

```bash
python3 4-SYSTEM/Skills/sheet-to-inbox/sheet_to_inbox.py import-local \
    --source ~/Downloads --since "YYYY-MM-DD HH:MM"
```

`--since` confines the scan to one download session, so unrelated files sitting
in the folder are ignored.

Each `.docx` is converted by `docx_to_markdown.py` (standard library only — a
`.docx` is a zip whose `word/document.xml` holds the content; no pandoc or
`python-docx` needed), preserving the annotation layer described above. Files
are then matched to records by:

a. **exact title** — the filename against the sheet's document-link text;
b. **`Toh<N>-Tai<M>《…》<PP>_<lang>`** → work ID `toh<N>-tai<M>-<PP>`;
c. **`T<M>-<P>_<name>_<lang>`** → the record whose work ID ends `tai<M>-<P>`.

A pattern that matches more than one record is reported as ambiguous and
imported for none of them.

Browsers append ` (1)` to a repeated download. Such copies are collapsed only
when their **extracted text** is identical — `.docx` zips embed timestamps, so
byte comparison would wrongly call identical documents different. When two
copies genuinely differ, both are reported and the longer extraction is kept.

Imported text goes to `documents/by-slug/<slug>.txt`, which `build` reads just
like a downloaded document — so a hand-collected corpus and an API-fetched one
produce identical output.

### Step 5 — Build the inbox files

```bash
python3 4-SYSTEM/Skills/sheet-to-inbox/sheet_to_inbox.py build
```

Writes one file per record to `0-INBOX/texts/` plus `_manifest.json`. Offline and idempotent — safe to re-run after any metadata correction.

### Step 6 — Write the bilingual alignment

```bash
python3 4-SYSTEM/Skills/sheet-to-inbox/sheet_to_inbox.py align
```

Writes `0-INBOX/texts/aligned/<work-id>.md` for every work that has both a
Tibetan and a Chinese witness carrying segments: one table, one row per
segment id, one column per witness.

**Pairing is by segment id, never by position.** Where one witness has an id
the other lacks, the cell is left blank and the file carries an editorial note
naming the disagreeing counts. Forcing two differently-segmented witnesses
into the same row count would manufacture an alignment the sources do not
support. Works flagged `cluster_uncertain` are excluded entirely.

The whole chain is also available as `sheet_to_inbox.py all`.

### Step 7 — Report

Report to the human contributor:
- counts by `ingest_status` (`with-body` / `link-restricted` / `no-link`);
- every row flagged `lang_mismatch`;
- every row with `work_id_source: none`;
- any document whose fetch failed, with the recorded reason.

Do not mark the ingest complete while documents remain unfetched — say plainly which ones are missing and why.

---

## Document access

Documents shared "anyone with the link" export anonymously and need no setup. The rest return `401` and are reported as `ingest_status: link-restricted`.

To fetch restricted documents, grant a Drive read scope once, as the account the documents are shared with:

```bash
gcloud auth application-default login --scopes=https://www.googleapis.com/auth/drive.readonly,https://www.googleapis.com/auth/cloud-platform
```

Then re-run `fetch-docs`; the script picks the token up automatically via `gcloud auth application-default print-access-token`. A token without the Drive scope fails with `insufficient authentication scopes` — that is reported per document, not silently swallowed.

If `GOOGLE_APPLICATION_CREDENTIALS` is set in the environment (gcloud warns about this during login), it points gcloud at a service-account key that will shadow the user credentials just created — and that service account almost certainly cannot see documents shared with a person. The script clears the variable for its own token subprocess, so no action is needed; but if a token is obtained by other means, unset it first.

Sign in as the account the documents are actually shared with. A successful login as the wrong account still yields a valid token, and every restricted document then fails with `drive-api-404` rather than anything that names the real cause.

**Uploaded `.docx` files behave differently from native Google Docs.** A link carrying `rtpof=true` points at a Word file stored in Drive, not a Google Doc; `/document/d/<id>/export?format=txt` does not serve those and returns a sign-in page regardless of sharing. Retrieve them with the Drive API (`files/<id>?alt=media`) or download them by hand and use `import-local`.

The alternative, when only a few documents are restricted, is to open each in a browser and use **File → Download → Plain text**, saving it to `0-INBOX/raw-data/pecha-sheet/documents/<google-doc-id>.txt`; `build` then picks it up like any cached document.

---

## Completion check

- [ ] `0-INBOX/raw-data/pecha-sheet/pecha-upload.xlsx` downloaded (or supplied via `--xlsx`)
- [ ] `records.json` written, with group and language totals matching the sheet
- [ ] No record has `work_id_source: none` (or each one is reported to the contributor)
- [ ] No duplicate slugs in `_manifest.json`
- [ ] Every record's `aligned_with` lists exactly its same-`work_id` peers, and rows flagged `cluster_uncertain` list none
- [ ] Rows flagged `cluster_uncertain` reported to the contributor as sheet rows needing an ID
- [ ] `fetch-docs` run, with every failure carrying a recorded reason
- [ ] One `0-INBOX/texts/<slug>.md` written per record, each with `status: draft`
- [ ] Files without a body carry the editorial note and an honest `ingest_status` — never invented content
- [ ] Bodies retain segment numbering (`^sN`), footnotes and highlighting — never `<w:t>` text alone
- [ ] Every aligned pair with bodies on both sides is `segments_aligned: true`, or the mismatch is reported
- [ ] Any locally imported files reported: matched, ambiguous, text-conflicting, unreadable, and without a sheet row
- [ ] Source `.docx` archived under `documents/original/`
- [ ] Every record filed under `tibetan/`, `chinese/` or `unsorted/` by its `lang_tag`
- [ ] An alignment file written for every work with a segment-bearing Tibetan and Chinese witness, and every count disagreement carrying its editorial note
- [ ] Counts by `ingest_status`, `lang_mismatch` rows, and fetch failures reported to the contributor
