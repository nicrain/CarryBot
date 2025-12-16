import os
import json
import argparse
import pytest
from unittest.mock import patch, MagicMock
import detect_stairs as ds

# --- Fixtures ---

@pytest.fixture
def empty_config_file(tmp_path):
    config_path = tmp_path / "test_config.json"
    return str(config_path)

@pytest.fixture
def populated_config_file(tmp_path):
    config_path = tmp_path / "test_config.json"
    with open(config_path, 'w') as f:
        json.dump({"roi_h_start": 0.99, "median_blur_ksize": 9}, f)
    return str(config_path)

# --- Tests for ParamsHandler ---

def test_defaults_loaded(empty_config_file):
    """测试在没有配置文件时，是否正确加载了默认参数。"""
    params = ds.ParamsHandler(default_params_path=empty_config_file)
    # 不调用 load_from_file，因为文件不存在，应该优雅处理
    params.load_from_file()
    
    # 检查默认值
    assert params.get("roi_h_start") == 0.2
    assert params.get("median_blur_ksize") == 5

def test_load_from_file(populated_config_file):
    """测试从 JSON 文件加载参数。"""
    params = ds.ParamsHandler(default_params_path=populated_config_file)
    params.load_from_file()
    
    assert params.get("roi_h_start") == 0.99
    assert params.get("median_blur_ksize") == 9
    # 未在文件中定义的参数应保持默认值
    assert params.get("roi_v_start") == 0.3

def test_env_var_priority(populated_config_file):
    """测试环境变量优先级高于配置文件和默认值。"""
    params = ds.ParamsHandler(default_params_path=populated_config_file)
    params.load_from_file()
    
    # 模拟环境变量
    with patch.dict(os.environ, {"CARRYBOT_ROI_H_START": "0.11", "CARRYBOT_MEDIAN_BLUR_KSIZE": "3"}):
        params._load_from_env()
        
        # 环境变量 (0.11) 应该覆盖 文件 (0.99)
        assert params.get("roi_h_start") == 0.11
        # 环境变量 (3) 应该覆盖 文件 (9)
        assert params.get("median_blur_ksize") == 3

def test_cli_args_priority(populated_config_file):
    """测试命令行参数优先级最高。"""
    params = ds.ParamsHandler(default_params_path=populated_config_file)
    params.load_from_file()
    
    # 模拟环境变量
    with patch.dict(os.environ, {"CARRYBOT_ROI_H_START": "0.11"}):
        params._load_from_env()
        
        # 模拟 CLI 参数
        args = argparse.Namespace(roi_h_start=0.55, roi_h_stop=None)
        params._load_from_cli_args(args)
        
        # CLI (0.55) 应该覆盖 环境变量 (0.11) 和 文件 (0.99)
        assert params.get("roi_h_start") == 0.55
        
        # CLI 为 None 的参数不应覆盖其他层级
        # roi_h_stop 为 None，所以应该用默认值 0.8 (或者文件/环境变量的值)
        assert params.get("roi_h_stop") == 0.8

def test_update_and_save(populated_config_file):
    """测试更新参数并保存到文件。"""
    params = ds.ParamsHandler(default_params_path=populated_config_file)
    params.load_from_file()
    
    new_values = {"roi_h_start": 0.77, "wall_dist_th": 1.5}
    params.update_and_save(new_values)
    
    # 内存中的值应该更新
    assert params.get("roi_h_start") == 0.77
    assert params.get("wall_dist_th") == 1.5
    
    # 文件应该被重写
    with open(populated_config_file, 'r') as f:
        saved_data = json.load(f)
    
    assert saved_data["roi_h_start"] == 0.77
    assert saved_data["wall_dist_th"] == 1.5
    # 其他参数应该还在
    assert saved_data["median_blur_ksize"] == 9