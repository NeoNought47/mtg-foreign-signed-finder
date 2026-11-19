#!/usr/bin/env python3
"""
polyglot.py - find which printings of a Magic: The Gathering card are sold in a
non-English language on TCGplayer and Card Kingdom.

Usage:
  python3 polyglot.py "Lightning Bolt"
  python3 polyglot.py "Sol Ring" --site tcg
  python3 polyglot.py "Simic Signet" -l fr --foil
  python3 polyglot.py "Liliana, Dreadhorde General" --site ck
  python3 polyglot.py "Lightning Bolt" --debug     # print raw API fields

Requires: pip install requests
"""
import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

# code -> (TCGplayer language name, accepted aliases). Codes follow TCGplayer's languageAbbreviation
LANGS = {
    "JP": ("Japanese",    ["ja", "jpn", "japanese"]),
    "CS": ("Chinese (S)", ["zhs", "chs", "sc", "simplified"]),
    "CT": ("Chinese (T)", ["zht", "cht", "tc", "traditional"]),
    "KR": ("Korean",      ["ko", "kor", "korean"]),
    "DE": ("German",      ["ger", "deu", "german"]),
    "FR": ("French",      ["fra", "fre", "french"]),
    "IT": ("Italian",     ["ita", "italian"]),
    "SP": ("Spanish",     ["es", "spa", "spanish"]),
    "PT": ("Portuguese",  ["por", "portuguese"]),
    "RU": ("Russian",     ["rus", "russian"]),
    "PH": ("Phyrexian",   ["phy", "phyrexian"]),
}
# Readable names for progress messages
LANG_DISPLAY = {"CS": "Simplified Chinese", "CT": "Traditional Chinese"}
# Aliases that expand to several codes
LANG_GROUPS = {"zh": ["CS", "CT"], "cn": ["CS", "CT"], "chinese": ["CS", "CT"]}
TCG_NAME_TO_CODE = {name: code for code, (name, _) in LANGS.items()}

# Words in a Card Kingdom variation/edition that mark a foreign printing
LANG_RE = re.compile(
    r"\b(japanese|jpn|jp|chinese|korean|german|french|italian|spanish|"
    r"portuguese|russian|phyrexian)\b", re.I)
CK_WORD_TO_CODE = {"japanese": "JP", "jpn": "JP", "jp": "JP", "korean": "KR",
                   "german": "DE", "french": "FR", "italian": "IT", "spanish": "SP",
                   "portuguese": "PT", "russian": "RU", "phyrexian": "PH"}


def parse_langs(value: str):
    """'jp,cs' / 'ja zh' / 'Japanese' -> ['JP', 'CS']"""
    codes = []
    for tok in re.split(r"[,\s]+", value.strip()):
        t = tok.lower()
        if not t:
            continue
        if t in LANG_GROUPS:
            found = LANG_GROUPS[t]
        else:
            found = [c for c, (name, aliases) in LANGS.items()
                     if t == c.lower() or t == name.lower() or t in aliases]
        if not found:
            raise argparse.ArgumentTypeError(
                f"unknown language '{tok}'. Valid codes: {', '.join(LANGS)} (or zh = both Chinese)")
        codes += [c for c in found if c not in codes]
    return codes


def finish_ok(is_foil: bool, finish: str) -> bool:
    return finish == "all" or (finish == "foil") == is_foil


def describe_search(site: str, name: str, args) -> str:
    """e.g. 'Searching TCGplayer for French foil Simic Signet...'"""
    if set(args.langs) == set(LANGS):
        lang = "non-English"
    else:
        names = [LANG_DISPLAY.get(c, LANGS[c][0]) for c in args.langs]
        lang = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]
    finish = {"foil": " foil", "nonfoil": " non-foil"}.get(args.finish, "")
    return f"Searching {site} for {lang}{finish} {name}..."


def progress(msg: str):
    """One-line progress on stderr that overwrites itself (only in a terminal)."""
    if sys.stderr.isatty():
        sys.stderr.write("\r\033[K" + msg)
        sys.stderr.flush()


# ---------------- common ----------------
def base_name(s: str) -> str:
    """Drop bracketed variant info, e.g. 'Lightning Bolt (Borderless)' -> 'lightning bolt'"""
    return re.sub(r"\s*[\(\[].*?[\)\]]", "", s).strip().lower()


def name_matches(query: str, product_name: str, fuzzy: bool = False) -> bool:
    q = query.strip().lower()
    b = base_name(product_name)
    if b == q:
        return True
    if q in [f.strip() for f in b.split("//")]:  # double-faced / split cards
        return True
    return fuzzy and q in product_name.lower()


def post_json(s, url, body, params=None, tries=3):
    r = None
    for i in range(tries):
        r = s.post(url, params=params, json=body, timeout=30)
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(3 * (i + 1))
            continue
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return r.json()


