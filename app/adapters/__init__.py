from ..core import config as app_config
from .base import BackendError, GenRequest, GenResult
from .cloud import CloudBackend
from .comfyui import ComfyUIBackend


def make_backend(name, cfg):
    name = (name or app_config.backend(cfg)).lower()
    if name == "cloud":
        return CloudBackend(cfg)
    return ComfyUIBackend(cfg)
