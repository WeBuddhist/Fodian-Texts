# Pecha Upload List — sheet schema

Reference for the `sheet-to-inbox` skill. Describes the source spreadsheet as it actually is, including the irregularities the parser has to absorb. When the sheet changes shape, update this file and `COLUMNS` in `sheet_to_inbox.py` in the same commit.

Sheet: `1qXWMyWun6t2Nqya6SWPcHKVwk9AwYCtz5VUjYQOlAhU`
Tabs: **`Pecha Upload`** (the data) and **`Categories`** (hidden; an `IMPORTRANGE` of the Pecha Categories master sheet).

---

## 1. Row layout

| Rows | Role |
|---|---|
| 1 | Super-header. `ཡིག་ཆ།` ("document") spans A–B; `རྩ་བ།` ("root text") spans G–H. This is what tells you column H is the *root's* BDRC ID, not the document's. |
| 2 | Sheet title and a link to the S.O.P. documents. |
| 3 | English column headers. |
| 4 | Chinese column headers (圓滿法藏編號, 文本準備負責人, …). |
| 5+ | Data, interrupted by group banner rows. |

**Group banner rows** carry a title in column D and nothing that identifies a text — no language, document link, long name, or category. They *do* often carry column C (`data_prep`) and column R (`align_status`), so those columns cannot be used to detect them.

| Row | Banner | Slug |
|---|---|---|
| 5 | 對讀項目_尚待Parsing_Gold Standard | `gold-standard` |
| 122 | Kumarajiva | `kumarajiva` |
| 192 | Kumarajiva Kangyur Translations 新譯佛典藏漢對讀(宛真) | `kangyur-translations` |
| 241 | 正持法師- For Kumarajiva | `zhengchi` |

---

## 2. Columns