# ---------------- TCGplayer ----------------
TCG_SEARCH = "https://mp-search-api.tcgplayer.com/v1/search/request"
TCG_LISTINGS = "https://mp-search-api.tcgplayer.com/v1/product/{pid}/listings"
LISTING_FILTERS = {"term": {"sellerStatus": "Live", "channelId": 0},
                   "range": {"quantity": {"gte": 1}},
                   "exclude": {"channelExclusion": 0}}


def tcg_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "application/json",
                      "Origin": "https://www.tcgplayer.com",
                      "Referer": "https://www.tcgplayer.com/"})
    return s


def tcg_search(s, name, delay, max_products, fuzzy, debug):
    products, frm, size = [], 0, 50
    for _ in range(6):  # at most 6 pages of search results
        body = {"algorithm": "sales_synonym_v2", "from": frm, "size": size,
                "filters": {"term": {"productLineName": ["magic"],
                                     "productTypeName": ["Cards"]},
                            "range": {}, "match": {}},
                "listingSearch": {"context": {"cart": {}}, "filters": LISTING_FILTERS},
                "context": {"cart": {}, "shippingCountry": "US"},
                "settings": {"useFuzzySearch": False, "didYouMean": {}},
                "sort": {}}
        block = post_json(s, TCG_SEARCH, body, params={"q": name, "isList": "false"})["results"][0]
        items = block.get("results", [])
        if debug and frm == 0:
            print(f"[debug] TCG search totalResults={block.get('totalResults')}")
            if items:
                print("[debug] first result fields:", sorted(items[0].keys()))
        hits = 0
        for it in items:
            pname = it.get("productName", "")
            if name_matches(name, pname, fuzzy):
                hits += 1
                products.append({"id": int(it["productId"]), "name": pname,
                                 "set": it.get("setName", "")})
        frm += size
        # Results are sorted by relevance: stop once a page has no matches after earlier hits
        if not items or frm >= block.get("totalResults", 0) or (products and hits == 0):
            break
        if len(products) >= max_products:
            break
        time.sleep(delay)
    return products[:max_products]


def tcg_listings(s, pid, langs, delay, max_pages=10):
    out, frm, size = [], 0, 50
    for _ in range(max_pages):
        filters = json.loads(json.dumps(LISTING_FILTERS))
        if langs:
            filters["term"]["language"] = langs
        body = {"filters": filters, "from": frm, "size": size,
                "sort": {"field": "price+shipping", "order": "asc"},
                "context": {"shippingCountry": "US", "cart": {}},
                "aggregations": ["listingType"]}
        block = post_json(s, TCG_LISTINGS.format(pid=pid), body)["results"][0]
        items = block.get("results", [])
        out.extend(items)
        frm += size
        if not items or frm >= block.get("totalResults", 0):
            break
        time.sleep(delay)
    return out


def run_tcg(name, args):
    print(f"\n{describe_search('TCGplayer', name, args)}")
    s = tcg_session()
    products = tcg_search(s, name, args.delay, args.max_products, args.fuzzy, args.debug)
    print(f"=== TCGplayer: {len(products)} matching printings, checking listings for each ===")
    if not products:
        print("Nothing found. Check the spelling (use the English card name), or try --fuzzy.")
        return

    if args.debug:  # one unfiltered page, to check the real language values
        sample = tcg_listings(s, products[0]["id"], None, args.delay, max_pages=1)
        print(f"[debug] language breakdown for {products[0]['name']}:",
              Counter(x.get("language") for x in sample))
        if sample:
            print("[debug] listing fields:", sorted(sample[0].keys()))

    tcg_langs = [LANGS[c][0] for c in args.langs]
    found, warned = 0, False
    for i, p in enumerate(products, 1):
        progress(f"  [{i}/{len(products)}] {p['set']}")
        time.sleep(args.delay)
        try:
            items = tcg_listings(s, p["id"], tcg_langs, args.delay)
        except requests.HTTPError as e:
            progress("")
            print(f"  ! {p['set']} / {p['name']}: request failed: {e}")
            continue
        if any(x.get("language") == "English" for x in items) and not warned:
            progress("")
            print("  ! Note: the language filter seems to be ignored; English listings removed locally")
            warned = True
        groups = defaultdict(lambda: {"n": 0, "qty": 0, "min": None})
        for x in items:
            lang = x.get("language", "?")
            if lang not in tcg_langs:
                continue
            printing = x.get("printing", "?")
            if not finish_ok(printing.lower() == "foil", args.finish):
                continue
            g = groups[(lang, printing)]
            g["n"] += 1
            g["qty"] += int(x.get("quantity") or 0)
            price = float(x.get("price") or 0)
            g["min"] = price if g["min"] is None else min(g["min"], price)
        if not groups:
            continue
        found += 1
        progress("")
        print(f"\n[{p['set']}] {p['name']}")
        print(f"  https://www.tcgplayer.com/product/{p['id']}")
        for (lang, printing), g in sorted(groups.items()):
            code = TCG_NAME_TO_CODE.get(lang, "??")
            print(f"    {code} {lang:<12} {printing:<8} {g['n']:>3} listings / {g['qty']:>3} cards"
                  f"   from ${g['min']:.2f}")
    progress("")
    print(f"\nTCGplayer summary: {found} of {len(products)} printings have matching listings.")


