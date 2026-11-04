# bench/

`tools/regression.py --set bench` 用的十组固定输入：两个人像 × 五件衣服。

**不进版本库**。这些图是网上找的商品照，带水印，公开仓库里不适合带。README 和 ROADMAP 里
十四组/二十二组的本地数字，就是在它们（加上 `samples/` 的四组）身上量出来的。

要用就按原名放进来：

```
case1_person.jpg    case4_person.png
case1_garment.jpg   case2_garment.jpg   case3_garment.jpg
case4_garment.jpg   case4_garment_crop.jpg
```

没有这些图也能跑公开那套（仓库自带 12 组）：

```bash
python tools/regression.py run --set samples --out reports/samples.json
```

换成自己的输入也可以，改 `tools/regression.py` 顶部的 `BENCH_PAIRS`，然后：

```bash
python tools/regression.py run --set bench --out reports/hand-base.json
```

换图之后 README 里的数字就对不上了，得重跑一遍并改文档。
