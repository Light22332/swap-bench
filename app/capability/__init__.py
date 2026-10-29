"""能力层：每个模块都能脱离流水线单独调用。

  generate  把一次请求变成一张图（ComfyUI / 云端）
  judge     判定一张图行不行（人脸、手部、结构）
  prep      把那件衣服从参考图里整理出来（人像解析 + 裁剪决策）

依赖方向只有一条：api → pipeline → capability → core。能力之间可以横向借用
（裁剪要知道图里有没有脸，就调 judge/faces），但都不许往上依赖 pipeline 或 api。
"""