# ---------------- Card Kingdom ----------------
CK_URL = "https://api.cardkingdom.com/api/v2/pricelist"
CK_CACHE = Path.home() / ".cache" / "polyglot" / "ck_pricelist.json"


def ck_load(max_age_h):
    if CK_CACHE.exists() and time.time() - CK_CACHE.stat().st_mtime < max_age_h * 3600:
        text = CK_CACHE.read_text()
    else:
        print("Downloading the full Card Kingdom price list (large file, will be cached)...")
        r = requests.get(CK_URL, headers={"User-Agent": UA}, timeout=180)
        r.raise_for_status()
        text = r.text
        CK_CACHE.parent.mkdir(parents=True, exist_ok=True)
        CK_CACHE.write_text(text)
    data = json.loads(text)
    return data.get("data", []) if isinstance(data, dict) else data


def run_ck(name, args):
    print(f"\n{describe_search('Card Kingdom', name, args)}")
    items = ck_load(args.ck_cache_hours)
    matches = [it for it in items if name_matches(name, it.get("name", ""), args.fuzzy)]
    print(f"=== Card Kingdom: {len(matches)} matching entries in the price list ===")
    if args.debug:
        if items:
            print("[debug] price list fields:", sorted(items[0].keys()))
        for it in matches:
            print("[debug]", it.get("sku"), "|", it.get("edition"), "|",
                  it.get("name"), "|", it.get("variation"), "| foil:", it.get("is_foil"))

    foreign = []
    for it in matches:
        # Only look at variation and edition, not the card name,
        # otherwise cards like "Phyrexian Arena" are flagged as Phyrexian language
        text = " ".join(str(it.get(k) or "") for k in ("variation", "edition"))
        m = LANG_RE.search(text)
        if not m:
            continue
        word = m.group(1).lower()
        if word == "chinese":
            code = "CT" if "traditional" in text.lower() else "CS"
        else:
            code = CK_WORD_TO_CODE[word]
        is_foil = str(it.get("is_foil")).lower() == "true"
        if code in args.langs and finish_ok(is_foil, args.finish):
            foreign.append((code, is_foil, it))
    if not foreign:
        print("No matching foreign-language printings (based on the variant description).")
        return
    for code, is_foil, it in foreign:
        foil = "Foil" if is_foil else "Normal"
        lang = f"{code} {LANGS[code][0]}"
        var = f" ({it['variation']})" if it.get("variation") else ""
        print(f"\n[{it.get('edition')}] {it.get('name')}{var}")
        print(f"  https://www.cardkingdom.com/{str(it.get('url', '')).lstrip('/')}")
        print(f"    {lang:<15} {foil:<8} ${it.get('price_retail')}   in stock: {it.get('qty_retail')}")
    print(f"\nCard Kingdom summary: {len(foreign)} foreign-language printings.")


# ---------------- main ----------------
def main():
    lang_help = "  ".join(f"{c}={n}" for c, (n, _) in LANGS.items())
    ap = argparse.ArgumentParser(
        description="Find foreign-language printings of an MTG card on TCGplayer / Card Kingdom",
        epilog=f"Language codes: {lang_help}  zh=both Simplified and Traditional Chinese. "
               "Common abbreviations (ja/ko/es/de/fr...) and full English names also work, "
               "case-insensitive.")
    ap.add_argument("name", help="English card name, e.g. \"Lightning Bolt\"")
    ap.add_argument("--site", default="all",
                    choices=["all", "tcg", "tcgplayer", "ck", "cardkingdom"],
                    help="search one site only (default: both)")
    ap.add_argument("--lang", "-l", dest="langs", type=parse_langs, default=list(LANGS),
                    help="only these languages, comma separated, e.g. --lang jp,cs or -l zh")
    fin = ap.add_mutually_exclusive_group()
    fin.add_argument("--foil", dest="finish", action="store_const", const="foil",
                     help="foils only")
    fin.add_argument("--nonfoil", dest="finish", action="store_const", const="nonfoil",
                     help="non-foils only")
    ap.set_defaults(finish="all")
    ap.add_argument("--fuzzy", action="store_true", help="looser name matching (substring)")
    ap.add_argument("--delay", type=float, default=0.7, help="seconds between requests")
    ap.add_argument("--max-products", type=int, default=80,
                    help="max number of TCGplayer printings to check")
    ap.add_argument("--ck-cache-hours", type=float, default=12,
                    help="how long to reuse the cached Card Kingdom price list")
    ap.add_argument("--debug", action="store_true", help="print raw API fields")
    args = ap.parse_args()
    args.site = {"tcgplayer": "tcg", "cardkingdom": "ck"}.get(args.site, args.site)

    if args.site in ("all", "tcg"):
        try:
            run_tcg(args.name, args)
        except Exception as e:
            progress("")
            print(f"TCGplayer error: {e}", file=sys.stderr)
    if args.site in ("all", "ck"):
        try:
            run_ck(args.name, args)
        except Exception as e:
            print(f"Card Kingdom error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
