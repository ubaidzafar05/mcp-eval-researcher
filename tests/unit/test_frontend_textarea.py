from pathlib import Path


def test_textarea_is_fixed_height_scrollable():
    path = Path("web-ui/components/ui/textarea.tsx")
    content = path.read_text(encoding="utf-8")
    assert "field-sizing-content" not in content
    assert "resize-none" in content
    assert "overflow-y-auto" in content
