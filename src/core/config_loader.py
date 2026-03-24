"""配置文件加载器：支持特殊占位符处理"""
from __future__ import annotations
import os
import re
import yaml
from typing import Dict, Any, List, Optional
from pathlib import Path


def load_yaml_file(file_path: str) -> Dict[str, Any]:
    """加载 YAML 文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_txt_file(file_path: str) -> str:
    """加载文本文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()

def resolve_placeholders(obj, base_dir: str = None):
    """
    递归解析特殊占位符
    
    支持的占位符：
    - $env:{VARNAME} - 替换为环境变量值
    - $source:{path/to/file.yaml} - 替换为 YAML 文件内容
    - $source_txt:{path/to/file.txt} - 替换为文本文件内容
    
    Args:
        obj: 要处理的对象（str/dict/list）
        base_dir: 基础目录（用于解析相对路径）
    """
    def resolve_env(value: str):
        pattern = r"(\$env:\{(.+?)\})"
        ret = value
        for full, varname in re.findall(pattern, ret):
            ret = ret.replace(full, str(os.environ.get(varname, "")))
        return ret
    
    def resolve_source(value: str):
        pattern = r"\$source:\{(.+?)\}"
        matched = re.fullmatch(pattern, value)
        if matched:
            rel_path = matched.group(1)
            abs_path = os.path.join(base_dir or "", rel_path)
            return resolve_placeholders(load_yaml_file(abs_path), os.path.dirname(abs_path))
        return value
    
    def resolve_source_txt(value: str):
        pattern = r"\$source_txt:\{(.+?)\}"
        matched = re.fullmatch(pattern, value)
        if matched:
            rel_path = matched.group(1)
            abs_path = os.path.join(base_dir or "", rel_path)
            return load_txt_file(abs_path)
        return value
    
    if isinstance(obj, str):
        ret = resolve_env(obj)
        ret = resolve_source_txt(ret)
        ret = resolve_source(ret)
        return ret
    elif isinstance(obj, dict):
        return {k: resolve_placeholders(v, base_dir) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [resolve_placeholders(i, base_dir) for i in obj]
    else:
        return obj


def load_config(fn: str) -> Dict[str, Any]:
    """
    加载配置文件并处理特殊占位符
    
    Args:
        fn: 配置文件路径
    
    Returns:
        处理后的配置字典
    """
    base_dir = os.path.dirname(os.path.abspath(fn))
    return resolve_placeholders(load_yaml_file(fn), base_dir)