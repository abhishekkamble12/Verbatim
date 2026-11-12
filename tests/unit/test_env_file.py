from services.env import load_env_file


def test_env_file_fills_missing_vars_only(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('# comment\nCG_A = one\nCG_B="two"\nCG_KEEP=file\n\nnot a pair\n', encoding="utf-8")
    monkeypatch.delenv("CG_A", raising=False)
    monkeypatch.delenv("CG_B", raising=False)
    monkeypatch.setenv("CG_KEEP", "real")
    load_env_file(f)
    import os
    assert (os.environ["CG_A"], os.environ["CG_B"], os.environ["CG_KEEP"]) == ("one", "two", "real")
    monkeypatch.delenv("CG_A")
    monkeypatch.delenv("CG_B")


def test_missing_env_file_is_fine(tmp_path):
    load_env_file(tmp_path / "nope")
