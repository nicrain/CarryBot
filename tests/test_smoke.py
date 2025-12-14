import importlib


def test_import_and_parse_args():
    mod = importlib.import_module('detect_stairs')
    assert hasattr(mod, 'parse_args')
    args = mod.parse_args([])
    assert args is not None
