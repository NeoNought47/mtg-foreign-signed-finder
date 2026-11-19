# polyglot

查一张万智牌在 TCGplayer 和 Card Kingdom 上，哪些版本有外语（非英文）在卖。

## 用法

```bash
pip install requests
python3 polyglot.py "Lightning Bolt"
python3 polyglot.py "Sol Ring" --site tcg --max-products 5
python3 polyglot.py "Karn, the Great Creator" --site ck
```

常用参数：`--site all|tcg|ck`、`--fuzzy`、`--delay`、`--max-products`、`--debug`。

## 说明

- TCGplayer 按挂单的语言字段筛选，会列出每个版本的语言、平卡/闪卡、挂单数和最低价。
- Card Kingdom 基本只卖英文卡，只能查出它单独列为版本的外语印刷（如 WAR 日文异画、Phyrexian 语版本）。
- Card Kingdom 价格表第一次运行会下载并缓存 12 小时，位置在 `~/.cache/polyglot/`。
- TCGplayer 用的是网页前端的内部接口，接口变动时用 `--debug` 排查。
