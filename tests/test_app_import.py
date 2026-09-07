import importlib


def test_vercel_entrypoint_imports_without_runtime_import_errors():
    module = importlib.import_module("index")
    assert module.app.version == "1.8.0"
