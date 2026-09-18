#!/usr/bin/env python3
"""
inbox-to-sources — promote the reviewed inbox texts into 1-SOURCES/.

The inbox holds one file per *sheet row*: a work split across five documents
appears as five files, and a translation that exists both with and without
footnotes appears twice. 1-SOURCES/ holds one file per *text*: the Tibetan
witness in `Text/`, each distinct Chinese edition in `Translations/`, parts
joined into chapters, block IDs in the vault's own `^chapter-verse` scheme,
and every Chinese segment preceded by a transclusion of its Tibetan
counterpart.

    plan     group inbox records into texts and editions; report, write nothing
    write    render the 1-SOURCES files
"""

import argparse
import collections
import datetime as _dt
import json
import os
import re
import sys

# --------------------------------------------------------------------------
# Title parsing
# --------------------------------------------------------------------------

# `Toh0023_kp0002_一切如來母一字般若波羅蜜多經_bo.docx`
# `Toh0026《聖般若波羅蜜多日藏大乘經》v.1_bo`
# `Toh4054-Tai1606《阿毘達磨雜集論》01_bo`
# `T1605-1_大乘阿毘達磨集論_bo`
TOH_TOK = re.compile(r"(?<![a-z0-9])toh\s*0*(\d+)(?:to0*(\d+))?", re.I)
TAI_TOK = re.compile(r"(?<![a-z0-9])(?:tai|t)\s*0*(\d+)", re.I)
KP_TOK = re.compile(r"(?<![a-z0-9])kp\s*0*(\d+)", re.I)
VER_TOK = re.compile(r"\bv\.?\s*(\d+(?:\.\d+)?)", re.I)
LANG_TOK = re.compile(r"[-_＿](bo|zh)(?:[-_＿.]|$)", re.I)
FOOTNOTE_TOK = re.compile(r"(with(?:out)?)[\s_-]*footnote|註腳", re.I)
SIMPLIFIED_TOK = re.compile(r"simplified|简", re.I)
BRACKET_TITLE = re.compile(r"[《〈]([^》〉]+)[》〉]")


def parse_document_title(raw):
    """Split a document filename into its title and the IDs packed around it.

    These filenames carry the catalogue numbers, the part number, the
    language and the footnote state in front of (and behind) the actual
    title. Everything is pulled out so the title field holds a title and
    nothing else, and each ID lands in its own field.
    """
    out = {"title": "", "toh": "", "toh_end": "", "taisho": "", "kp": "",
           "version": "", "part": "", "lang": "", "footnotes": None,
           "simplified": False, "raw": raw}
    if not raw:
        return out
    s = re.sub(r"\.docx?$", "", raw.strip(), flags=re.I)

    m = FOOTNOTE_TOK.search(s)
    if m:
        out["footnotes"] = not (m.group(1) or "").lower().startswith("without")
        s = FOOTNOTE_TOK.sub(" ", s)
    if SIMPLIFIED_TOK.search(s):
        out["simplified"] = True
        s = SIMPLIFIED_TOK.sub(" ", s)

    m = LANG_TOK.search(s)
    if m:
        out["lang"] = m.group(1).lower()
        s = s[:m.start()] + " " + s[m.end():]

    m = TOH_TOK.search(s)
    if m:
        out["toh"] = "toh%s" % m.group(1).lstrip("0")
        if m.group(2):
            out["toh_end"] = "toh%s" % m.group(2).lstrip("0")
        s = s[:m.start()] + " " + s[m.end():]
    m = KP_TOK.search(s)
    if m:
        out["kp"] = "kp%s" % m.group(1).lstrip("0")
        s = s[:m.start()] + " " + s[m.end():]
    m = TAI_TOK.search(s)
    if m:
        out["taisho"] = "tai%s" % m.group(1).lstrip("0")
        s = s[:m.start()] + " " + s[m.end():]
    m = VER_TOK.search(s)
    if m:
        out["version"] = m.group(1)
        s = s[:m.start()] + " " + s[m.end():]

    # A title in 《…》 is unambiguous; take it before stripping stray digits.
    m = BRACKET_TITLE.search(s)
    if m:
        out["title"] = m.group(1).strip()
        rest = s[:m.start()] + " " + s[m.end():]
        mp = re.search(r"(?<!\d)(\d{1,3})(?!\d)", rest)
        if mp:
            out["part"] = str(int(mp.group(1)))
        return out

    # Otherwise the remainder, minus separators and any lone part number.
    mp = re.match(r"^[\s_\-＿]*(\d{1,3})(?![\d])[\s_\-＿]+", s)
    if mp:
        out["part"] = str(int(mp.group(1)))
        s = s[mp.end():]
    s = re.sub(r"[_＿]+", " ", s)
    s = re.sub(r"(?<!\d)\d{1,3}\s*$", "", s)
    out["title"] = re.sub(r"^[\s\-—·.]+|[\s\-—·.]+$", "", re.sub(r"\s{2,}", " ", s)).strip()
    return out


