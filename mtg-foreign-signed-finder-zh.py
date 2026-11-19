#!/usr/bin/env python3
"""
mtg-foreign-signed-finder-zh.py：查一张万智牌在 TCGplayer 和 Card Kingdom 上，哪些版本有外语（非英文）在卖。
这是中文版，功能和 mtg-foreign-signed-finder.py 完全一样，只是提示和输出是中文。

用法:
  python3 mtg-foreign-signed-finder-zh.py "Lightning Bolt"
  python3 mtg-foreign-signed-finder-zh.py "Sol Ring" --site tcg
  python3 mtg-foreign-signed-finder-zh.py "Simic Signet" -l 法语 --foil
  python3 mtg-foreign-signed-finder-zh.py "Sol Ring" -l fr,de,jp
  python3 mtg-foreign-signed-finder-zh.py "Lightning Bolt" -l 英语,日语 --signed
  python3 mtg-foreign-signed-finder-zh.py "Liliana, Dreadhorde General" --site ck
  python3 mtg-foreign-signed-finder-zh.py "Lightning Bolt" --debug     # 打印接口原始字段，排查用

依赖: pip install requests
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
from unicodedata import east_asian_width

import requests

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

# 语言代码 -> (TCGplayer 的语言名, 中文名, 可以接受的别名)。代码取 TCGplayer 的 languageAbbreviation
LANGS = {
    "EN": ("English",     "英语",     ["eng", "english", "英", "英语", "英文"]),
    "JP": ("Japanese",    "日语",     ["ja", "jpn", "japanese", "日", "日语", "日文"]),
    "CS": ("Chinese (S)", "简体中文", ["zhs", "chs", "sc", "simplified", "简", "简体", "简中", "简体中文"]),
    "CT": ("Chinese (T)", "繁体中文", ["zht", "cht", "tc", "traditional", "繁", "繁体", "繁中", "繁体中文"]),
    "KR": ("Korean",      "韩语",     ["ko", "kor", "korean", "韩", "韩语", "韩文"]),
    "DE": ("German",      "德语",     ["ger", "deu", "german", "德", "德语", "德文"]),
    "FR": ("French",      "法语",     ["fra", "fre", "french", "法", "法语", "法文"]),
    "IT": ("Italian",     "意大利语", ["ita", "italian", "意", "意语", "意大利语", "意大利文"]),
    "SP": ("Spanish",     "西班牙语", ["es", "spa", "spanish", "西", "西语", "西班牙语", "西班牙文"]),
    "PT": ("Portuguese",  "葡萄牙语", ["por", "portuguese", "葡", "葡语", "葡萄牙语", "葡萄牙文"]),
    "RU": ("Russian",     "俄语",     ["rus", "russian", "俄", "俄语", "俄文"]),
    "PH": ("Phyrexian",   "非瑞克西亚语", ["phy", "phyrexian", "非瑞克西亚", "非瑞克西亚语"]),
}
# 一个别名展开成多个代码
LANG_GROUPS = {"zh": ["CS", "CT"], "cn": ["CS", "CT"], "chinese": ["CS", "CT"],
               "中": ["CS", "CT"], "中文": ["CS", "CT"]}
TCG_NAME_TO_CODE = {name: code for code, (name, _, _) in LANGS.items()}
FINISH_ZH = {"Foil": "闪", "Normal": "平"}
# 默认：除英语以外的所有语言
FOREIGN = [c for c in LANGS if c != "EN"]

# TCGplayer 上的签名卡都是卖家拍照的 custom 挂单，签名信息写在卖家填的标题/描述里。
# 先去掉只是看起来像签名的词（如 Signature Spellbook 系列、Signature Foil 版本、not signed）
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
    """卖家写的标题，描述有新内容时也带上"""
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

# Card Kingdom 版本描述里出现这些词，视为外语版本
LANG_RE = re.compile(
    r"\b(japanese|jpn|jp|chinese|korean|german|french|italian|spanish|"
    r"portuguese|russian|phyrexian)\b", re.I)
CK_WORD_TO_CODE = {"japanese": "JP", "jpn": "JP", "jp": "JP", "korean": "KR",
                   "german": "DE", "french": "FR", "italian": "IT", "spanish": "SP",
                   "portuguese": "PT", "russian": "RU", "phyrexian": "PH"}


def parse_langs(value: str):
    """'jp,cs' / 'ja zh' / '法语,德语' -> ['JP', 'CS']"""
    codes = []
    for tok in re.split(r"[,，、\s]+", value.strip()):
        t = tok.lower()
        if not t:
            continue
        if t in LANG_GROUPS:
            found = LANG_GROUPS[t]
        else:
            found = [c for c, (name, zh, aliases) in LANGS.items()
                     if t == c.lower() or t == name.lower() or t in aliases]
        if not found:
            raise argparse.ArgumentTypeError(
                f"不认识的语言 '{tok}'，可用代码: {', '.join(LANGS)}（或 zh = 简繁中文）")
        codes += [c for c in found if c not in codes]
    return codes


def finish_ok(is_foil: bool, finish: str) -> bool:
    return finish == "all" or (finish == "foil") == is_foil


def describe_search(site: str, name: str, args) -> str:
    """例如 '正在 TCGplayer 上找法语闪的 Simic Signet...'"""
    if set(args.langs) == set(FOREIGN):
        lang = "外语"
    elif set(args.langs) == set(LANGS):
        lang = "任意语言"
    else:
        names = [LANGS[c][1] for c in args.langs]
        lang = names[0] if len(names) == 1 else "、".join(names[:-1]) + "或" + names[-1]
    signed = {"signed": "签名", "unsigned": "无签名"}.get(args.signed, "")
    finish = {"foil": "闪", "nonfoil": "平"}.get(args.finish, "")
    what = lang + signed + finish
    return f"正在 {site} 上找{what}的 {name}..." if what else f"正在 {site} 上找 {name}..."


def pad(s: str, width: int) -> str:
    """按终端显示宽度补空格（中文字符算两格）"""
    w = sum(2 if east_asian_width(ch) in "WF" else 1 for ch in s)
    return s + " " * max(0, width - w)


def progress(msg: str):
    """在 stderr 上原地刷新的一行进度（只在终端里显示）"""
    if sys.stderr.isatty():
        sys.stderr.write("\r\033[K" + msg)
        sys.stderr.flush()


# ---------------- 通用 ----------------
def base_name(s: str) -> str:
    """去掉括号里的版本说明，例如 'Lightning Bolt (Borderless)' -> 'lightning bolt'"""
    return re.sub(r"\s*[\(\[].*?[\)\]]", "", s).strip().lower()


def name_matches(query: str, product_name: str, fuzzy: bool = False) -> bool:
    q = query.strip().lower()
    b = base_name(product_name)
    if b == q:
        return True
    if q in [f.strip() for f in b.split("//")]:  # 分体牌（双面牌两家网站都只用正面名字）
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
    for _ in range(6):  # 最多翻 6 页搜索结果
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
            print(f"[debug] TCG 搜索 totalResults={block.get('totalResults')}")
            if items:
                print("[debug] 第一条结果的字段:", sorted(items[0].keys()))
        hits = 0
        for it in items:
            pname = it.get("productName", "")
            if name_matches(name, pname, fuzzy):
                hits += 1
                products.append({"id": int(it["productId"]), "name": pname,
                                 "set": it.get("setName", "")})
        frm += size
        # 结果按相关度排序：已经找到过、这一页又一个都没匹配上，就停
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
    print(f"=== TCGplayer：找到 {len(products)} 个匹配的版本，逐个查挂单 ===")
    if not products:
        print("没找到。检查牌名拼写（用英文名），或加 --fuzzy。")
        return

    if args.debug:  # 不加语言过滤看一页，核对语言字段的真实取值
        sample = tcg_listings(s, products[0]["id"], None, args.delay, max_pages=1)
        print(f"[debug] {products[0]['name']} 的挂单语言分布:",
              Counter(x.get("language") for x in sample))
        if sample:
            print("[debug] 挂单字段:", sorted(sample[0].keys()))

    tcg_langs = [LANGS[c][0] for c in args.langs]
    # 签名卡一定是拍照挂单，直接让接口只返回这类
    types = ["custom"] if args.signed == "signed" else None
    found, warned = 0, False
    for i, p in enumerate(products, 1):
        progress(f"  [{i}/{len(products)}] {p['set']}")
        time.sleep(args.delay)
        try:
            items = tcg_listings(s, p["id"], tcg_langs, args.delay, listing_types=types)
        except requests.HTTPError as e:
            progress("")
            print(f"  ! {p['set']} / {p['name']}：请求失败 {e}")
            continue
        if any(x.get("language") not in tcg_langs for x in items) and not warned:
            progress("")
            print("  ! 注意：语言过滤似乎没生效，已在本地排除其他语言的挂单")
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
            if args.signed == "signed":  # 签名卡每张都不一样，逐条列出
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
            zh = LANGS[code][1] if code in LANGS else lang
            print(f"    {code} {pad(zh, 12)} {FINISH_ZH.get(printing, printing)}"
                  f"  {g['n']:>3} 条挂单 / 共 {g['qty']:>3} 张   最低 ${g['min']:.2f}")
        for x in signed_rows:
            code = TCG_NAME_TO_CODE.get(x.get("language"), "??")
            zh = LANGS[code][1] if code in LANGS else x.get("language", "?")
            print(f"    {code} {pad(zh, 12)} {FINISH_ZH.get(x.get('printing'), x.get('printing', '?'))}"
                  f"  ${float(x.get('price') or 0):>8.2f}  {x.get('condition', '')}"
                  f"  [{x.get('sellerName', '')}]\n        \"{listing_title(x)}\"")
    progress("")
    print(f"\nTCGplayer 小结：{len(products)} 个版本里，{found} 个有符合条件的挂单。")


# ---------------- Card Kingdom ----------------
CK_URL = "https://api.cardkingdom.com/api/v2/pricelist"
CK_CACHE = Path.home() / ".cache" / "mtg-foreign-signed-finder" / "ck_pricelist.json"


def ck_load(max_age_h):
    if CK_CACHE.exists() and time.time() - CK_CACHE.stat().st_mtime < max_age_h * 3600:
        text = CK_CACHE.read_text()
    else:
        print("下载 Card Kingdom 全量价格表（文件较大，会缓存）...")
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
        print("Card Kingdom 不卖签名卡，跳过。")
        return
    items = ck_load(args.cache_hours)
    matches = [it for it in items if name_matches(name, it.get("name", ""), args.fuzzy)]
    print(f"=== Card Kingdom：价格表里有 {len(matches)} 条匹配 ===")
    if args.debug:
        if items:
            print("[debug] 价格表字段:", sorted(items[0].keys()))
        for it in matches:
            print("[debug]", it.get("sku"), "|", it.get("edition"), "|",
                  it.get("name"), "|", it.get("variation"), "| foil:", it.get("is_foil"))

    foreign = []
    for it in matches:
        # 只看版本描述和系列名，不看牌名，否则 "Phyrexian Arena" 这类牌会被误判
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
        print("没有符合条件的版本（语言按版本描述判断）。")
        return
    for code, is_foil, it in foreign:
        var = f" ({it['variation']})" if it.get("variation") else ""
        print(f"\n[{it.get('edition')}] {it.get('name')}{var}")
        print(f"  https://www.cardkingdom.com/{str(it.get('url', '')).lstrip('/')}")
        print(f"    {code} {pad(LANGS[code][1], 12)} {'闪' if is_foil else '平'}"
              f"  售价 ${it.get('price_retail')}   库存 {it.get('qty_retail')}")
    print(f"\nCard Kingdom 小结：{len(foreign)} 条符合条件的版本。")


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
        print("Cardmarket 没有这些语言的筛选，跳过。")
        return
    products = cached_json(CM_PRODUCTS_URL, "cm_products.json", args.cache_hours,
                           "下载 Cardmarket 商品目录（文件较大，会缓存）...")["products"]
    matches = [p for p in products if name_matches(name, p.get("name", ""), args.fuzzy)
               and not p.get("name", "").startswith("Art Series:")]  # art cards, not playable
    if not matches:
        print("没找到。检查牌名拼写（用英文名），或加 --fuzzy。")
        return
    guide = cached_json(CM_PRICES_URL, "cm_price_guide.json", args.cache_hours,
                        "下载 Cardmarket 价格指导（文件较大，会缓存）...")
    prices = {g["idProduct"]: g for g in guide.get("priceGuides", [])}
    try:
        sets = scryfall_sets(name)
    except requests.RequestException as e:
        print(f"  ! 没能从 Scryfall 拿到系列名（{e}），用系列编号代替")
        sets = {}
    matches.sort(key=lambda p: sets.get(p["idProduct"], ("", ""))[1], reverse=True)
    matches = matches[:args.max_products]

    # 默认的语言范围在页面上就是"不按语言筛选"
    default_langs = set(args.langs) in (set(FOREIGN), set(LANGS))
    link_langs = [None] if default_langs else usable
    print(f"=== Cardmarket：找到 {len(matches)} 个匹配的版本 ===")
    print("Cardmarket 有反爬，脚本没法确认有没有货。")
    print("每个链接打开就是已经套好筛选条件的商品页。")
    if default_langs and set(args.langs) == set(FOREIGN):
        print("链接没有按语言筛选（页面里会包含英文挂单）；用 -l 指定语言可以得到按语言筛选的链接。")
    left_out = [LANGS[c][1] for c in args.langs if c not in CM_LANG_ID and not default_langs]
    if left_out:
        print(f"Cardmarket 没有{'、'.join(left_out)}的筛选，已略过。")

    for p in matches:
        pid = p["idProduct"]
        set_name = sets.get(pid, (f"Cardmarket 系列 #{p.get('idExpansion')}", ""))[0]
        g = prices.get(pid, {})
        print(f"\n[{set_name}] {p['name']}")
        parts = []
        if args.finish != "foil":
            parts.append(f"平 最低 {euro(g.get('low'))}，趋势 {euro(g.get('trend'))}")
        if args.finish != "nonfoil" and (g.get("low-foil") or g.get("trend-foil")):
            parts.append(f"闪 最低 {euro(g.get('low-foil'))}，趋势 {euro(g.get('trend-foil'))}")
        if parts:
            print(f"  价格指导（所有语言合计）：{' | '.join(parts)}")
        for code in link_langs:
            label = f"{code} {LANGS[code][1]}：" if code else ""
            print(f"    {label}{cm_link(pid, code, args)}")
    print(f"\nCardmarket 小结：列出 {len(matches)} 个版本（打开链接查看有没有货）。")


# ---------------- main ----------------
def main():
    lang_help = "  ".join(f"{c}={zh}" for c, (_, zh, _) in LANGS.items())
    ap = argparse.ArgumentParser(
        description="查万智牌在 TCGplayer / Card Kingdom 的外语版本",
        epilog=f"语言代码: {lang_help}  zh=简繁中文都要。"
               "也接受 ja/ko/es/de/fr 等常见缩写、英文全名和中文名（如 法语、日文），大小写不限。")
    ap.add_argument("name", help="牌的英文名，例如 \"Lightning Bolt\"")
    ap.add_argument("--site", default="all",
                    choices=["all", "tcg", "tcgplayer", "ck", "cardkingdom", "cm", "cardmarket"],
                    help="只查某一家，默认查 TCGplayer 和 Card Kingdom；cm/cardmarket = 只查 Cardmarket")
    ap.add_argument("--lang", "-l", dest="langs", type=parse_langs, default=None,
                    help="只看这些语言，多个用逗号分隔，例如 -l fr,de,jp 或 -l 法语,德语"
                         "（默认除英语外的所有语言，用 --signed 时默认所有语言；加 en 可以包含英语）")
    fin = ap.add_mutually_exclusive_group()
    fin.add_argument("--foil", dest="finish", action="store_const", const="foil",
                     help="只看闪卡")
    fin.add_argument("--nonfoil", dest="finish", action="store_const", const="nonfoil",
                     help="只看平卡")
    sig = ap.add_mutually_exclusive_group()
    sig.add_argument("--signed", dest="signed", action="store_const", const="signed",
                     help="只看签名卡，不加 -l 时不限语言（TCGplayer 按卖家写的挂单文字判断；Cardmarket 给出筛选链接；Card Kingdom 不支持）")
    sig.add_argument("--unsigned", dest="signed", action="store_const", const="unsigned",
                     help="排除签名卡")
    ap.set_defaults(finish="all", signed="all")
    ap.add_argument("--cardmarket", "--cm", action="store_true",
                    help="同时查 Cardmarket（默认不查；Cardmarket 有反爬，给出套好筛选的链接）")
    ap.add_argument("--fuzzy", action="store_true", help="放宽名称匹配（包含即可）")
    ap.add_argument("--delay", type=float, default=0.7, help="每次请求间隔秒数")
    ap.add_argument("--max-products", type=int, default=80, help="TCGplayer 最多查几个版本 / Cardmarket 最多列几个版本")
    ap.add_argument("--cache-hours", "--ck-cache-hours", dest="cache_hours", type=float, default=12,
                    help="Card Kingdom / Cardmarket 下载的数据缓存多少小时")
    ap.add_argument("--debug", action="store_true", help="打印接口原始字段")
    args = ap.parse_args()
    args.site = {"tcgplayer": "tcg", "cardkingdom": "ck", "cardmarket": "cm"}.get(args.site, args.site)
    if args.langs is None:  # --signed means any language; otherwise foreign only
        args.langs = list(LANGS) if args.signed == "signed" else list(FOREIGN)

    if args.site in ("all", "tcg"):
        try:
            run_tcg(args.name, args)
        except Exception as e:
            progress("")
            print(f"TCGplayer 出错：{e}", file=sys.stderr)
    if args.site in ("all", "ck"):
        try:
            run_ck(args.name, args)
        except Exception as e:
            print(f"Card Kingdom 出错：{e}", file=sys.stderr)
    if args.site == "cm" or args.cardmarket:
        try:
            run_cm(args.name, args)
        except Exception as e:
            print(f"Cardmarket 出错：{e}", file=sys.stderr)


if __name__ == "__main__":
    main()
