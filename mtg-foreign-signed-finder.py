#!/usr/bin/env python3
"""
mtg-foreign-signed-finder.py - find which printings of a Magic: The Gathering card are sold in a
non-English language on TCGplayer and Card Kingdom.

Usage:
  python3 mtg-foreign-signed-finder.py "Lightning Bolt"
  python3 mtg-foreign-signed-finder.py "Sol Ring" --site tcg
  python3 mtg-foreign-signed-finder.py "Simic Signet" -l fr --foil
  python3 mtg-foreign-signed-finder.py "Lightning Bolt" -l en,jp --signed
  python3 mtg-foreign-signed-finder.py "Liliana, Dreadhorde General" --site ck
  python3 mtg-foreign-signed-finder.py "Lightning Bolt" --debug     # print raw API fields

Requires: pip install requests
"""
import argparse
import html
import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlencode

import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

# code -> (TCGplayer language name, accepted aliases). Codes follow TCGplayer's languageAbbreviation
LANGS = {
    "EN": ("English",     ["eng", "english"]),
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
# Default: every language except English
FOREIGN = [c for c in LANGS if c != "EN"]

# Signed cards on TCGplayer are photo ("custom") listings whose seller-written
# title/description says so. Phrases that only look like a signature are removed first.
SIGNED_RE = re.compile(r"\bsigned\b|\bautograph(ed)?\b|\bsignature\b|\bartist proof\b", re.I)
NOT_SIGNED_RE = re.compile(
    r"\b(not|never|no)\s+(been\s+)?signed\b|\bno\s+signature\b|"
    r"\bsignature\s+(spellbook|foil|series|edition)\b|"
    # shipping wording, e.g. "shipped with signature confirmation"
    r"\bsignature\s+(confirmation|confirm|required|on\s+delivery|tracking|service)\b|"
    r"\b(require|requires|required|with)\s+(a\s+)?signature\s+(upon|on|at)\s+delivery\b", re.I)


def clean_html(t: str) -> str:
    t = html.unescape(html.unescape(t or ""))  # TCGplayer escapes the HTML twice
    return " ".join(re.sub(r"<[^>]+>", " ", t).replace("\xa0", " ").split())


def listing_text(x) -> str:
    cd = x.get("customData") or {}
    return f"{clean_html(cd.get('title'))} {clean_html(cd.get('description'))}"


def listing_title(x) -> str:
    """Seller's title, plus the description when it adds something."""
    cd = x.get("customData") or {}
    title, desc = clean_html(cd.get("title")), clean_html(cd.get("description"))
    if not desc or desc in title:
        return title[:100]
    probe = NOT_SIGNED_RE.sub(lambda m: " " * len(m.group()), desc)
    m = None if SIGNED_RE.search(title) else SIGNED_RE.search(probe)
    if m:  # show the part of the description that mentions the signature
        start = max(0, m.start() - 40)
        snippet = ("..." if start else "") + desc[start:m.end() + 50].strip()
        if m.end() + 50 < len(desc):
            snippet += "..."
        return f"{title[:50]} | {snippet}"
    return f"{title} | {desc}"[:100]


def is_signed(x) -> bool:
    if x.get("listingType") != "custom":
        return False
    return bool(SIGNED_RE.search(NOT_SIGNED_RE.sub(" ", listing_text(x))))


def signed_ok(signed: bool, mode: str) -> bool:
    return mode == "all" or (mode == "signed") == signed

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
    if set(args.langs) == set(FOREIGN):
        lang = "non-English"
    elif set(args.langs) == set(LANGS):
        lang = ""
    else:
        names = [LANG_DISPLAY.get(c, LANGS[c][0]) for c in args.langs]
        lang = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]
    signed = {"signed": " signed", "unsigned": " unsigned"}.get(args.signed, "")
    finish = {"foil": " foil", "nonfoil": " non-foil"}.get(args.finish, "")
    what = " ".join(w for w in (lang, signed.strip(), finish.strip(), name) if w)
    if set(args.langs) == set(LANGS):
        what += " in any language"
    return f"Searching {site} for {what}..."


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
    if q in [f.strip() for f in b.split("//")]:  # split cards (double-faced cards are listed by front face)
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


