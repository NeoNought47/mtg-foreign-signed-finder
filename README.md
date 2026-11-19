# polyglot

**English** | [中文](#中文)

Look up a Magic: The Gathering card and find out which printings are sold in a non-English language on TCGplayer and Card Kingdom.

## Usage

```bash
pip install requests
python3 polyglot.py "Lightning Bolt"
python3 polyglot.py "Sol Ring" --site tcg --max-products 5
python3 polyglot.py "Karn, the Great Creator" --site ck
python3 polyglot.py "Lightning Bolt" -l jp,cs --foil
python3 polyglot.py "Gala Greeters" --site cardkingdom -l zh --nonfoil
```

| Option | What it does |
| --- | --- |
| `--site all\|tcg\|tcgplayer\|ck\|cardkingdom` | Search one site only (default: both) |
| `--lang` / `-l` | Only show these languages, comma separated, e.g. `-l jp,cs` |
| `--foil` / `--nonfoil` | Only foils / only non-foils |
| `--fuzzy` | Looser card name matching |
| `--max-products` | Max number of TCGplayer printings to check |
| `--delay` | Seconds between requests |
| `--debug` | Print raw API fields for troubleshooting |

### Language codes

| Code | Language | Also accepted |
| --- | --- | --- |
| JP | Japanese | ja, jpn |
| CS | Chinese (Simplified) | zhs, chs, sc |
| CT | Chinese (Traditional) | zht, cht, tc |
| KR | Korean | ko, kor |
| DE | German | ger, deu |
| FR | French | fra, fre |
| IT | Italian | ita |
| SP | Spanish | es, spa |
| PT | Portuguese | por |
| RU | Russian | rus |
| PH | Phyrexian | phy |

`zh` or `cn` means both Simplified and Traditional Chinese. Full English names also work. Case doesn't matter.

## Notes

- TCGplayer is filtered by each listing's language field. For every printing it shows the language, foil/non-foil, number of listings, total quantity and lowest price.
- Card Kingdom sells almost only English cards. It only finds foreign printings that Card Kingdom lists as their own variant (e.g. WAR Japanese alternate art planeswalkers, Phyrexian language cards).
- The first run downloads the full Card Kingdom price list and caches it for 12 hours in `~/.cache/polyglot/`.
- TCGplayer is queried through the internal API its website uses. If it breaks, run with `--debug` to see what changed.

---

## 中文

查一张万智牌在 TCGplayer 和 Card Kingdom 上，哪些版本有外语（非英文）在卖。

### 用法

用法示例见上方 [Usage](#usage)。

| 参数 | 作用 |
| --- | --- |
| `--site all\|tcg\|tcgplayer\|ck\|cardkingdom` | 只查某一家，默认两家都查 |
| `--lang` / `-l` | 只看某些语言，逗号分隔，例如 `-l jp,cs` |
| `--foil` / `--nonfoil` | 只看闪卡 / 只看平卡 |
| `--fuzzy` | 放宽名称匹配 |
| `--max-products` | TCGplayer 最多查几个版本 |
| `--delay` | 每次请求间隔秒数 |
| `--debug` | 打印接口原始字段，排查用 |

### 语言代码

| 代码 | 语言 | 也接受 |
| --- | --- | --- |
| JP | 日文 | ja, jpn |
| CS | 简体中文 | zhs, chs, sc |
| CT | 繁体中文 | zht, cht, tc |
| KR | 韩文 | ko, kor |
| DE | 德文 | ger, deu |
| FR | 法文 | fra, fre |
| IT | 意大利文 | ita |
| SP | 西班牙文 | es, spa |
| PT | 葡萄牙文 | por |
| RU | 俄文 | rus |
| PH | Phyrexian | phy |

`zh` 或 `cn` 表示简繁中文都要。英文全名也可以用，大小写不限。

### 说明

- TCGplayer 按挂单的语言字段筛选，会列出每个版本的语言、平卡/闪卡、挂单数、总张数和最低价。
- Card Kingdom 基本只卖英文卡，只能查出它单独列为版本的外语印刷（如 WAR 日文异画鹏洛客、Phyrexian 语版本）。
- Card Kingdom 价格表第一次运行会下载并缓存 12 小时，位置在 `~/.cache/polyglot/`。
- TCGplayer 用的是网页前端的内部接口，接口变动时用 `--debug` 排查。
