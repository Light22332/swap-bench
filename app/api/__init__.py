"""HTTP 层：只管请求解析和响应，不写业务。

  server  骨架：起服务、分发、写字节
  http    Request 包装
  state   配置快照与在跑的任务表
  history 从 JSONL 还原历史任务与汇总指标
  view    文件路径 → 前端 URL
  routes/ 每个资源一个模块（config / jobs / run / upload / static）
"""
from .server import Handler, serve

__all__ = ["Handler", "serve"]