def tcg_listings(s, pid, langs, delay, max_pages=10, listing_types=None):
    out, frm, size = [], 0, 50
    for _ in range(max_pages):
        filters = json.loads(json.dumps(LISTING_FILTERS))
        if langs:
            filters["term"]["language"] = langs
        if listing_types:
            filters["term"]["listingType"] = listing_types
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
    # Signed cards are always photo listings, so ask the API for those only
    types = ["custom"] if args.signed == "signed" else None
    found, warned = 0, False
    for i, p in enumerate(products, 1):
        progress(f"  [{i}/{len(products)}] {p['set']}")
        time.sleep(args.delay)
        try:
            items = tcg_listings(s, p["id"], tcg_langs, args.delay, listing_types=types)
        except requests.HTTPError as e:
            progress("")
            print(f"  ! {p['set']} / {p['name']}: request failed: {e}")
            continue
        if any(x.get("language") not in tcg_langs for x in items) and not warned:
            progress("")
            print("  ! Note: the language filter seems to be ignored; other languages removed locally")
            warned = True
        groups = defaultdict(lambda: {"n": 0, "qty": 0, "min": None})
        signed_rows = []
        for x in items:
            lang = x.get("language", "?")
            if lang not in tcg_langs:
                continue
            printing = x.get("printing", "?")
            if not finish_ok(printing.lower() == "foil", args.finish):
                continue
            if not signed_ok(is_signed(x), args.signed):
                continue
            if args.signed == "signed":  # each signed card is unique, list them one by one
                signed_rows.append(x)
                continue
            g = groups[(lang, printing)]
            g["n"] += 1
            g["qty"] += int(x.get("quantity") or 0)
            price = float(x.get("price") or 0)
            g["min"] = price if g["min"] is None else min(g["min"], price)
        if not groups and not signed_rows:
            continue
        found += 1
        progress("")
        print(f"\n[{p['set']}] {p['name']}")
        print(f"  https://www.tcgplayer.com/product/{p['id']}")
        for (lang, printing), g in sorted(groups.items()):
            code = TCG_NAME_TO_CODE.get(lang, "??")
            print(f"    {code} {lang:<12} {printing:<8} {g['n']:>3} listings / {g['qty']:>3} cards"
                  f"   from ${g['min']:.2f}")
        for x in signed_rows:
            code = TCG_NAME_TO_CODE.get(x.get("language"), "??")
            title = listing_title(x)
            print(f"    {code} {x.get('language', '?'):<12} {x.get('printing', '?'):<8}"
                  f" ${float(x.get('price') or 0):>8.2f}  {x.get('condition', '')}"
                  f"  [{x.get('sellerName', '')}]\n        \"{title}\"")
    progress("")
    print(f"\nTCGplayer summary: {found} of {len(products)} printings have matching listings.")


# ---------------- Card Kingdom ----------------
CK_URL = "https://api.cardkingdom.com/api/v2/pricelist"
CK_CACHE = Path.home() / ".cache" / "mtg-foreign-signed-finder" / "ck_pricelist.json"


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
    if args.signed == "signed":
        print("Card Kingdom doesn't sell signed cards, skipping.")
        return
    items = ck_load(args.cache_hours)
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
        word = m.group(1).lower() if m else None
        if word is None:
            code = "EN"
        elif word == "chinese":
            code = "CT" if "traditional" in text.lower() else "CS"
        else:
            code = CK_WORD_TO_CODE[word]
        is_foil = str(it.get("is_foil")).lower() == "true"
        if code in args.langs and finish_ok(is_foil, args.finish):
            foreign.append((code, is_foil, it))
    if not foreign:
        print("No matching printings (language is based on the variant description).")
        return
    for code, is_foil, it in foreign:
        foil = "Foil" if is_foil else "Normal"
        lang = f"{code} {LANGS[code][0]}"
        var = f" ({it['variation']})" if it.get("variation") else ""
        print(f"\n[{it.get('edition')}] {it.get('name')}{var}")
        print(f"  https://www.cardkingdom.com/{str(it.get('url', '')).lstrip('/')}")
        print(f"    {lang:<15} {foil:<8} ${it.get('price_retail')}   in stock: {it.get('qty_retail')}")
    print(f"\nCard Kingdom summary: {len(foreign)} matching printings.")


