from typing import Any, Dict, Type
from .base import get_interface_class, Interface

def load_interface(interface_cfg: Dict[str, Any]):
    interface_typename = interface_cfg["type"]
    interface_type = get_interface_class(interface_typename)
    interface = interface_type.from_cfg(interface_cfg)
    assert isinstance(interface, Interface), f"load interface fail type {interface_type}, result {interface}"
    return interface
def load_interfaces(config: Dict[str, Any]) -> Dict[str, Interface]:
    interface_cfgs: Dict[str, Dict] = config.get("interfaces", {})
    return {k: load_interface(v) for k, v in interface_cfgs.items()}