# --------------------------------------------------------------------------
# Grouping
# --------------------------------------------------------------------------

def text_key(work_id):
    """The text a work ID belongs to — its Toh anchor, without the part."""
    m = re.match(r"^(toh[a-z]*\d+(?:to\d+)?)", work_id or "")
    return m.group(1) if m else (work_id or "")


def part_key(work_id):
    """Sort key for the parts of one text."""
    nums = [int(n) for n in re.findall(r"(?<!toh)(?<!tai)(?<!kp)\b(\d+)\b", work_id or "")]
    tail = re.findall(r"-(\d+)$", work_id or "")
    return (int(tail[0]) if tail else (nums[-1] if nums else 0), work_id or "")


CLASSICAL = {"zh", "zh-hant"}


def edition_class(rec):
    """Which 1-SOURCES file a Chinese record belongs to.

    Footnoted and un-footnoted copies are the same translation and collapse
    into one edition; a simplified-script edition and a modern-Chinese
    rendering are different texts and keep their own files.
    """
    tag = rec["lang_tag"]
    if tag == "bo":
        return "root"
    if tag == "zh-hans":
        return "simplified"
    if tag == "zh-modern":
        return "modern"
    if tag in CLASSICAL:
        return "classical"
    return tag or "other"


# richest first — the witness chosen to represent a collapsed edition
VARIANT_RANK = {"with-footnote": 0, "": 1, "traditional": 1, "without-footnote": 2}


def choose_witness(recs, manifest):
    """Pick the witness that represents an edition, richest body first."""
    def key(r):
        m = manifest.get(r["slug"], {})
        return (VARIANT_RANK.get(r["variant"], 3),
                0 if m.get("ingest_status") == "with-body" else 1,
                -(m.get("segment_count") or 0))
    return sorted(recs, key=key)[0]


def build_plan(records, manifest):
    texts = collections.defaultdict(lambda: collections.defaultdict(list))
    for rec in records:
        if rec.get("cluster_uncertain") or not rec["work_id"]:
            continue
        texts[text_key(rec["work_id"])][edition_class(rec)].append(rec)

    plan = []
    for tkey in sorted(texts):
        editions = texts[tkey]
        entry = {"text_key": tkey, "editions": {}}
        for cls, recs in editions.items():
            # one witness per part, parts ordered
            by_part = collections.defaultdict(list)
            for r in recs:
                by_part[r["work_id"]].append(r)
            parts = []
            for i, wid in enumerate(sorted(by_part, key=part_key), start=1):
                chosen = choose_witness(by_part[wid], manifest)
                others = [r["slug"] for r in by_part[wid] if r is not chosen]
                m = manifest.get(chosen["slug"], {})
                parts.append({
                    "chapter": i,
                    "work_id": wid,
                    "slug": chosen["slug"],
                    "variant": chosen["variant"],
                    "segment_count": m.get("segment_count") or 0,
                    "ingest_status": m.get("ingest_status"),
                    "superseded": others,
                })
            if any(p["ingest_status"] == "with-body" for p in parts):
                entry["editions"][cls] = parts
        if entry["editions"]:
            plan.append(entry)
    return plan
# --------------------------------------------------------------------------
# Rendering  (appended: writer stage)
# --------------------------------------------------------------------------

SEG_LINE = re.compile(r"^[ \t]*(?:\d{1,5}\.)?[ \t]*(?P<text>.*?)[ \t]*\^s(?P<id>[0-9a-z-]+)[ \t]*$")
FOOTNOTE_DEF = re.compile(r"^\[\^(\d+)\]: ")