# ---------------- Cardmarket ----------------
# Cardmarket's website is behind Cloudflare and its API needs a seller account,
# so listings can't be read. Its public catalog and price guide downloads are open:
# they give every printing and its prices (all languages together), and the script
# builds product links with Cardmarket's own filters already applied.
CM_PRODUCTS_URL = "https://downloads.s3.cardmarket.com/productCatalog/productList/products_singles_1.json"
CM_PRICES_URL = "https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_1.json"
CM_PRODUCT_PAGE = "https://www.cardmarket.com/en/Magic/Products"
SCRYFALL_SEARCH = "https://api.scryfall.com/cards/search"
# Cardmarket idLanguage numbers. It has no Phyrexian
CM_LANG_ID = {"EN": 1, "FR": 2, "DE": 3, "SP": 4, "IT": 5, "CS": 6,
              "JP": 7, "PT": 8, "RU": 9, "KR": 10, "CT": 11}


def cached_json(url, filename, max_age_h, msg):
    path = CK_CACHE.parent / filename
    if path.exists() and time.time() - path.stat().st_mtime < max_age_h * 3600:
        text = path.read_text()
    else:
        print(msg)
        r = requests.get(url, headers={"User-Agent": UA}, timeout=180)
        r.raise_for_status()
        text = r.text
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return json.loads(text)


def scryfall_sets(name):
    """Cardmarket idProduct -> (set name, release date), from Scryfall."""
    out = {}
    s = requests.Session()
    s.headers.update({"User-Agent": "mtg-foreign-signed-finder/1.0", "Accept": "application/json"})
    url = SCRYFALL_SEARCH
    params = {"q": f'!"{name}"', "unique": "prints",
              "include_extras": "true", "include_variations": "true"}
    while url:
        r = s.get(url, params=params, timeout=30)
        if r.status_code == 404:  # no such card
            break
        r.raise_for_status()
        d = r.json()
        for c in d.get("data", []):
            if c.get("cardmarket_id"):
                out[c["cardmarket_id"]] = (c.get("set_name", ""), c.get("released_at", ""))
        url, params = (d.get("next_page"), None) if d.get("has_more") else (None, None)
        time.sleep(0.1)  # Scryfall asks for 50-100 ms between requests
    return out


def cm_link(pid, code, args):
    q = {"idProduct": pid}
    if code:
        q["language"] = CM_LANG_ID[code]
    if args.finish != "all":
        q["isFoil"] = "Y" if args.finish == "foil" else "N"
    if args.signed != "all":
        q["isSigned"] = "Y" if args.signed == "signed" else "N"
    return f"{CM_PRODUCT_PAGE}?{urlencode(q)}"


def euro(v):
    return f"€{v:.2f}" if v else "-"


