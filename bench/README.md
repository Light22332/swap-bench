# bench/

`tools/regression.py` 用的八组固定输入：两个人像 × 四件衣服。

**不进版本库**。这些图是网上找的商品照，带水印，公开仓库里不适合带。README 和 ROADMAP 里那些回归数字（合格率 75%、平均重试 1.62 次之类）都是在它们身上量出来的。

要用就按原名放进来：

```
case1_person.jpg    case4_person.png
case1_garment.jpg   case3_garment.jpg
case4_garment.jpg   case4_garment_crop.jpg
```

换成自己的八组也可以，改 `tools/regression.py` 顶部的 `PAIRS`，然后：

```bash
python tools/regression.py run --out reports/base.json
```

换图之后 README 里的数字就对不上了，得重跑一遍并改文档。
