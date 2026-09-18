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
