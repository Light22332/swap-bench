from .base import BackendError, GenRequest, GenResult
from .cloud import CloudBackend
from .comfyui import ComfyUIBackend


def make_backend(name, cfg):
    name = (name or cfg.get("backend") or "comfyui").lower()
    if name == "cloud":
        return CloudBackend(cfg)
    return ComfyUIBackend(cfg)
