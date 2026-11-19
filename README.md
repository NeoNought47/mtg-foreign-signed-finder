# MTG Foreign & Signed Finder

**English** | [中文](#中文)

Look up a Magic: The Gathering card and find out which printings are sold in a non-English language on **TCGplayer** and **Card Kingdom**, with filters for language, foil/non-foil and signed cards.

Two scripts with identical features:

| Script | Output language |
| --- | --- |
| `mtg-foreign-signed-finder.py` | English |
| `mtg-foreign-signed-finder-zh.py` | Chinese (also accepts Chinese language names like `法语`) |

## Install

Requires Python 3.8+ and `requests`:

```bash
pip install requests
git clone https://github.com/NeoNought47/mtg-foreign-signed-finder.git
cd mtg-foreign-signed-finder
```

## Quick start

```bash
python3 mtg-foreign-signed-finder.py "Lightning Bolt"                      # every non-English printing on both sites
python3 mtg-foreign-signed-finder.py "Simic Signet" -l fr --foil           # French foils only
python3 mtg-foreign-signed-finder.py "Sol Ring" -l fr,de,jp                # French, German or Japanese
python3 mtg-foreign-signed-finder.py "Sol Ring" --site tcg --max-products 5
python3 mtg-foreign-signed-finder.py "Gala Greeters" --site cardkingdom -l zh --nonfoil
python3 mtg-foreign-signed-finder.py "Lightning Bolt" --signed                # signed cards in any language
python3 mtg-foreign-signed-finder.py "Lightning Bolt" -l en,jp --signed --foil  # signed English or Japanese foils
```

## Features

### Card name matching
- Use the card's **English name**. Matching is exact and case-insensitive.
- Variant info in brackets is ignored, so `Lightning Bolt (Borderless)` counts as `Lightning Bolt`.
- Double-faced cards: use the front face name (both sites list them that way), e.g. `Delver of Secrets`.
- Split cards match either half, e.g. `Fire` finds `Fire // Ice`.
- `--fuzzy` loosens matching to "name contains the query".

### Site selection
- `--site all` (default) searches both sites.
- `--site tcg` or `--site tcgplayer` searches TCGplayer only.
- `--site ck` or `--site cardkingdom` searches Card Kingdom only.

### Language filter
- `--lang` / `-l` limits results to one or more languages. Without it, every language **except English** is included, or **every language** when `--signed` is used. Add `en` to include English, e.g. `-l en,jp`.
- Multiple languages mean "any of these": `-l fr,de,jp` shows French, German **or** Japanese.
- Separate with commas, or with spaces inside quotes: `-l "fr de jp"`.
- Codes, aliases and full English names can be mixed, case-insensitive: `-l french,ger,ja`.
- An unknown language prints an error listing the valid codes.

| Code | Language | Also accepted | Chinese names (`mtg-foreign-signed-finder-zh.py` only) |
| --- | --- | --- | --- |
| EN | English | eng, english | 英, 英语, 英文 |
| JP | Japanese | ja, jpn | 日, 日语, 日文 |
| CS | Chinese (Simplified) | zhs, chs, sc, simplified | 简, 简体, 简中, 简体中文 |
| CT | Chinese (Traditional) | zht, cht, tc, traditional | 繁, 繁体, 繁中, 繁体中文 |
| KR | Korean | ko, kor | 韩, 韩语, 韩文 |
| DE | German | ger, deu | 德, 德语, 德文 |
| FR | French | fra, fre | 法, 法语, 法文 |
| IT | Italian | ita | 意, 意语, 意大利语 |
| SP | Spanish | es, spa | 西, 西语, 西班牙语 |
| PT | Portuguese | por | 葡, 葡语, 葡萄牙语 |
| RU | Russian | rus | 俄, 俄语, 俄文 |
| PH | Phyrexian | phy | 非瑞克西亚, 非瑞克西亚语 |

`zh`, `cn` or `chinese` (and `中`, `中文` in the Chinese script) mean both Simplified and Traditional. Codes follow TCGplayer's own abbreviations, so Spanish is `SP`, but `es` works too.

### Foil filter
- `--foil` shows foils only, `--nonfoil` shows non-foils only. Default: both. They can't be used together.
- Combines with the language filter: `-l fr,de,jp --foil`.

### Signed filter
- `--signed` shows signed cards only, in **any language** (English included). `--unsigned` leaves signed cards out. Default: both. They can't be used together.
- Add `-l` to narrow down by language, e.g. `-l jp,de --signed` for signed Japanese or German only. Other filters combine too: `--signed --foil`.
- **TCGplayer only.** Signed cards are photo listings, and whether a card is signed comes from the seller's own title and description. It counts wording like `Signed`, `Artist signed`, `Signed by ...`, `Autographed`, `with a signature` and `Artist Proof`, and ignores look-alikes like *Signature Spellbook*, `Signature Foil`, `not signed` and shipping wording such as `signature confirmation`. A seller who doesn't mention the signature won't be caught.
- With `--signed`, each signed listing is shown on its own: language, finish, price, condition, seller and the seller's title. If the signature is only mentioned in the description, the part that mentions it is shown.
- **Card Kingdom doesn't sell signed cards**, so with `--signed` it says so and is skipped.

### Output
- Before each site it says what it is looking for, e.g. `Searching TCGplayer for French foil Simic Signet...` or `Searching TCGplayer for signed Lightning Bolt in any language...` (Chinese script: `正在 TCGplayer 上找法语闪的 Simic Signet...`).
- **TCGplayer**: for each printing with matching listings, shows the set, product link, and per language and finish the number of listings, total quantity and lowest price.
- **Card Kingdom**: for each matching printing, shows the set, variant, product link, language, finish, retail price and stock.
- Each site ends with a one-line summary.
- In a terminal, TCGplayer shows a progress line like `[3/15] Commander 2013` that updates in place. It is printed to stderr and hidden when output isn't a terminal, so redirecting to a file stays clean.

### Other options

| Option | Default | What it does |
| --- | --- | --- |
| `--max-products N` | 80 | Max number of TCGplayer printings to check |
| `--delay SECONDS` | 0.7 | Pause between TCGplayer requests |
| `--ck-cache-hours H` | 12 | How long to reuse the cached Card Kingdom price list |
| `--debug` | off | Print raw API fields, an unfiltered language breakdown, and every Card Kingdom match |
| `-h` | | Show help, including the language code list |

### Reliability
- Requests that hit rate limits or server errors (429, 5xx) are retried up to 3 times with increasing waits.
- A failed printing is reported and skipped; the rest of the search continues.
- An error on one site doesn't stop the other site from being searched.

## How it works and limitations

- **TCGplayer** is queried through the internal API its website uses. The script searches for the card, keeps exact name matches, then asks for listings of each printing filtered by language. Printings with many versions (Sol Ring has 100+) take a few minutes; use `--max-products` to limit. If TCGplayer changes its API the script will break; run with `--debug` to see what changed.
- **Card Kingdom** sells almost only English cards, and its price list has no language field. The script detects foreign printings from the variant and set name, so it only finds printings Card Kingdom lists as their own version, such as WAR Japanese alternate art planeswalkers, Phyrexian language cards and SNC multilingual box toppers. "No matching printings" is usually the real answer, not a bug. With `-l en`, every printing without a language word counts as English.
- The first Card Kingdom search downloads the full price list (large) and caches it in `~/.cache/mtg-foreign-signed-finder/`.

---

## 中文

查一张万智牌在 **TCGplayer** 和 **Card Kingdom** 上，哪些版本有外语（非英文）在卖，可以按语言、闪/平和签名过滤。

两个脚本功能完全一样：

| 脚本 | 输出语言 |
| --- | --- |
| `mtg-foreign-signed-finder.py` | 英文 |
| `mtg-foreign-signed-finder-zh.py` | 中文（`-l` 也能直接写 `法语` 这样的中文名） |

### 安装

需要 Python 3.8+ 和 `requests`：

```bash
pip install requests
git clone https://github.com/NeoNought47/mtg-foreign-signed-finder.git
cd mtg-foreign-signed-finder
```

### 快速上手

```bash
python3 mtg-foreign-signed-finder-zh.py "Lightning Bolt"                     # 两家网站所有外语版本
python3 mtg-foreign-signed-finder-zh.py "Simic Signet" -l 法语 --foil        # 只看法语闪
python3 mtg-foreign-signed-finder-zh.py "Sol Ring" -l fr,de,jp               # 法语、德语、日语之一
python3 mtg-foreign-signed-finder-zh.py "Sol Ring" --site tcg --max-products 5
python3 mtg-foreign-signed-finder-zh.py "Gala Greeters" --site cardkingdom -l 中文 --nonfoil
python3 mtg-foreign-signed-finder-zh.py "Lightning Bolt" --signed               # 任何语言的签名卡
python3 mtg-foreign-signed-finder-zh.py "Lightning Bolt" -l 英语,日语 --signed --foil  # 英语或日语的签名闪
```

### 功能

#### 牌名匹配
- 用牌的**英文名**，精确匹配，不分大小写。
- 忽略括号里的版本说明，`Lightning Bolt (Borderless)` 也算 `Lightning Bolt`。
- 双面牌用正面的名字（两家网站都是这样列的），例如 `Delver of Secrets`。
- 分体牌输入任意一半都能匹配，例如 `Fire` 能找到 `Fire // Ice`。
- `--fuzzy` 放宽为"名称包含输入内容即可"。

#### 选择网站
- `--site all`（默认）两家都查。
- `--site tcg` 或 `--site tcgplayer` 只查 TCGplayer。
- `--site ck` 或 `--site cardkingdom` 只查 Card Kingdom。

#### 语言过滤
- `--lang` / `-l` 只看指定的一种或多种语言。不加时包含**除英语外**的所有语言；用 `--signed` 时则包含**所有语言**。要包含英语就加上 `en`，例如 `-l en,jp`。
- 多种语言表示"其中之一"：`-l fr,de,jp` 会列出法语、德语**或**日语。
- 用逗号分隔，或者加引号用空格分隔：`-l "fr de jp"`。中文版还支持中文逗号和顿号：`-l 法语、德语，日语`。
- 代码、别名、英文全名可以混着写，不分大小写：`-l french,ger,ja`。
- 输错语言会报错，并列出所有可用代码。
- 完整的代码和别名见上方英文部分的 [语言代码表](#language-filter)。中文版额外接受表格最后一列的中文名。
- `zh`、`cn`、`chinese`（中文版还有 `中`、`中文`）表示简繁中文都要。代码用的是 TCGplayer 自己的缩写，所以西班牙语是 `SP`，不过写 `es` 也能识别。

#### 闪/平过滤
- `--foil` 只看闪卡，`--nonfoil` 只看平卡，默认都看。两个不能同时用。
- 可以和语言过滤一起用：`-l fr,de,jp --foil`。

#### 签名过滤
- `--signed` 只看签名卡，**不限语言**（包括英文）。`--unsigned` 排除签名卡。默认都看，两个不能同时用。
- 想限定语言就加 `-l`，例如 `-l jp,de --signed` 只看日文或德文的签名卡。也能和其他过滤一起用：`--signed --foil`。
- **只支持 TCGplayer。** 签名卡都是卖家拍照上传的挂单，是否签名是根据卖家自己写的标题和描述判断的。会识别 `Signed`、`Artist signed`、`Signed by ...`、`Autographed`、`with a signature`、`Artist Proof` 这类写法，并排除 *Signature Spellbook* 系列、`Signature Foil` 版本、`not signed`，以及 `signature confirmation`（寄件签收）这类看起来像但不是签名的词。卖家没写签名的就识别不了。
- 用 `--signed` 时每张签名卡单独列一行：语言、闪/平、价格、品相、卖家和卖家写的标题。签名只写在描述里的，会显示描述中提到签名的那一段。
- **Card Kingdom 不卖签名卡**，用 `--signed` 时会提示并跳过。

#### 输出
- 每查一家网站前先说明在找什么，例如 `正在 TCGplayer 上找法语闪的 Simic Signet...`、`正在 TCGplayer 上找任意语言签名的 Lightning Bolt...`。
- **TCGplayer**：每个有符合条件挂单的版本，列出系列、商品链接，以及每种语言和闪/平的挂单数、总张数、最低价。
- **Card Kingdom**：每个符合条件的版本，列出系列、版本描述、商品链接、语言、闪/平、售价和库存。
- 每家网站最后有一行小结。
- 在终端里运行时，TCGplayer 会显示一行原地刷新的进度，例如 `[3/15] Commander 2013`。这行输出到 stderr，输出重定向到文件时不显示，不会弄乱结果。

#### 其他参数

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `--max-products N` | 80 | TCGplayer 最多查几个版本 |
| `--delay 秒数` | 0.7 | TCGplayer 每次请求的间隔 |
| `--ck-cache-hours 小时` | 12 | Card Kingdom 价格表缓存多久 |
| `--debug` | 关 | 打印接口原始字段、不过滤时的语言分布，以及 Card Kingdom 的每条匹配 |
| `-h` | | 显示帮助，包括语言代码列表 |

#### 稳定性
- 遇到限流或服务器错误（429、5xx）会自动重试，最多 3 次，等待时间逐次加长。
- 某个版本请求失败会提示并跳过，其他版本继续查。
- 一家网站出错不影响另一家。

### 原理和限制

- **TCGplayer** 用的是网页前端的内部接口。脚本先搜索牌名、保留名字完全匹配的版本，再按语言逐个查挂单。版本多的牌（比如 Sol Ring 有 100 多个版本）要跑几分钟，可以用 `--max-products` 限制。TCGplayer 改接口时脚本会失效，用 `--debug` 看哪里变了。
- **Card Kingdom** 基本只卖英文卡，价格表里也没有语言字段。脚本根据版本描述和系列名判断语言，所以只能查到它单独列成一个版本的外语印刷，比如 WAR 日文异画鹏洛客、Phyrexian 语版本、SNC 多语言盒顶卡。显示"没有符合条件的版本"通常就是真实情况，不是脚本坏了。用 `-l en` 时，版本描述里没有语言词的都算英语。
- 第一次查 Card Kingdom 会下载全量价格表（文件较大），缓存在 `~/.cache/mtg-foreign-signed-finder/`。
