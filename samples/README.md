# samples/

八张示例图，随仓库分发，随便用。全是用本机的 Qwen-Image 2.1 生成的，不涉及任何商品照或网图的版权。

| 文件 | 内容 |
|---|---|
| `demo_person_a.jpg` | 人像：女性，上半身正面，双手在画面里 |
| `demo_person_b.jpg` | 人像：男性，正面站姿，双手在画面里 |
| `demo_garment_1.jpg` | 橘色短款羽绒服，白底平铺 |
| `demo_garment_2.jpg` | 米白长款风衣，假人模特 |
| `demo_garment_3.jpg` | 黑色高领针织衫，白底平铺 |
| `demo_garment_4.jpg` | 两件冲锋衣拼在一张图上（用来看参考图裁剪怎么决策） |
| `demo_garment_5.jpg` | 白色棉服贴边特写（衣服铺满整幅，裁剪逻辑会放行不裁） |
| `demo_garment_6.jpg` | 蓝色牛仔外套，浅灰底平铺 |

页面上「载入示例看看」用的是 `demo_person_a` + `demo_garment_1` + `demo_garment_2`。

实测这一组跑得通：人脸相似度 0.85、身体区域变化 79%、两只手都在（复核 0.92 / 0.99）、背景主色距离 9，五项全过，一次出图 56 秒。

回归基线用的那 8 组图不在这里，也不随仓库分发，见 `../bench/README.md`。

`_raw/` 是生成时的原图（PNG），已被 gitignore；转成 JPEG 是为了让仓库小一点。
