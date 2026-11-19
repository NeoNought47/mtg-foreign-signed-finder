# polyglot

查一张万智牌在 TCGplayer 和 Card Kingdom 上，哪些版本有外语（非英文）在卖。

## 用法

```bash
pip install requests
python3 polyglot.py "Lightning Bolt"
python3 polyglot.py "Sol Ring" --site tcg --max-products 5
python3 polyglot.py "Karn, the Great Creator" --site ck
python3 polyglot.py "Lightning Bolt" -l jp,cs --foil
python3 polyglot.py "Gala Greeters" --site cardkingdom -l zh --nonfoil
```

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
| JP | Japanese | ja, jpn |
| CS | Chinese (S) 简体 | zhs, chs, sc |
| CT | Chinese (T) 繁体 | zht, cht, tc |
| KR | Korean | ko, kor |
| DE | German | ger, deu |
| FR | French | fra, fre |
| IT | Italian | ita |
| SP | Spanish | es, spa |
| PT | Portuguese | por |
| RU | Russian | rus |
| PH | Phyrexian | phy |

`zh` 或 `cn` 表示简繁中文都要。英文全名也可以用，大小写不限。

## 说明

- TCGplayer 按挂单的语言字段筛选，会列出每个版本的语言、平卡/闪卡、挂单数和最低价。
- Card Kingdom 基本只卖英文卡，只能查出它单独列为版本的外语印刷（如 WAR 日文异画、Phyrexian 语版本）。
- Card Kingdom 价格表第一次运行会下载并缓存 12 小时，位置在 `~/.cache/polyglot/`。
- TCGplayer 用的是网页前端的内部接口，接口变动时用 `--debug` 排查。