| Col | English header | Chinese header | Field in `records.json` | Notes |
|---|---|---|---|---|
| A | Kumarajive No. | 圓滿法藏編號 | `kumarajiva_no` → `cluster_id` | The work ID. Appears **once** per work and is inherited by the rows beneath it. Occasionally holds a stray source URL (an `online.adarshah.org` link) instead of an ID — those cells are discarded. |
| B | BDRC Work | | `bdrc_work` | BDRC ID of *this document*. |
| C | Data Preparation | 文本準備負責人 | `data_prep` | Person responsible. Also filled on banner rows. |
| D | Tibetan/Chineses Sutra Name (Short) | 藏/中經名（短） | `name_short` | Often has the work ID appended; the parser strips it. |
| E | Tibetan/Chiness Sutra Name (Long) | 藏/中經名（長） | `name_long` | |
| F | English Sutra Name | 英文經名 | `name_en` | Usually only on the Tibetan row of a pair. |
| G | Commentary of (Toh number) | | `toh_column` → `toh` | **Headed "Commentary of" but used as the Toh anchor of the row's own work.** Do not read a commentary relation out of it. |
| H | BDRC Work | | `root_bdrc` | Sits under the `རྩ་བ།` super-header — the *root text's* BDRC ID. |
| I | Category | | `category` | See §4. |
| J | Author (Tibetan/Chinese) | 作者（藏/繁） | `author_orig` | e.g. `སངས་རྒྱས་བཅོམ་ལྡན་འདས།` / `佛世尊`. |
| K | Author (English) | 作者（英文） | `author_en` | |
| L | Source: URL or site name | 資料來源:網址或站名 | `source`, `source_url` | `CBETA`, `Esukhia`, `བཀའ་འགྱུར།`, or a URL. |
| M | Bo/Zh/Modern ZH | 文體(藏/繁/簡） | `lang_column` → `lang_tag` | **Authoritative for language.** See §3. |
| N | Document link | 文檔連結 | `doc_link` → `doc_url`, `doc_title` | A hyperlink to a Google Doc. In the `gold-standard` group the cell text *is* the raw URL; elsewhere it is a filename that also encodes the work ID and language. |
| O | Pecha no. | Pecha 序號 | `pecha_no` → `pecha_id` | `I83E829AF - <title>`. The ID is the part before the dash. |
| P | Pecha Status | 處理階段 | `pecha_status` | See §5. |
| Q | Alignment File | 對讀檔案料夾 | `align_file`, `align_file_url` | A folder name, or a link to the alignment spreadsheet. |
| R | Alingment Status *(sic)* | 對讀階段 | `align_status` | `Alignment Checking` or `Ready`. Also filled on banner rows. |
| S–X | todo KV · todo Drupchen · remark GZ · same segmentation · segmentation of simplified Chinese translation · 陳/黃 remarks | | `remarks.*` | Free-text working notes; emitted only when non-empty. |

---

## 3. Language column (M)

| Cell value | `lang_tag` | `language` | `edition_variant` |
|---|---|---|---|
| `Bo` | `bo` | Tibetan | |
| `ZH` / `Zh` | `zh` | Classical Chinese | |
| `ZH Traditional` | `zh-hant` | Classical Chinese | traditional |
| `簡` | `zh-hans` | Chinese | simplified |
| `ZH Modern` | `zh-modern` | Modern Chinese | modern |
| `註腳 with footnote` | `zh` | Classical Chinese | with-footnote |

The document-link title may carry its own markers (`_simplified_`, `_with footnote`, `_without footnote`). These refine the variant **only within the language column M already declares** — a title marker never moves a row between Tibetan and Chinese.

**Known inconsistency:** row 130 is marked `ZH` in column M but links to a document whose title ends `_bo.docx`. The parser keeps column M's value and records the disagreement as `lang_mismatch:` in the output file.

---

## 4. Category taxonomy

From the hidden `Categories` tab, which imports the Pecha Categories master sheet in four languages (BO / EN / LZH / ZH).

| Code | Tibetan | English | Classical Chinese |
|---|---|---|---|
| 1 | མདོ་སྡེ། | Discourses | 經部 |
| 2.1 | ཤེར་ཕྱིན་གྱི་མདོ། | Discourses on the Perfection of Wisdom | 般若經與相關釋論 |
| 2.2 | ཤེར་ཕྱིན་གྱི་བསྟན་བཅོས། | Treatises on the Perfection of Wisdom | 般若論典 |
| 3 | དབུ་མ། | Middle Way | 中觀 |
| 4 | སེམས་ཙམ། | Mind-only Treatises | 唯識 |
| 5 | མངོན་པ། | Systematic Treatises | 阿毘達磨 |
| 6 | རྒྱུད་སྡེ། | Tantras | 密續 |
| 7 | ཚད་མ། | Logic | 因明邏輯 |
| 8 | ཞལ་འདོན། | Liturgy | 實修儀軌 |
| 9.1 | བློ་སྦྱོང་། | Mind Trainings | 修心方法 |
| 9.2 | བསླབ་བྱ། | Advices | 修身教法 |
| 10.1 | ལོ་རྒྱུས། | History | 歷史與傳記 |
| 10.2 | སྒྲུང་། | Stories | 佛教故事 |
| 11 | གསོ་བ་རིག་པ། | Medicine | 醫方明 |
| 12.1 | འདུལ་བའི་མདོ། | Discourses on Monastic Rules | 律經 |
| 12.2 | འདུལ་བའི་བསྟན་བཅོས། | Treatises on Monastic Rules | 律部論典 |
| 13 | རིག་གནས། | Linguistics Treatises | 佛教語言學論典 |
| 14 | སྣ་ཚོགས། | Miscellaneous | 其他 |

Branches `2`, `9`, `10`, `12` are marked "don't use" at the top level in the master sheet — only their sub-codes are selectable.

The data uses sub-codes the taxonomy leaves blank (e.g. `4.1. 唯識宗阿毗達磨釋論`). The parser matches the exact code first, then falls back to the parent branch, so `4.1` inherits the labels of branch `4`.

`file_type` is derived from the branch: `2.2, 3, 4, 5, 7, 12.2, 13` → `commentary`; `zh-modern` rows → `translation`; everything else → `root-text`.

---

## 5. Status vocabularies

**`pecha_status` (column P)** — where the text sits in the upload pipeline:

| Value | Meaning as used in the sheet |
|---|---|
| `Pased` *(sic — "Parsed")* | Parsed, awaiting the next step |
| `Staging` | In the staging environment |
| `Ready` | Ready to publish |
| `Published` | Live |
| `fodian.org` | Published at fodian.org (cell links there) |
| `Blocked` | Held up |
| `Needs improvement` | Requires rework |
| `Alignment Checking` | Status column reused to mirror the alignment stage |

**`align_status` (column R)** — `Alignment Checking` for almost every row; `Ready` for a small number.

---

## 6. The work-ID cascade

The per-row ID is derived in this order, and the choice is recorded as `work_id_source`:

1. **`doc-title`** — an ID embedded in the document-link title.
   - `《大寶積經》菩薩藏會-玄奘 toh56to57-tai310-002_zh` → `toh56to57-tai310-002`
   - `Toh0023_kp0002_一切如來母一字般若波羅蜜多經_bo.docx` → `toh0023-kp0002`
2. **`column-a`** — the cluster ID inherited from column A, normalised (`Toh0023_kp0002_` → `toh0023-kp0002`).
3. **`column-g`** — the Toh number, when nothing better exists.
4. **`none`** — no ID derivable. The row is slugged `row<N>` and must be reported to a human.

**Inheritance breaks.** Column A's ID carries down, but rows 247–256 show why that cannot be trusted blindly: rows 254–256 are the Diamond Sūtra (金剛經, column G `Toh 16`) sitting under an inherited `Toh0115`, and rows 249–253 are three further sūtras (佛說八大人覺經, 四十二章經, 佛垂般涅槃略說教誡經) with no ID of their own at all. A differing column-G Toh number starts a new cluster. Everything else inheriting without corroboration is flagged `cluster_uncertain: true` and claims no alignment — the Tibetan rows there are untitled, so their pairing is not recoverable from the sheet. **Eight rows (247–253) are in this state and need IDs adding to the sheet.**

Normalisation: lowercase, `_` → `-`, trailing separators and any trailing `_bo` / `_zh` language marker removed.

**Watch the underscore.** `\b` does not fire between `3` and `_` in `Toh0023_kp0002_`, because `_` is a word character — the catalogue-number patterns use an explicit non-digit lookahead instead.

---

## 7. Relations

| Relation | How it is carried |
|---|---|
| **Bo ↔ Zh alignment** | Rows sharing a `work_id`. Written to every file as `aligned_with:`. This is the relation the dataset exists to record. |
| **Text → root text** | `root_bdrc` (column H), under the `རྩ་བ།` super-header. |
| **Text → its own catalogue entries** | `toh` (column G), `taisho` (parsed from the work ID), `bdrc_work` (column B), `pecha_id` (column O). |
| **Text → working group** | `work_group`, from the banner row above it. |
| **Text → alignment artefact** | `alignment_file` / `alignment_file_url` (column Q). |

A work split into parts (e.g. `toh56to57-tai310-002` … `-008`) gets one ID per part, and each part's Tibetan and Chinese rows align to each other — not across parts.

---

## 7a. Two kinds of document link

Column N mixes two things that need different retrieval:

| Link shape | What it is | How to retrieve |
|---|---|---|
| `/document/d/<44-char id>/edit` | A **native Google Doc** | `…/export?format=txt` — works anonymously when link-readable |
| `/document/d/<33-char id>/edit?…rtpof=true&sd=true` | A **`.docx` uploaded to Drive**, not converted | `export?format=txt` returns a sign-in page whatever the sharing. Use the Drive API (`files/<id>?alt=media`) or download by hand and run `import-local`. |

The `rtpof=true` parameter (and a shorter file ID) is the tell. All the `simplified_zh` variants in the `kumarajiva` group are uploaded `.docx` — they were the last 11 documents left unreachable after the first ingest.

---

## 7b. The annotation layer in the documents

Surveyed across the 110 documents collected on 2026-09-18:

| Feature | Files | Total | Notes |
|---|---|---|---|
| Word auto-numbering (`<w:numPr>`) | 58 | 13,457 numbered paragraphs | **The segmentation, and the Tibetan–Chinese alignment.** Single-level, `decimal`, `lvlText` `%1.`, `start=1`. The numbers exist only as a numbering definition plus a counter — they are in no text run. |
| Typed numbering (`12. …`) | 51 | ~60,000 segments | The same alignment layer, typed into the text instead. A bare `12.` is an empty segment holding an alignment slot open. |
| Footnotes (`word/footnotes.xml`) | 10 | 233 | Scholarly notes, frequently citing the Tibetan original for a Chinese rendering. |
| Highlighting (`<w:highlight>`) | 7 | — | Flagged passages. |
| Brace markers `{…}` | 24 | 479 | Literal text. Derge folio references (`{D4054-A approx 117a.6-178b.}`) and segment braces. 3 files have unbalanced braces **in the source**. |
| Embedded Tibetan fonts | 9 | — | Jomolhari, Uchen. |
| Heading styles | **0** | 0 | There are none. |
| Word TOC fields | **0** | 0 | There are none. |
| Bookmarks, comments, tables, tracked changes | **0** | 0 | None. |

Paired witnesses carry matching segment counts — Toh0137 has 700 in both
Tibetan and Chinese, Toh0037 has 425 in both, Toh555/Tai665 has 8539 in both
— which is what makes segment *n* of one the counterpart of segment *n* of
the other.

**Both notations must be read.** 58 documents number through Word, 51 type the
number in. Reading only one notation leaves most of the corpus unsegmented.

Because there are no headings or TOC fields, **the numbered segmentation is the
only structure these documents have.** A TOC is added later, in `1-SOURCES/`,
by the `add-toc` skill; it is not recoverable from the `.docx`.

---

## 8. Observed shape (ingest of 2026-09-16)

209 text rows in 4 groups; 136 carry a Google Doc link.

| Group | Rows | Predominant status |
|---|---|---|
| `gold-standard` | 108 | Ready (56), Pased (20), fodian.org (16), Staging (14) |
| `kumarajiva` | 54 | Staging (14), Blocked (13), fodian.org (10), Published (6) |
| `kangyur-translations` | 32 | fodian.org (18), Staging (14) |
| `zhengchi` | 15 | Staging (8), Alignment Checking (6) |

By language: `bo` 93 · `zh` 99 · `zh-hans` 9 · `zh-modern` 6 · `zh-hant` 2.
By type: root-text 177 · commentary 26 · translation 6.
