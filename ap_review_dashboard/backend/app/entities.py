"""Entity / brand / alias reference data plus match helpers.

Data copied verbatim from updates-from-amy/ap_server 2.py (lines 73-157).
This is reference data — edit only when a new entity, alias, or brand is
introduced.
"""
import re


# ── Entity & brand data ──────────────────────────────────────────────────
ALL_ENTITY_NAMES = [
    "stand together benefits, llc","st benefits","stb",
    "stand together events, llc","st events",
    "stand together giving, llc","american strategies group",
    "stcc music","stcc faith","stcc athletes",
    "ckf events","cki events",
    "bri - free speech and debate llc","catalyst programming",
    "cvaf","concerned veterans for america foundation","libre institute",
    "cva","concerned veterans for america","libre","cva action","libre action",
    "university fund llc",
    "stand together, inc.","stand together","stand together chamber of commerce","stand together inc",
    "stand together communications","st comms","st communications",
    "capitol leaders","cavhoco","knslt","stvl3","stvl6",
    "stand together c4","stc4","st press","hva llc",
    "bigger picture us, inc","bpfp",
    "charles koch foundation","ckf",
    "charles koch institute","cki","st fellowships","stand together fellowships",
    "charles koch charitable fund","ckcf",
    "pbm center, inc.","mbm center",
    "the john quincy adams society","jqa","jqas",
    "vela education fund","vela",
    "bill of rights institute","bri",
    "empowered","stand together foundation","stf",
    "americans for prosperity foundation","afpf",
    "americans for prosperity","afp",
    "americans for prosperity action","afp action","afpa",
    "yes, every kid, inc.","yes",
    "yes, every kid inc. foundation","yesf",
    "cause of action","coa",
    "americans for prosperity state pac","afp state pac",
    "education defense and innovation network","edin",
    "stand together trust","stt",
    "ictll1 llc","learning lab wichita","wichita learning lab",
    "stt events llc",
    "stmse","stand together music, sports, and entertainment",
    "proto innovation","proto","whatcraft",
]

BRAND_TO_PARENT = {
    "stand together events, llc":"stand together, inc.",
    "st events":"stand together, inc.",
    "stand together giving, llc":"stand together, inc.",
    "american strategies group":"stand together, inc.",
    "stcc music":"stand together, inc.",
    "stcc faith":"stand together, inc.",
    "stcc athletes":"stand together, inc.",
    "ckf events":"charles koch foundation",
    "cki events":"charles koch institute",
    "bri - free speech and debate llc":"bill of rights institute",
    "catalyst programming":"stand together foundation",
    "cvaf":"americans for prosperity foundation",
    "libre institute":"americans for prosperity foundation",
    "cva":"americans for prosperity",
    "libre":"americans for prosperity",
    "cva action":"americans for prosperity action",
    "libre action":"americans for prosperity action",
    "university fund llc":"stand together trust",
}

ENTITY_ALIASES_FULL = {
    "stand together, inc.":["stand together","stand together chamber of commerce","stand together inc","stand together c4","stc4"],
    "stand together communications":["st comms","st communications","stand together communication","stand together comm"],
    "stand together benefits, llc":["st benefits","stb"],
    "charles koch institute":["cki","st fellowships","stand together fellowships"],
    "charles koch foundation":["ckf"],
    "charles koch charitable fund":["ckcf"],
    "bill of rights institute":["bri"],
    "stand together foundation":["stf"],
    "stand together trust":["stt"],
    "americans for prosperity foundation":["afpf"],
    "americans for prosperity":["afp"],
    "cva":["concerned veterans for america"],
    "cvaf":["concerned veterans for america foundation"],

    "americans for prosperity action":["afp action","afpa"],
    "americans for prosperity state pac":["afp state pac"],
    "yes, every kid, inc.":["yes"],
    "yes, every kid inc. foundation":["yesf"],
    "the john quincy adams society":["jqa","jqas"],
    "vela education fund":["vela"],
    "bigger picture us, inc":["bpfp"],
    "proto innovation":["proto","whatcraft"],
    "ictll1 llc":["learning lab wichita","wichita learning lab"],
    "stmse":["stand together music, sports, and entertainment"],
}


# ── Helpers ──────────────────────────────────────────────────────────────
def normalize(s: str) -> str:
    """Lowercase, strip punctuation, drop common suffixes, collapse whitespace."""
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"[,\.\-]", " ", s)
    s = re.sub(r"\b(llc|inc|ltd|corp|co|dba|the|and|&)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()


def resolve_entity(name_lower: str) -> str:
    """Resolve a brand or alias to its canonical paying-entity name."""
    if name_lower in BRAND_TO_PARENT:
        return BRAND_TO_PARENT[name_lower]
    for canonical, aliases in ENTITY_ALIASES_FULL.items():
        if name_lower == canonical or name_lower in [a.lower() for a in aliases]:
            return canonical
    return name_lower


def entities_match(sage_entity: str, found_entity: str) -> bool:
    """True iff two entity strings refer to the same paying entity."""
    if not sage_entity or not found_entity:
        return False
    se = sage_entity.lower().strip()
    fe = found_entity.lower().strip()
    if not se or not fe:
        return False
    if se == fe:
        return True
    se_n = normalize(se)
    fe_n = normalize(fe)
    if se_n == fe_n:
        return True
    se_r = resolve_entity(se)
    fe_r = resolve_entity(fe)
    if se_r == fe_r:
        return True
    for canonical, aliases in ENTITY_ALIASES_FULL.items():
        all_names = [canonical] + [a.lower() for a in aliases]
        if se in all_names and fe in all_names:
            return True
        if se_r in all_names and fe_r in all_names:
            return True
        if se in all_names and fe_r == canonical:
            return True
        if fe in all_names and se_r == canonical:
            return True
    se_canonical = resolve_entity(se_n)
    fe_canonical = resolve_entity(fe_n)
    if se_canonical == fe_canonical and se_canonical != se_n:
        return True
    return False


def find_entity_in_invoice(text: str):
    """Search text for any known entity name.

    Returns (matched_alias, canonical_entity) or (None, None).
    Iterates ALL_ENTITY_NAMES sorted by length desc so longer matches win.
    Uses \\b word boundaries for short (≤5 char) names to avoid substring noise.
    """
    if not text:
        return None, None
    text_lower = text.lower()
    for name in sorted(ALL_ENTITY_NAMES, key=len, reverse=True):
        if len(name) < 3:
            continue
        if len(name) <= 5:
            pattern = r"\b" + re.escape(name) + r"\b"
        else:
            pattern = re.escape(name)
        if re.search(pattern, text_lower):
            return name, resolve_entity(name)
    return None, None
