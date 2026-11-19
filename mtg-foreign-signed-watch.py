#!/usr/bin/env python3
"""
mtg-foreign-signed-watch.py - keep watching for cards that aren't for sale yet.

Add the cards you're waiting for to a watch list, then let it check every day
and send a macOS notification when a new matching listing shows up.
Uses the same filters as mtg-foreign-signed-finder.py.

Usage:
  python3 mtg-foreign-signed-watch.py add "Demonic Tutor" -l fr --signed
  python3 mtg-foreign-signed-watch.py add "Sol Ring" -l jp --foil
  python3 mtg-foreign-signed-watch.py list
  python3 mtg-foreign-signed-watch.py remove 2
  python3 mtg-foreign-signed-watch.py check          # check everything now
  python3 mtg-foreign-signed-watch.py report         # show the last check's results
  python3 mtg-foreign-signed-watch.py schedule 09:00 # check every day at 9:00
  python3 mtg-foreign-signed-watch.py unschedule

Add --zh anywhere for Chinese output (the schedule remembers it).
Checks TCGplayer and Card Kingdom. Cardmarket can't be watched (it blocks scripts).
"""
import argparse
import importlib.util
import json
import os
import plistlib
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(filename):
    spec = importlib.util.spec_from_file_location(filename.replace("-", "_"), HERE / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


F = _load("mtg-foreign-signed-finder.py")      # search logic + English wording
Z = _load("mtg-foreign-signed-finder-zh.py")   # Chinese wording

# MTG_WATCH_HOME lets you keep a separate watch list (handy for testing)
HOME = Path(os.environ.get("MTG_WATCH_HOME", Path.home() / ".config" / "mtg-foreign-signed-finder"))
WATCHLIST = HOME / "watchlist.json"
REPORT = HOME / "last-report.txt"
LOG = HOME / "watch.log"
LABEL = "com.mtg-foreign-signed-finder.watch"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"

ZH = False


def T(en, zh):
    return zh if ZH else en


# ---------------- watch list ----------------
def load():
    if WATCHLIST.exists():
        return json.loads(WATCHLIST.read_text())
    return {"next_id": 1, "watches": []}


def save(data):
    HOME.mkdir(parents=True, exist_ok=True)
    tmp = WATCHLIST.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(WATCHLIST)


def ns_for(w):
    return argparse.Namespace(langs=w["langs"], finish=w["finish"], signed=w["signed"],
                              fuzzy=w.get("fuzzy", False), delay=0.7,
                              max_products=w.get("max_products", 80), cache_hours=12, debug=False)


def describe(w):
    """'French signed Demonic Tutor' / '法语签名的 Demonic Tutor'"""
    ns = ns_for(w)
    if ZH:
        return Z.describe_search("X", w["name"], ns).split("上找", 1)[1].rstrip(".")
    return F.describe_search("X", w["name"], ns).split(" for ", 1)[1].rstrip(".")


def site_names(w):
    return ", ".join({"tcg": "TCGplayer", "ck": "Card Kingdom"}[s] for s in w["sites"])


# ---------------- checking ----------------
def check_tcg(w, ns):
    s = F.tcg_session()
    products = F.tcg_search(s, w["name"], ns.delay, ns.max_products, ns.fuzzy, False)
    tcg_langs = [F.LANGS[c][0] for c in ns.langs]
    types = ["custom"] if ns.signed == "signed" else None
    hits = []
    for i, p in enumerate(products, 1):
        F.progress(f"  TCGplayer [{i}/{len(products)}] {p['set']}")
        time.sleep(ns.delay)
        for x in F.tcg_listings(s, p["id"], tcg_langs, ns.delay, listing_types=types):
            if x.get("language") not in tcg_langs:
                continue
            if not F.finish_ok(str(x.get("printing", "")).lower() == "foil", ns.finish):
                continue
            if not F.signed_ok(F.is_signed(x), ns.signed):
                continue
            hits.append({
                "key": f"tcg:{p['id']}:{int(x.get('listingId') or 0)}",
                "site": "TCGplayer", "set": p["set"], "code": F.TCG_NAME_TO_CODE.get(x.get("language"), "??"),
                "foil": str(x.get("printing", "")).lower() == "foil",
                "price": float(x.get("price") or 0), "qty": int(x.get("quantity") or 0),
                "condition": x.get("condition", ""), "seller": x.get("sellerName", ""),
                "title": F.listing_title(x) if x.get("listingType") == "custom" else "",
                "url": f"https://www.tcgplayer.com/product/{p['id']}",
            })
    F.progress("")
    return hits


def check_ck(w, ns):
    if ns.signed == "signed":  # Card Kingdom doesn't sell signed cards
        return []
    hits = []
    for it in F.ck_load(ns.cache_hours):
        if not F.name_matches(w["name"], it.get("name", ""), ns.fuzzy):
            continue
        if int(it.get("qty_retail") or 0) <= 0:  # out of stock
            continue
        text = " ".join(str(it.get(k) or "") for k in ("variation", "edition"))
        m = F.LANG_RE.search(text)
        word = m.group(1).lower() if m else None
        if word is None:
            code = "EN"
        elif word == "chinese":
            code = "CT" if "traditional" in text.lower() else "CS"
        else:
            code = F.CK_WORD_TO_CODE[word]
        is_foil = str(it.get("is_foil")).lower() == "true"
        if code not in ns.langs or not F.finish_ok(is_foil, ns.finish):
            continue
        var = f" ({it['variation']})" if it.get("variation") else ""
        hits.append({
            "key": f"ck:{it.get('sku')}", "site": "Card Kingdom", "set": f"{it.get('edition')}{var}",
            "code": code, "foil": is_foil, "price": float(it.get("price_retail") or 0),
            "qty": int(it.get("qty_retail") or 0), "condition": "", "seller": "", "title": "",
            "url": f"https://www.cardkingdom.com/{str(it.get('url', '')).lstrip('/')}",
        })
    return hits


def check_one(w):
    """Returns (hits, errors)."""
    ns = ns_for(w)
    hits, errors = [], []
    for site, fn in (("tcg", check_tcg), ("ck", check_ck)):
        if site not in w["sites"]:
            continue
        try:
            hits += fn(w, ns)
        except Exception as e:  # one site failing shouldn't stop the rest
            F.progress("")
            errors.append(f"{'TCGplayer' if site == 'tcg' else 'Card Kingdom'}: {e}")
    return hits, errors


def format_hit(h, new):
    lang = Z.LANGS[h["code"]][1] if ZH and h["code"] in Z.LANGS else F.LANGS.get(h["code"], ("?",))[0]
    finish = T("Foil" if h["foil"] else "Normal", "闪" if h["foil"] else "平")
    tag = T("NEW ", "新 ") if new else "    "
    extra = "  ".join(x for x in (h["condition"], f"[{h['seller']}]" if h["seller"] else "") if x)
    line = (f"  {tag} {h['site']:<12} [{h['set']}]  {h['code']} {lang} {finish}"
            f"  ${h['price']:.2f} x{h['qty']}  {extra}".rstrip())
    if h["title"]:
        line += f"\n           \"{h['title']}\""
    return line + f"\n           {h['url']}"


def run_checks(data, ids=None):
    """Check watches, update what's been seen. Returns (report_lines, new_count, error_count, cards_with_new)."""
    lines, new_total, err_total, cards = [], 0, 0, []
    for w in data["watches"]:
        if ids and w["id"] not in ids:
            continue
        print(T(f"Checking [{w['id']}] {describe(w)}...", f"正在查 [{w['id']}] {describe(w)}..."))
        hits, errors = check_one(w)
        seen = set(w.get("seen", []))
        new = [h for h in hits if h["key"] not in seen]
        w["seen"] = sorted(seen | {h["key"] for h in hits})
        w["last_checked"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        w["last_count"] = len(hits)
        new_total += len(new)
        err_total += len(errors)
        if new:
            cards.append(describe(w))
        head = T(f"[{w['id']}] {describe(w)}  ({site_names(w)}): {len(hits)} listing(s), {len(new)} new",
                 f"[{w['id']}] {describe(w)}（{site_names(w)}）：{len(hits)} 条挂单，其中 {len(new)} 条是新的")
        block = [head]
        for h in sorted(hits, key=lambda h: (h["key"] in seen, h["price"])):
            block.append(format_hit(h, h["key"] not in seen))
        for e in errors:
            block.append(T(f"  ! error: {e}", f"  ! 出错：{e}"))
        if not hits and not errors:
            block.append(T("  Nothing yet.", "  暂时没有。"))
        print("\n".join(block) + "\n")
        lines += block + [""]
    return lines, new_total, err_total, cards


def notify(title, message):
    script = f"display notification {json.dumps(message)} with title {json.dumps(title)} sound name \"Glass\""
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)


# ---------------- commands ----------------
def cmd_add(args):
    data = load()
    langs = args.langs
    if langs is None:  # same default as the finder: --signed = any language, else foreign only
        langs = list(F.LANGS) if args.signed == "signed" else list(F.FOREIGN)
    sites = {"all": ["tcg", "ck"], "tcg": ["tcg"], "tcgplayer": ["tcg"],
             "ck": ["ck"], "cardkingdom": ["ck"]}[args.site]
    w = {"id": data["next_id"], "name": args.name, "langs": langs, "finish": args.finish,
         "signed": args.signed, "sites": sites, "fuzzy": args.fuzzy,
         "max_products": args.max_products, "added": datetime.now().strftime("%Y-%m-%d"), "seen": []}
    if args.signed == "signed":  # Card Kingdom doesn't sell signed cards
        sites = [x for x in sites if x != "ck"]
        w["sites"] = sites
    if not sites:
        print(T("Card Kingdom doesn't sell signed cards, so this watch would never find anything.",
                "Card Kingdom 不卖签名卡，这样蹲永远不会有结果。"))
        return
    data["next_id"] += 1
    data["watches"].append(w)
    save(data)
    print(T(f"Added [{w['id']}]: {describe(w)} ({site_names(w)})",
            f"已添加 [{w['id']}]：{describe(w)}（{site_names(w)}）"))
    if args.no_check:
        return
    print(T("Checking what's there right now...", "先查一下现在有没有..."))
    run_checks(data, ids={w["id"]})
    save(data)
    print(T("From now on you'll only be notified about listings that are new.",
            "之后只会提醒新出现的挂单。"))
    if not PLIST.exists():
        print(T("Tip: run 'schedule' to check automatically every day.",
                "提示：运行 schedule 可以设置每天自动检查。"))


def cmd_list(args):
    data = load()
    if not data["watches"]:
        print(T("The watch list is empty. Add a card with 'add'.", "蹲卡清单是空的，用 add 添加。"))
    for w in data["watches"]:
        last = w.get("last_checked")
        status = (T(f"last checked {last}, {w.get('last_count', 0)} listing(s)",
                    f"上次检查 {last}，{w.get('last_count', 0)} 条挂单") if last
                  else T("not checked yet", "还没检查过"))
        print(T(f"[{w['id']}] {describe(w)}  ({site_names(w)})  - {status}",
                f"[{w['id']}] {describe(w)}（{site_names(w)}）  {status}"))
    print()
    if PLIST.exists():
        cal = plistlib.loads(PLIST.read_bytes()).get("StartCalendarInterval", {})
        print(T(f"Daily check: on, at {cal.get('Hour', 0):02d}:{cal.get('Minute', 0):02d}",
                f"每日自动检查：已开启，每天 {cal.get('Hour', 0):02d}:{cal.get('Minute', 0):02d}"))
    else:
        print(T("Daily check: off (run 'schedule' to turn it on)",
                "每日自动检查：未开启（运行 schedule 开启）"))


def cmd_remove(args):
    data = load()
    before = len(data["watches"])
    gone = [w for w in data["watches"] if w["id"] in args.ids]
    data["watches"] = [w for w in data["watches"] if w["id"] not in args.ids]
    save(data)
    for w in gone:
        print(T(f"Removed [{w['id']}] {describe(w)}", f"已删除 [{w['id']}] {describe(w)}"))
    if len(data["watches"]) == before:
        print(T("No watch with that number. Use 'list' to see the numbers.",
                "没有这个编号，用 list 查看编号。"))


def cmd_check(args):
    data = load()
    if not data["watches"]:
        print(T("The watch list is empty. Add a card with 'add'.", "蹲卡清单是空的，用 add 添加。"))
        return
    started = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines, new_total, err_total, cards = run_checks(data, ids=set(args.ids) if args.ids else None)
    save(data)
    HOME.mkdir(parents=True, exist_ok=True)
    header = T(f"Check at {started}: {new_total} new listing(s)", f"{started} 检查结果：{new_total} 条新挂单")
    REPORT.write_text(header + "\n\n" + "\n".join(lines))
    print(header)
    print(T(f"Saved to {REPORT}", f"结果已保存到 {REPORT}"))
    if args.notify:
        if new_total:
            sep = T(", ", "、")
            what = sep.join(cards[:3]) + (T(" and more", " 等") if len(cards) > 3 else "")
            notify(T("MTG watch: new listings!", "蹲卡：有新挂单！"),
                   T(f"{new_total} new: {what}. Run 'report' for details.",
                     f"{what}：{new_total} 条新挂单。运行 report 查看详情。"))
        elif err_total:
            notify(T("MTG watch: check failed", "蹲卡：检查出错"),
                   T(f"{err_total} error(s). See {REPORT.name}.", f"有 {err_total} 处出错，详见 {REPORT.name}。"))


def cmd_report(args):
    if REPORT.exists():
        print(REPORT.read_text())
    else:
        print(T("No check has run yet.", "还没有检查过。"))


def launchctl(*a):
    return subprocess.run(["launchctl", *a], capture_output=True, text=True)


def cmd_schedule(args):
    try:
        hour, minute = (int(x) for x in args.time.split(":"))
        assert 0 <= hour < 24 and 0 <= minute < 60
    except (ValueError, AssertionError):
        sys.exit(T("Time must look like 09:00", "时间格式应为 09:00"))
    HOME.mkdir(parents=True, exist_ok=True)
    program = [sys.executable, str(Path(__file__).resolve()), "check", "--notify"] + (["--zh"] if ZH else [])
    plist = {"Label": LABEL, "ProgramArguments": program,
             "StartCalendarInterval": {"Hour": hour, "Minute": minute},
             "StandardOutPath": str(LOG), "StandardErrorPath": str(LOG)}
    if "MTG_WATCH_HOME" in os.environ:
        plist["EnvironmentVariables"] = {"MTG_WATCH_HOME": str(HOME)}
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    launchctl("bootout", domain, str(PLIST))
    PLIST.write_bytes(plistlib.dumps(plist))
    r = launchctl("bootstrap", domain, str(PLIST))
    if r.returncode != 0:
        sys.exit(T(f"launchctl failed: {r.stderr.strip()}", f"launchctl 出错：{r.stderr.strip()}"))
    print(T(f"Done. Every day at {hour:02d}:{minute:02d} the watch list is checked, "
            "and you get a notification when something new shows up.",
            f"设置好了。每天 {hour:02d}:{minute:02d} 会自动检查蹲卡清单，有新挂单时弹通知。"))
    print(T("If the Mac is asleep at that time, it checks when it wakes up.",
            "如果到点时电脑在睡眠，会在唤醒后补查。"))
    print(T(f"Log: {LOG}", f"日志：{LOG}"))


def cmd_unschedule(args):
    launchctl("bootout", f"gui/{os.getuid()}", str(PLIST))
    if PLIST.exists():
        PLIST.unlink()
        print(T("Daily check turned off.", "已关闭每日自动检查。"))
    else:
        print(T("Daily check wasn't on.", "每日自动检查本来就没开。"))


def main():
    global ZH
    if "--zh" in sys.argv:
        ZH = True
        sys.argv.remove("--zh")
    ap = argparse.ArgumentParser(
        description=T("Watch for cards and get notified when a matching listing shows up",
                      "蹲卡：有符合条件的挂单时通知你"))
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help=T("add a card to the watch list", "添加要蹲的卡"))
    a.add_argument("name", help=T("English card name", "牌的英文名"))
    a.add_argument("--lang", "-l", dest="langs", type=(Z.parse_langs if ZH else F.parse_langs), default=None,
                   help=T("languages, e.g. -l fr or -l fr,de,jp (default: non-English, or any with --signed)",
                          "语言，例如 -l 法语 或 -l fr,de,jp（默认外语；用 --signed 时默认任意语言）"))
    fin = a.add_mutually_exclusive_group()
    fin.add_argument("--foil", dest="finish", action="store_const", const="foil")
    fin.add_argument("--nonfoil", dest="finish", action="store_const", const="nonfoil")
    sig = a.add_mutually_exclusive_group()
    sig.add_argument("--signed", dest="signed", action="store_const", const="signed")
    sig.add_argument("--unsigned", dest="signed", action="store_const", const="unsigned")
    a.set_defaults(finish="all", signed="all")
    a.add_argument("--site", default="all", choices=["all", "tcg", "tcgplayer", "ck", "cardkingdom"])
    a.add_argument("--fuzzy", action="store_true")
    a.add_argument("--max-products", type=int, default=80)
    a.add_argument("--no-check", action="store_true",
                   help=T("don't check right away", "添加后不立刻检查"))
    a.set_defaults(func=cmd_add)

    sub.add_parser("list", help=T("show the watch list", "查看蹲卡清单")).set_defaults(func=cmd_list)

    r = sub.add_parser("remove", help=T("remove watches by number", "按编号删除"))
    r.add_argument("ids", type=int, nargs="+")
    r.set_defaults(func=cmd_remove)

    c = sub.add_parser("check", help=T("check now", "立刻检查"))
    c.add_argument("ids", type=int, nargs="*", help=T("only these numbers", "只查这些编号"))
    c.add_argument("--notify", action="store_true",
                   help=T("send a macOS notification when something new shows up", "有新挂单时弹系统通知"))
    c.set_defaults(func=cmd_check)

    sub.add_parser("report", help=T("show the last check's results", "查看上次检查结果")).set_defaults(func=cmd_report)

    s = sub.add_parser("schedule", help=T("check automatically every day", "设置每天自动检查"))
    s.add_argument("time", nargs="?", default="09:00", help=T("HH:MM, default 09:00", "时间 HH:MM，默认 09:00"))
    s.set_defaults(func=cmd_schedule)

    sub.add_parser("unschedule", help=T("stop the daily check", "关闭每天自动检查")).set_defaults(func=cmd_unschedule)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