def run_cm(name, args):
    print(f"\n{describe_search('Cardmarket', name, args)}")
    usable = [c for c in args.langs if c in CM_LANG_ID]
    if not usable:
        print("Cardmarket has no filter for these languages, skipping.")
        return
    products = cached_json(CM_PRODUCTS_URL, "cm_products.json", args.cache_hours,
                           "Downloading the Cardmarket catalog (large file, will be cached)...")["products"]
    matches = [p for p in products if name_matches(name, p.get("name", ""), args.fuzzy)
               and not p.get("name", "").startswith("Art Series:")]  # art cards, not playable
    if not matches:
        print("Nothing found. Check the spelling (use the English card name), or try --fuzzy.")
        return
    guide = cached_json(CM_PRICES_URL, "cm_price_guide.json", args.cache_hours,
                        "Downloading the Cardmarket price guide (large file, will be cached)...")
    prices = {g["idProduct"]: g for g in guide.get("priceGuides", [])}
    try:
        sets = scryfall_sets(name)
    except requests.RequestException as e:
        print(f"  ! Couldn't get set names from Scryfall ({e}), showing expansion ids")
        sets = {}
    matches.sort(key=lambda p: sets.get(p["idProduct"], ("", ""))[1], reverse=True)
    matches = matches[:args.max_products]

    # The default language set means "don't filter by language" on the page
    default_langs = set(args.langs) in (set(FOREIGN), set(LANGS))
    link_langs = [None] if default_langs else usable
    print(f"=== Cardmarket: {len(matches)} matching printings ===")
    print("Cardmarket blocks scripts, so stock can't be checked here.")
    print("Each link opens the printing with the filters already applied.")
    if default_langs and set(args.langs) == set(FOREIGN):
        print("Links aren't filtered by language (the page will include English); "
              "pick one with -l for language-filtered links.")
    left_out = [LANGS[c][0] for c in args.langs if c not in CM_LANG_ID and not default_langs]
    if left_out:
        print(f"Cardmarket has no filter for {', '.join(left_out)}, left out.")

    for p in matches:
        pid = p["idProduct"]
        set_name = sets.get(pid, (f"Cardmarket expansion #{p.get('idExpansion')}", ""))[0]
        g = prices.get(pid, {})
        print(f"\n[{set_name}] {p['name']}")
        parts = []
        if args.finish != "foil":
            parts.append(f"Normal from {euro(g.get('low'))}, trend {euro(g.get('trend'))}")
        if args.finish != "nonfoil" and (g.get("low-foil") or g.get("trend-foil")):
            parts.append(f"Foil from {euro(g.get('low-foil'))}, trend {euro(g.get('trend-foil'))}")
        if parts:
            print(f"  Price guide (all languages): {' | '.join(parts)}")
        for code in link_langs:
            label = f"{code} {LANGS[code][0]}: " if code else ""
            print(f"    {label}{cm_link(pid, code, args)}")
    print(f"\nCardmarket summary: {len(matches)} printing(s) listed (open the links to check stock).")


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
                    choices=["all", "tcg", "tcgplayer", "ck", "cardkingdom", "cm", "cardmarket"],
                    help="search one site only (default: TCGplayer and Card Kingdom; "
                         "cm/cardmarket = Cardmarket only)")
    ap.add_argument("--lang", "-l", dest="langs", type=parse_langs, default=None,
                    help="only these languages, comma separated, e.g. --lang jp,cs or -l zh "
                         "(default: every language except English, or every language with --signed; "
                         "add en to include English)")
    fin = ap.add_mutually_exclusive_group()
    fin.add_argument("--foil", dest="finish", action="store_const", const="foil",
                     help="foils only")
    fin.add_argument("--nonfoil", dest="finish", action="store_const", const="nonfoil",
                     help="non-foils only")
    sig = ap.add_mutually_exclusive_group()
    sig.add_argument("--signed", dest="signed", action="store_const", const="signed",
                     help="signed cards only, any language unless --lang is given "
                          "(TCGplayer reads the seller's listing text; Cardmarket gets a filtered link; "
                          "Card Kingdom has none)")
    sig.add_argument("--unsigned", dest="signed", action="store_const", const="unsigned",
                     help="leave out signed cards")
    ap.set_defaults(finish="all", signed="all")
    ap.add_argument("--cardmarket", "--cm", action="store_true",
                    help="also search Cardmarket (off by default; gives filtered links, "
                         "since Cardmarket blocks scripts)")
    ap.add_argument("--fuzzy", action="store_true", help="looser name matching (substring)")
    ap.add_argument("--delay", type=float, default=0.7, help="seconds between requests")
    ap.add_argument("--max-products", type=int, default=80,
                    help="max number of printings to check on TCGplayer / list on Cardmarket")
    ap.add_argument("--cache-hours", "--ck-cache-hours", dest="cache_hours", type=float, default=12,
                    help="how long to reuse the downloaded Card Kingdom / Cardmarket files")
    ap.add_argument("--debug", action="store_true", help="print raw API fields")
    args = ap.parse_args()
    args.site = {"tcgplayer": "tcg", "cardkingdom": "ck", "cardmarket": "cm"}.get(args.site, args.site)
    if args.langs is None:  # --signed means any language; otherwise foreign only
        args.langs = list(LANGS) if args.signed == "signed" else list(FOREIGN)

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
    if args.site == "cm" or args.cardmarket:
        try:
            run_cm(args.name, args)
        except Exception as e:
            print(f"Cardmarket error: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
