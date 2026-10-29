"""闈欐€佽祫婧愶細椤甸潰銆佸墠绔枃浠躲€佸浘鐗囥€?
椤甸潰鍜屽墠绔唬鐮佷竴鐩村湪鏀癸紝鎵€浠ュ甫 no-cache锛涘浘鐗囧厑璁哥紦瀛樹袱鍒嗛挓銆?"""
import os
import re

from ...core import paths

NAME_OK = re.compile(r"[A-Za-z0-9_.\-]+")


def handle(req):
    p = req.path
    if p in ("/", "/index.html"):
        req.file(os.path.join(paths.WEB, "index.html"), cache="no-cache")
        return True
    if p.startswith("/static/"):
        name = p[len("/static/"):]
        if not NAME_OK.fullmatch(name):
            req.json({"error": "bad name"}, 400)
            return True
        req.file(os.path.join(paths.WEB, name), cache="no-cache")
        return True
    if p == "/img":
        req.file(paths.inside(req.param("path")))
        return True
    return False

