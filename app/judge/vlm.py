"""云端视觉模型质检：让它按固定清单逐项判定，只回 JSON。

要点：
- 清单写死在提示词里，不让模型自由发挥，否则结果没法跨批次比较
- 要求 reason 只写一句，便于在页面和报告里并排展示
- 解析失败不抛异常，返回带 error 的降级结果，让整条流水线继续
"""
import base64
import json
import time
import urllib.error
import urllib.request

from ..core.checks import CHECKS, summarize


def _data_uri(path):
    with open(path, "rb") as f:
        raw = f.read()
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode()


def _build_prompt():
    lines = []
    for c in CHECKS:
        lines.append(f'- "{c["key"]}"（{c["label"]}）')
    return (
        "你在做服装换装结果的验收。给你三张图：图1是原始人物照，图2是目标服装参考，"
        "图3是生成结果。请只依据图像本身判断，逐项给出通过与否，不要客套。\n"
        "判定项：\n" + "\n".join(lines) + "\n\n"
        "要求：\n"
        "1. 每项 pass 只能是 true 或 false，不允许 null。\n"
        "2. reason 写一句中文，20 字以内，指出具体依据。\n"
        "3. 只输出一个 JSON 对象，格式："
        '{"checks":{"<key>":{"pass":true,"reason":"..."}, ...}}\n'
        "4. 不要输出 JSON 之外的任何文字。"
    )


def evaluate(person_path, result_path, garment_path=None, cfg=None, **_):
    t0 = time.time()
    jc = (cfg or {}).get("judge", {})
    base_url = (jc.get("base_url") or "").rstrip("/")
    api_key = jc.get("api_key") or ""
    model = jc.get("model") or ""
    timeout = jc.get("timeout", 60)

    if not (base_url and api_key and model):
        return None  # 交给上层降级

    content = [{"type": "text", "text": _build_prompt()}]
    for label, path in (("图1 原始人物", person_path),
                        ("图2 目标服装", garment_path),
                        ("图3 生成结果", result_path)):
        if not path:
            continue
        content.append({"type": "text", "text": label})
        content.append({"type": "image_url", "image_url": {"url": _data_uri(path)}})

    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": 800,
    }).encode()

    req = urllib.request.Request(
        base_url + "/chat/completions", data=body,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"})

    try:
        resp = json.load(urllib.request.urlopen(req, timeout=timeout))
        text = resp["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")[:300]
        v = summarize({c["key"]: {"pass": None, "reason": ""} for c in CHECKS},
                      "vlm", note=f"视觉模型 HTTP {e.code}", latency_s=time.time() - t0)
        v["error"] = raw
        return v
    except Exception as e:
        v = summarize({c["key"]: {"pass": None, "reason": ""} for c in CHECKS},
                      "vlm", note="视觉模型调用失败", latency_s=time.time() - t0)
        v["error"] = str(e)
        return v

    parsed = _extract_json(text)
    if not parsed:
        v = summarize({c["key"]: {"pass": None, "reason": ""} for c in CHECKS},
                      "vlm", note="无法解析模型输出", latency_s=time.time() - t0)
        v["error"] = text[:300]
        return v

    checks = {}
    for c in CHECKS:
        r = parsed.get("checks", {}).get(c["key"], {})
        p = r.get("pass")
        checks[c["key"]] = {
            "pass": p if isinstance(p, bool) else None,
            "reason": str(r.get("reason", ""))[:60],
        }
    return summarize(checks, "vlm", note="", latency_s=time.time() - t0)


def _extract_json(text):
    """模型常带 ```json 包裹或前后废话，这里只捞第一个完整对象。"""
    if not text:
        return None
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None