def read_inbox(path):
    """Return (frontmatter_dict_lite, segments[list of (id,text)], footnote_defs)."""
    raw = open(path, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
    fm, body = (m.group(1), raw[m.end():]) if m else ("", raw)
    meta = {}
    for line in fm.split("\n"):
        mm = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if mm:
            meta[mm.group(1)] = mm.group(2).strip().strip('"')
    segs, notes = [], []
    for line in body.split("\n"):
        if FOOTNOTE_DEF.match(line):
            notes.append(line)
            continue
        sm = SEG_LINE.match(line)
        if sm:
            segs.append((sm.group("id"), sm.group("text").strip()))
    return meta, segs, notes


def slugify_ascii(text, fallback=""):
    t = re.sub(r"[^\x00-\x7f]", "", (text or "")).lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    t = re.sub(r"-{2,}", "-", t)
    return t[:60].strip("-") or fallback


def yq(v):
    if v is None or v == "":
        return '""'
    s = str(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    if re.search(r'[:#\[\]{}&*!|>%@`"\']|^\s|\s$|^-\s', s) or "\n" in s:
        return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')
    return s


def render_text(parts, meta, heading_of, transclude_root=None, gaps=None):
    """Render body: one `##` chapter per part, `^chapter-verse` on every block."""
    out = []
    for p in parts:
        ch = p["chapter"]
        out.append("## %s ^%d-0" % (heading_of(p), ch))
        out.append("")
        for i, (_sid, text) in enumerate(p["segments"], start=1):
            if transclude_root is not None:
                if (ch, i) in transclude_root:
                    out.append("![[%s#^%d-%d]]" % (transclude_root[(ch, i)], ch, i))
                    out.append("")
                elif gaps is not None:
                    gaps.append("%d-%d" % (ch, i))
            out.append("%s ^%d-%d" % (text if text else "", ch, i))
            out.append("")
    return "\n".join(out)






def stage_write(plan, records, manifest, vault="."):
    """Write the 1-SOURCES files: one root text, one file per Chinese edition."""
    R = {r["slug"]: r for r in records}
    textdir = os.path.join(vault, "1-SOURCES", "Text")
    trdir = os.path.join(vault, "1-SOURCES", "Translations")
    os.makedirs(textdir, exist_ok=True)
    os.makedirs(trdir, exist_ok=True)
    today = _dt.date.today().isoformat()

    written, report = [], []
    for entry in plan:
        tkey = entry["text_key"]
        eds = entry["editions"]
        if "root" not in eds:
            report.append({"text": tkey, "skipped": "no Tibetan witness"})
            continue

        # ---- load every part's segments
        for cls, parts in eds.items():
            for part in parts:
                m = manifest.get(part["slug"], {})
                if not m.get("path") or m.get("ingest_status") != "with-body":
                    part["segments"], part["notes"], part["meta"] = [], [], {}
                    continue
                meta, segs, notes = read_inbox(os.path.join(vault, m["path"]))
                part["segments"], part["notes"], part["meta"] = segs, notes, meta

        root_parts = [p for p in eds["root"] if p["segments"]]
        if not root_parts:
            report.append({"text": tkey, "skipped": "Tibetan witness has no segments"})
            continue
        for i, p in enumerate(root_parts, start=1):
            p["chapter"] = i

        # ---- identity, from the sheet (authoritative) plus the filename title
        first = R[root_parts[0]["slug"]]
        dt = parse_document_title(first["doc_title"])
        bo_title = first["name_long"] or first["name_short"] or dt["title"] or tkey
        en_title = first["name_en"]
        toh = first["toh"] or dt["toh"] or tkey
        base = slugify_ascii(en_title, fallback=toh)
        stem = "%s-%s" % (toh, base) if base != toh else toh

        root_name = "bo-%s.md" % stem
        root_path = os.path.join(textdir, root_name)
        root_rel = "1-SOURCES/Text/%s" % root_name

        def heading_bo(p):
            n = len(root_parts)
            return ("%s — %d/%d" % (bo_title, p["chapter"], n)) if n > 1 else bo_title

        total = sum(len(p["segments"]) for p in root_parts)
        fm = ["---",
              "title: %s" % yq(bo_title),
              "alt_titles:"]
        zh_first = None
        for cls in ("classical", "modern", "simplified"):
            if cls in eds and eds[cls]:
                zh_first = R[eds[cls][0]["slug"]]
                break
        if zh_first and (zh_first["name_short"] or zh_first["name_long"]):
            fm.append("  - zh: %s" % yq(zh_first["name_long"] or zh_first["name_short"]))
        if en_title:
            fm.append("  - en: %s" % yq(en_title))
        fm += ["author: %s" % yq(first["author_orig"]),
               "author_in_english: %s" % yq(first["author_en"]),
               "language: Tibetan",
               "script: Unicode Tibetan",
               "file_type: root-text",
               "lang_tag: bo",
               "chapters: %d" % len(root_parts),
               "total_verses: %d" % total,
               "verse_id_format: chapter-verse",
               "toh: %s" % yq(toh),
               "taisho: %s" % yq(first["taisho"]),
               "kp_id: %s" % yq(dt["kp"]),
               "work_id: %s" % yq(first["work_id"]),
               "bdrc_work_id: %s" % yq(first["bdrc_work"]),
               "root_bdrc_work_id: %s" % yq(first["root_bdrc"]),
               "pecha_id: %s" % yq(first["pecha_id"]),
               "category: %s" % yq(first["category_raw"]),
               "category_code: %s" % yq(first["category_code"]),
               "category_en: %s" % yq(first["category_en"]),
               "source_description: %s" % yq(first["source"]),
               "sheet_id: %s" % yq(first["sheet_id"]),
               "sheet_rows: [%s]" % ", ".join(str(R[p["slug"]]["sheet_row"]) for p in root_parts),
               "parts: [%s]" % ", ".join(yq(p["work_id"]) for p in root_parts),
               "promoted_from: [%s]" % ", ".join(yq(p["slug"]) for p in root_parts),
               "promoted: %s" % today,
               "status: draft",
               "---", ""]
        body = ["# %s" % bo_title, ""]
        if en_title:
            body += ["*%s*" % en_title, ""]
        body.append(render_text(root_parts, first, heading_bo))
        notes = [n for p in root_parts for n in p["notes"]]
        if notes:
            body += ["", *notes]
        with open(root_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(fm + body).rstrip() + "\n")
        written.append(root_rel)

        # ---- root segment index, for transcluding from the translations
        root_ids = {(p["chapter"], i)
                    for p in root_parts for i in range(1, len(p["segments"]) + 1)}

        for cls in sorted(k for k in eds if k != "root"):
            parts = [p for p in eds[cls] if p["segments"]]
            if not parts:
                continue
            for i, p in enumerate(parts, start=1):
                p["chapter"] = i
            zr = R[parts[0]["slug"]]
            zdt = parse_document_title(zr["doc_title"])
            zh_title = zr["name_long"] or zr["name_short"] or zdt["title"] or bo_title
            # `footnotes:` states what the document actually contains. The
            # sheet's own label is recorded separately when it disagrees —
            # row 135 is marked "註腳 with footnote" but carries no footnote
            # at all, and silently trusting either side would hide that.
            has_notes = any(p["notes"] for p in parts) or \
                any("[^" in t for p in parts for _i, t in p["segments"])
            declared = zdt["footnotes"]
            if declared is None and parts[0]:
                v = R[parts[0]["slug"]]["variant"]
                declared = True if v == "with-footnote" else (False if v == "without-footnote" else None)
            footnotes = has_notes
            tag = {"classical": "zh", "simplified": "zh-hans", "modern": "zh-modern"}.get(cls, cls)
            tname = "%s-%s.md" % (tag, stem)
            tpath = os.path.join(trdir, tname)

            transclude = {k: root_rel for k in root_ids}
            gaps = []

            def heading_zh(p, _n=len(parts), _t=zh_title):
                return ("%s — %d/%d" % (_t, p["chapter"], _n)) if _n > 1 else _t

            ztotal = sum(len(p["segments"]) for p in parts)
            zfm = ["---",
                   "title: %s" % yq(zh_title),
                   "alt_titles:"]
            if bo_title:
                zfm.append("  - bo: %s" % yq(bo_title))
            if en_title:
                zfm.append("  - en: %s" % yq(en_title))
            zfm += ["author: %s" % yq(zr["author_orig"]),
                    "language: %s" % yq(zr["language"]),
                    "script: %s" % yq("Simplified Chinese" if cls == "simplified" else "Traditional Chinese"),
                    "file_type: translation",
                    "lang_tag: %s" % yq(tag),
                    "edition_class: %s" % yq(cls),
                    "footnotes: %s" % ("true" if footnotes else "false"),
                    ] + ([
                    "footnotes_sheet_label: %s" % ("true" if declared else "false"),
                    "footnotes_note: \"the sheet labels this witness differently from what the document contains\"",
                    ] if declared is not None and bool(declared) != bool(footnotes) else []) + [
                    "chapters: %d" % len(parts),
                    "total_verses: %d" % ztotal,
                    "verse_id_format: chapter-verse",
                    "root_text: %s" % yq(root_rel),
                    "covers_verses: %s" % yq("1-1–%d-%d" % (parts[-1]["chapter"], len(parts[-1]["segments"])) if parts else ""),
                    "toh: %s" % yq(toh),
                    "taisho: %s" % yq(zr["taisho"] or first["taisho"]),
                    "kp_id: %s" % yq(zdt["kp"] or dt["kp"]),
                    "bdrc_work_id: %s" % yq(zr["bdrc_work"]),
                    "pecha_id: %s" % yq(zr["pecha_id"]),
                    "category: %s" % yq(zr["category_raw"]),
                    "source_description: %s" % yq(zr["source"]),
                    "sheet_rows: [%s]" % ", ".join(str(R[p["slug"]]["sheet_row"]) for p in parts),
                    "promoted_from: [%s]" % ", ".join(yq(p["slug"]) for p in parts),
                    "superseded_witnesses: [%s]" % ", ".join(yq(s) for p in parts for s in p["superseded"]),
                    "promoted: %s" % today,
                    "status: draft",
                    "---", ""]
            zbody = ["# %s" % zh_title, ""]
            rendered = render_text(parts, zr, heading_zh, transclude_root=transclude, gaps=gaps)
            if gaps:
                zbody += ["> [Ed: %d segment(s) have no counterpart in the Tibetan and carry "
                          "no transclusion: %s. The two witnesses disagree on segmentation — "
                          "resolve before relying on the alignment.]"
                          % (len(gaps), ", ".join(gaps[:8]) + (" …" if len(gaps) > 8 else "")), ""]
            zbody.append(rendered)
            znotes = [n for p in parts for n in p["notes"]]
            if znotes:
                zbody += ["", *znotes]
            with open(tpath, "w", encoding="utf-8") as fh:
                fh.write("\n".join(zfm + zbody).rstrip() + "\n")
            written.append("1-SOURCES/Translations/%s" % tname)
            report.append({"text": tkey, "edition": cls, "file": tname,
                           "segments": ztotal, "gaps": len(gaps),
                           "footnotes": bool(footnotes)})
    return written, report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("stage", choices=["plan", "write"])
    p.add_argument("--records", default="0-INBOX/raw-data/pecha-sheet/records.json")
    p.add_argument("--manifest", default="0-INBOX/texts/_manifest.json")
    p.add_argument("--out", default="0-INBOX/raw-data/pecha-sheet/sources-plan.json")
    args = p.parse_args(argv)

    records = json.load(open(args.records, encoding="utf-8"))
    manifest = {m["slug"]: m for m in json.load(open(args.manifest, encoding="utf-8"))}
    plan = build_plan(records, manifest)

    if args.stage == "write":
        written, report = stage_write(plan, records, manifest)
        print("wrote %d files into 1-SOURCES/" % len(written))
        gaps = sum(r.get("gaps", 0) for r in report)
        skipped = [r for r in report if r.get("skipped")]
        print("translations with un-transcluded segments: %d (total %d segments)"
              % (sum(1 for r in report if r.get("gaps")), gaps))
        for r in skipped:
            print("  skipped %s — %s" % (r["text"], r["skipped"]))
        json.dump(report, open(args.out.replace("sources-plan", "sources-write-report"), "w"),
                  ensure_ascii=False, indent=1)
        return 0

    if args.stage == "plan":
        json.dump(plan, open(args.out, "w"), ensure_ascii=False, indent=1)
        n_ed = sum(len(t["editions"]) for t in plan)
        n_parts = sum(len(ps) for t in plan for ps in t["editions"].values())
        sup = sum(len(p["superseded"]) for t in plan for ps in t["editions"].values() for p in ps)
        print("texts: %d | editions (files to write): %d | parts: %d | witnesses superseded: %d"
              % (len(plan), n_ed, n_parts, sup))
        print("plan -> %s" % args.out)
        cls = collections.Counter(c for t in plan for c in t["editions"])
        print("editions by class:", dict(cls))
    return 0


if __name__ == "__main__":
    sys.exit(main())

