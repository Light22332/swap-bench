"""读图与上传归一化的测试：不联网、不需要 GPU、不需要 ComfyUI。

覆盖：EXIF 方向转正、EXIF/元数据去掉、透明底铺白、超长边缩小、HEIC 的
人话报错、坏文件报错，以及 /api/upload 路由确实把归一化后的图落盘。

跑法：python tools/tests/test_photos.py
"""
import base64
import io
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

from PIL import Image, ImageDraw                            # noqa: E402
from app.core import photos                                # noqa: E402
from app.api.routes import upload as upload_route          # noqa: E402

FAILED = []
TMP = os.path.join(ROOT, "outputs", "_test_photos")
os.makedirs(TMP, exist_ok=True)


def check(name, cond, detail=""):
    print(("  PASS  " if cond else "  FAIL  ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


def reopen(blob):
    im = Image.open(io.BytesIO(blob))
    im.load()
    return im


def jpeg_with_orientation(orientation, size=(120, 80)):
    """左上角一块红：转正之后它应该挪到别处，用来验证真的转了。"""
    im = Image.new("RGB", size, (240, 240, 240))
    ImageDraw.Draw(im).rectangle([0, 0, 29, 19], fill=(220, 20, 20))
    ex = Image.Exif()
    ex[274] = orientation          # 274 = Orientation
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=95, exif=ex.tobytes())
    return buf.getvalue()


def png_rgba_with_transparent_bg():
    im = Image.new("RGBA", (60, 40), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle([10, 10, 49, 39], fill=(0, 128, 0, 255))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


class Req:
    """只实现 _upload 用到的那两个方法。"""
    def __init__(self, payload):
        self.payload = payload
        self.out = None
        self.code = None

    def body(self):
        return self.payload

    def json(self, obj, code=200):
        self.out, self.code = obj, code


print("方向：EXIF 转正")
blob6 = jpeg_with_orientation(6)
out, meta = photos.prepare_upload(blob6, "IMG_0001.jpg")
im = reopen(out)
check("方向 6：宽高互换（120×80 → 80×120）", im.size == (80, 120), str(im.size))
check("方向 6：摘要里写了转正", meta["rotated"] and "转正" in meta["note"], str(meta))
r, g, b = im.getpixel((70, 10))[:3]
check("方向 6：右上角是原来的红块", r > 150 and g < 90 and b < 90, str((r, g, b)))

out1, meta1 = photos.prepare_upload(jpeg_with_orientation(1), "flat.jpg")
check("方向 1：尺寸不变、不提示转正",
      reopen(out1).size == (120, 80) and not meta1["rotated"] and meta1["note"] == "",
      str(meta1))

outsq, metasq = photos.prepare_upload(jpeg_with_orientation(6, size=(100, 100)), "square.jpg")
check("正方形照片转 90° 也要说转正（宽高看不出来）",
      metasq["rotated"] and "转正" in metasq["note"], str(metasq))

print("元数据：方向标记和 EXIF 不跟着走")
ex = reopen(out).getexif()
check("导出后没有方向标记", 274 not in ex, str(list(ex.keys())))

print("透明底：铺白，不铺黑")
outa, _ = photos.prepare_upload(png_rgba_with_transparent_bg(), "cutout.png")
ima = reopen(outa)
check("透明 PNG 变成 RGB", ima.mode == "RGB", ima.mode)
check("透明区域是白的", min(ima.getpixel((2, 2))[:3]) >= 240, str(ima.getpixel((2, 2))))
check("不透明区域还是绿的", ima.getpixel((30, 25))[1] > 100, str(ima.getpixel((30, 25))))

print("尺寸：超长边缩到 4096")
big = Image.new("RGB", (5000, 100), (200, 200, 200))
buf = io.BytesIO()
big.save(buf, "PNG")
outb, metab = photos.prepare_upload(buf.getvalue(), "panorama.png")
check("超长边缩到 4096", max(reopen(outb).size) == photos.MAX_SIDE and metab["resized"],
      str(reopen(outb).size))

print("坏文件：报人话")
heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64
check("认得出 HEIC 的 ftyp", photos.is_heif(heic))
try:
    photos.prepare_upload(heic, "IMG_0002.HEIC")
    check("HEIC 会报错", False)
except photos.PhotoError as e:
    msg = str(e)
    check("HEIC 报错说清楚怎么办", "HEIC" in msg and "JPG" in msg, msg)

try:
    photos.prepare_upload(b"this is not an image", "x.jpg")
    check("坏文件会报错", False)
except photos.PhotoError as e:
    check("坏文件报错说人话", "打不开" in str(e), str(e))

print("HEIC：装了 pillow-heif 就真的转成 JPG")
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    heic_ready = True
except Exception:  # noqa: BLE001
    heic_ready = False

real_heic = b""
if heic_ready:
    src_im = Image.new("RGB", (120, 80), (240, 240, 240))
    ImageDraw.Draw(src_im).rectangle([0, 0, 29, 19], fill=(220, 20, 20))
    ex6 = Image.Exif()
    ex6[274] = 6
    hbuf = io.BytesIO()
    src_im.save(hbuf, "HEIF", quality=90, exif=ex6.tobytes())
    real_heic = hbuf.getvalue()
    check("真 HEIC 被认出来", photos.is_heif(real_heic), str(real_heic[8:12]))
    hout, hmeta = photos.prepare_upload(real_heic, "IMG_0004.HEIC")
    check("真 HEIC 转成 JPG，note 里说清楚",
          hmeta["format"] == "HEIF" and "转成 JPG" in hmeta["note"], str(hmeta))
    check("真 HEIC 转出来是竖的", reopen(hout).size == (80, 120), str(reopen(hout).size))
else:
    print("  SKIP  没装 pillow-heif，跳过真 HEIC 转换（提示文案上面已经测过）")

print("普通照片：原样尺寸，不弹提示")
src = os.path.join(ROOT, "samples", "demo_person_a.jpg")
with open(src, "rb") as f:
    sample = f.read()
outc, metac = photos.prepare_upload(sample, "demo_person_a.jpg")
check("普通照片尺寸不变", reopen(outc).size == reopen(sample).size,
      f"{reopen(outc).size} vs {reopen(sample).size}")
check("普通照片没有多余提示", metac["note"] == "", metac["note"])
check("open_upright 和 PIL 读样本尺寸一致",
      photos.open_upright(src).size == reopen(sample).size)

print("接口：/api/upload 落盘的是转正后的 JPEG")
saved = []
try:
    payload = "data:image/jpeg;base64," + base64.b64encode(blob6).decode()
    req = Req({"name": "phone.jpg", "data": payload})
    upload_route._upload(req)
    ok = req.code == 200 and req.out and req.out.get("ok")
    check("接口：返回 ok", bool(ok), str(req.out))
    path = req.out.get("path") if ok else None
    check("接口：路径是 uploads/ 下的 .jpg", bool(path) and path.endswith(".jpg"), str(path))
    full = os.path.join(ROOT, path) if path else ""
    if os.path.isfile(full):
        saved.append(full)
        with open(full, "rb") as f:
            disk = reopen(f.read())
        check("接口：落盘图是竖的", disk.size == (80, 120), str(disk.size))
        check("接口：note 写明转正", "转正" in req.out.get("note", ""), req.out.get("note"))
    else:
        check("接口：文件落到了磁盘上", False, str(full))

    heic_payload = "data:image/heic;base64," + base64.b64encode(heic).decode()
    req2 = Req({"name": "IMG_0003.HEIC", "data": heic_payload})
    upload_route._upload(req2)
    check("接口：HEIC 返回 415 和提示",
          req2.code == 415 and "HEIC" in (req2.out or {}).get("error", ""),
          str(req2.code) + " " + str(req2.out))

    if real_heic:
        req3 = Req({"name": "IMG_0006.HEIC",
                    "data": "data:image/heic;base64," + base64.b64encode(real_heic).decode()})
        upload_route._upload(req3)
        check("接口：真 HEIC 上传成功，说明转成了 JPG",
              req3.code == 200 and "转成 JPG" in (req3.out or {}).get("note", ""),
              str(req3.code) + " " + str(req3.out))
        if req3.code == 200 and req3.out.get("path"):
            saved.append(os.path.join(ROOT, req3.out["path"]))
finally:
    for p in saved:
        try:
            os.remove(p)
        except OSError:
            pass
    shutil.rmtree(TMP, ignore_errors=True)

print()
if FAILED:
    print("没过：" + "、".join(FAILED))
    sys.exit(1)
print("全部通过")
