---
name: inbox-to-sources
description: Promote reviewed inbox texts into `1-SOURCES/` — one Tibetan root text per work in `Text/`, one file per distinct Chinese edition in `Translations/`, with multi-document works joined into chapters, block IDs restamped into the vault's `^chapter-verse` scheme, every Chinese segment preceded by a transclusion of its Tibetan counterpart, and the sheet's metadata carried into frontmatter. Use after the inbox files have been checked by a human.
---

# inbox-to-sources

`0-INBOX/texts/` holds one file per **sheet row**. `1-SOURCES/` holds one file per **text**. This skill performs that change of unit: a work spread across five documents becomes one file with five chapters; a translation that exists both with and without footnotes becomes one file with a `footnotes:` field; the flat `^sN` inbox anchors become the vault's `^chapter-verse` block IDs; and each Chinese segment gains a transclusion of the Tibetan segment it renders.

The failure mode it prevents is **a plausible-looking alignment that is not real**. Segments are joined by ID, never by position, so a Chinese segment with no Tibetan counterpart gets no transclusion and the file says so. Silently sliding rows together to make the counts match would produce a file that reads as a careful bilingual edition while asserting correspondences no source supports.

Output is `status: draft`. Promotion to `ingested` is a human decision.

> **Write permission.** `4-SYSTEM/CLAUDE.md` §2 records `1-SOURCES/` as LLM-no-write, "only metadata additions via skill workflows". This skill *is* that workflow, and it was commissioned for this purpose. It still never edits an existing `1-SOURCES/` file in place — it writes whole files from inbox material that a human has already reviewed.

---

## Inputs

| Input | Description | Default |
|---|---|---|
| Parsed records | Output of `sheet-to-inbox`'s `parse` stage. | `0-INBOX/raw-data/pecha-sheet/records.json` |
| Inbox manifest | Output of `sheet-to-inbox`'s `build` stage. | `0-INBOX/texts/_manifest.json` |
| Inbox text files | The `0-INBOX/texts/{tibetan,chinese}/*.md` bodies, with `^sN` anchors. | — |

Run `sheet-to-inbox` first. This skill reads only the inbox; it never re-downloads anything.

## Output

| Path | Contents |
|---|---|
| `1-SOURCES/Text/bo-<toh>-<slug>.md` | One Tibetan root text per work. |
| `1-SOURCES/Translations/<tag>-<toh>-<slug>.md` | One file per distinct Chinese edition; `<tag>` is `zh-hant`, `zh-hans` or `zh-modern`. |
| `0-INBOX/raw-data/pecha-sheet/sources-plan.json` | The grouping decision, written by `plan`. |
| `0-INBOX/raw-data/pecha-sheet/sources-write-report.json` | Per-file segment counts, transclusion gaps, footnote state. |

---

## Output file format

**Root text** — `1-SOURCES/Text/bo-<toh>-<slug>.md`

```markdown
---
title: <Tibetan title>
alt_titles:
  - zh: <Chinese title>
  - en: <English title>
author: <Tibetan>
author_in_english: <English>
language: Tibetan
script: Unicode Tibetan
file_type: root-text
lang_tag: bo
chapters: 5
total_verses: 2847
verse_id_format: chapter-verse
toh: toh4054
taisho: tai1606
kp_id: kp2
work_id: toh4054-tai1606-1
bdrc_work_id: WA0RT3393-1
root_bdrc_work_id: WA0RT3393-1
pecha_id: I83E829AF
category: "4.1. 唯識宗阿毗達磨釋論"
category_code: "4.1"
category_en: 4 Mind-only Treatises
source_description: Esukhia
sheet_id: <sheet>
sheet_rows: [6, 8, 10, 12, 14]
parts: [toh4054-tai1606-1, …]
promoted_from: [toh4054-tai1606-1-bo, …]
promoted: YYYY-MM-DD
status: draft
---

# <Tibetan title>

*<English title>*

## <title> — 1/5 ^1-0

<segment> ^1-1

<segment> ^1-2
```

**Translation** — `1-SOURCES/Translations/zh-<toh>-<slug>.md`

```markdown
---
title: <Chinese title>
alt_titles:
  - bo: <Tibetan title>
  - en: <English title>
file_type: translation
lang_tag: zh-hant | zh-hans | zh-modern
edition_class: classical | simplified | modern
chinese_register: literary | modern
script: Traditional Chinese | Simplified Chinese
footnotes: true
root_text: 1-SOURCES/Text/bo-<toh>-<slug>.md
covers_verses: "1-1–5-2847"
superseded_witnesses: [toh0158-kp0013-zh-without-footnote]
status: draft
---

# <Chinese title>

## <title> ^1-0

![[1-SOURCES/Text/bo-<toh>-<slug>.md#^1-1]]

<Chinese segment> ^1-1
```

When the document's footnote content contradicts the sheet's label, two extra fields appear:

