"""验证扩展加载器：示例能通过校验、坏文件能给出人能看懂的错。"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from providers.extension import SPEC_VERSION, load_extensions, validate

EXAMPLES = ROOT / "extensions" / "examples"


def test_示例全部通过校验():
    exts, errors = load_extensions(EXAMPLES)
    assert not errors, f"示例有问题: {errors}"
    assert len(exts) >= 2, f"示例太少: {len(exts)}"
    ids = {e.id for e in exts}
    assert "asus-rog-pelta" in ids
    assert "razer-viper-v3-pro" in ids


def test_匹配规则按vid和pid():
    exts, _ = load_extensions(EXAMPLES)
    asus = next(e for e in exts if e.id == "asus-rog-pelta")
    assert asus.matches({"vendor_id": 0x0B05, "product_id": 0x1B84,
                         "usage_page": 0xFF00})
    assert not asus.matches({"vendor_id": 0x0B05, "product_id": 0x1234,
                            "usage_page": 0xFF00})
    assert not asus.matches({"vendor_id": 0x046D, "product_id": 0x1B84,
                            "usage_page": 0xFF00})


def test_usage_page不匹配就跳过():
    exts, _ = load_extensions(EXAMPLES)
    razer = next(e for e in exts if e.id == "razer-viper-v3-pro")
    assert razer.matches({"vendor_id": 0x1532, "product_id": 0x00C1,
                          "usage_page": 0x0001, "usage": 0x0002})
    assert not razer.matches({"vendor_id": 0x1532, "product_id": 0x00C1,
                              "usage_page": 0x000C})


def test_缺字段报错带文件名():
    bad = {"spec": SPEC_VERSION, "name": "缺 id"}
    errors = validate(bad)
    assert any("id" in e for e in errors)


def test_json语法错不炸整个加载():
    with tempfile.TemporaryDirectory() as tmp:
        good = Path(tmp) / "ok.json"
        good.write_text(json.dumps({
            "spec": 1, "id": "ok", "name": "ok",
            "match": {"vid": "0x046D", "pid": ["0x1234"]},
            "read": {"battery": {"report_id": "0x51",
                                 "value": {"offset": 6}}},
        }), encoding="utf-8")
        broken = Path(tmp) / "broken.json"
        broken.write_text("{ not json", encoding="utf-8")
        exts, errors = load_extensions(tmp)
        assert len(exts) == 1
        assert any("broken.json" in e for e in errors)


def test_重复id会被拒绝():
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("a.json", "b.json"):
            (Path(tmp) / name).write_text(json.dumps({
                "spec": 1, "id": "dup", "name": "dup",
                "match": {"vid": "0x046D", "pid": ["0x1"]},
                "read": {"battery": {"report_id": "0x51",
                                     "value": {"offset": 6}}},
            }), encoding="utf-8")
        exts, errors = load_extensions(tmp)
        assert len(exts) == 1
        assert any("重复" in e for e in errors)


def main():
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL {name}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} 通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