```yaml
footnotes: false
footnotes_sheet_label: true
footnotes_note: "the sheet labels this witness differently from what the document contains"
```

---

## Rules

1. **Block IDs follow `4-SYSTEM/CLAUDE.md` §5 and §5a.** `^chapter-verse`, chapter = part ordinal (1 for a single-document work), verse = segment number within that part. `##` headings take `^N-0`; the `#` title takes no block ID; nothing is zero-padded.
2. **An empty Chinese segment is dropped, not transcluded.** The Chinese witnesses keep an empty numbered slot wherever the Tibetan has a segment they do not render — that is how the source documents hold the alignment. Carried into Obsidian verbatim, each blank would pull in a Tibetan transclusion the Chinese does not translate. Drop the empty segments; the survivors keep their true IDs, so segment 9 still aligns with Tibetan segment 9 even when 1–8 are gone. A Tibetan segment with no Chinese counterpart is simply not transcluded anywhere.
3. **Segment identity is line position, and `segment_count:` is authoritative.** Read exactly that many lines from the inbox `## Text` section. Trimming trailing blank lines instead drops a genuinely empty final segment and shifts nothing visible — an off-by-one that only surfaces later as a misaligned transclusion.
4. **Literary and modern Chinese are different texts.** `zh-hant` (literary, traditional script), `zh-hans` (simplified) and `zh-modern` each get their own file, named by that tag and carrying `chinese_register:` and `script:` in frontmatter, so a reviewer can tell at a glance which they are reading. Only footnoted/un-footnoted copies of the *same* rendering collapse together.
5. **Transclusions are joined by ID, never by position.** A Chinese segment with no Tibetan segment of the same ID gets no transclusion, and the file opens with an editorial note naming the affected IDs. Never shift segments to make counts agree.
6. **A transclusion line never takes a block ID** and never advances the verse counter — it is structural, not content.
7. **Footnoted and un-footnoted copies are one edition; scripts and registers are not.** `with-footnote` / `without-footnote` / plain collapse into one file (richest witness wins, the rest recorded in `superseded_witnesses:`). Simplified-script and modern-Chinese editions keep their own files — a modern rendering is a different translation, not a copy.
8. **`footnotes:` states what the document contains**, not what the sheet claims. Where they disagree, record both and say so.
9. **Catalogue numbers come from the sheet, titles from the document filename.** The filenames pack `Toh####`, `kp####`, `Tai####`, a part number, a version and a language around the title; the title field gets the title alone and each ID its own field. But the *values* for `toh:`/`taisho:` come from the sheet, which is authoritative — one filename carries an internal code (`MRK-T46-…`) that parses as a Taishō number and is not one.
10. **A work with no segmented Tibetan witness is skipped, not guessed at.** Report it.
11. **Rows flagged `cluster_uncertain` are excluded entirely** — the sheet does not establish which text they belong to.
12. **Never edit an existing `1-SOURCES/` file in place.** This skill writes whole files. Re-running overwrites its own output; it does not merge.

---

## Procedure

### Step 1 — Plan

```bash
python3 4-SYSTEM/Skills/inbox-to-sources/inbox_to_sources.py plan
```

Groups inbox records into texts and editions and writes `sources-plan.json`. Writes nothing into `1-SOURCES/`. Review the counts — texts, editions, parts, superseded witnesses — before continuing.

### Step 2 — Write

```bash
python3 4-SYSTEM/Skills/inbox-to-sources/inbox_to_sources.py write
```

For each text: load every part's segments from the inbox, order the parts, restamp block IDs as `^chapter-verse`, render the root text, then render each Chinese edition with a transclusion before every segment that has a Tibetan counterpart.

### Step 3 — Report

Report to the human contributor:
- files written, split by `Text/` and `Translations/`;
- every text skipped, with the reason;
- every translation carrying transclusion gaps, with the gap count — these are segmentation disagreements needing a human decision;
- every `footnotes_note:` disagreement;
- witnesses superseded by the edition collapse.

---

## Completion check

- [ ] `sources-plan.json` reviewed before any write
- [ ] One `1-SOURCES/Text/` file per text with a segmented Tibetan witness; skipped texts reported
- [ ] One `1-SOURCES/Translations/` file per distinct Chinese edition, with `root_text:` pointing at its root
- [ ] Block IDs are `^chapter-verse` throughout; `##` headings carry `^N-0`; no transclusion line carries a block ID
- [ ] Every transclusion resolves to a block ID that exists in the named root file
- [ ] No empty segment survives in a translation, and no transclusion is left dangling without its segment
- [ ] Written `total_verses` equals the segmentation recorded in the inbox manifest
- [ ] Every segment without a counterpart is left un-transcluded and named in the file's editorial note
- [ ] `superseded_witnesses:` lists every witness collapsed into each edition
- [ ] Every file carries `status: draft`
