import re
from pathlib import Path

import pytest

from conftest import FIXTURE_KB
from kervan_search.config import ConfigError, Settings
from kervan_search.corpus import DEFAULT_KB_DIR, CorpusError, load_articles, parse_article, shorten


def test_defaults_are_the_compose_values():
    assert Settings.from_env({}) == Settings(port=8001, log_file=None, vector_provider="simulated")


def test_environment_is_read():
    env = {
        "PORT": "9100",
        "LOG_FILE": "/var/log/kervan/search.jsonl",
        "VECTOR_PROVIDER": "http",
        "VECTOR_PROVIDER_URL": "https://vectors.example.test",
        "VECTOR_PROVIDER_API_KEY": "k",
    }
    assert Settings.from_env(env) == Settings(
        9100, "/var/log/kervan/search.jsonl", "http", "https://vectors.example.test", "k"
    )


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"VECTOR_PROVIDER": "pinecone"}, "VECTOR_PROVIDER must be"),
        ({"VECTOR_PROVIDER": "http"}, "needs VECTOR_PROVIDER_URL"),
        ({"PORT": "http"}, "PORT"),
        ({"PORT": "70000"}, "PORT"),
        ({"PORT": "0"}, "PORT"),
    ],
)
def test_bad_environment_is_refused(env, message):
    with pytest.raises(ConfigError, match=message):
        Settings.from_env(env)


def test_knowledge_base():
    articles = load_articles(DEFAULT_KB_DIR)
    assert 10 <= len(articles) <= 15
    assert [a.id for a in articles] == sorted(a.id for a in articles)
    for path in DEFAULT_KB_DIR.glob("*.md"):
        assert parse_article(path.read_text(encoding="utf-8"), path.name).id == path.stem


def test_knowledge_base_has_no_personal_data():
    # Articles are `public` (SPEC §5.2): no e-mail addresses or phone numbers.
    for path in DEFAULT_KB_DIR.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"@|\+90|\b0?5\d{9}\b", text), path.name


def test_fixture_corpus():
    assert [a.id for a in load_articles(FIXTURE_KB)] == ["alpha", "beta", "gamma"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("no front matter", "missing front matter"),
        ("---\nid: a\ntitle: A\n", "unterminated"),
        ("---\nid: a\n---\nbody", "needs 'title'"),
        ("---\nid: a\ntitle: A\nauthor: x\n---\nbody", "unknown front matter key"),
        ("---\nid: a\nid: b\ntitle: A\n---\nbody", "duplicate front matter key"),
        ("---\nid a\ntitle: A\n---\nbody", "malformed"),
        ("---\nid: a\ntitle: A\n---\n\n", "empty article"),
    ],
)
def test_malformed_article_is_refused(text, message):
    with pytest.raises(CorpusError, match=message):
        parse_article(text, "x.md")


def test_crlf_article():
    article = parse_article("---\r\nid: a\r\ntitle: A: the first\r\n---\r\nOne.\r\n\r\nTwo.\r\n", "a.md")
    assert (article.id, article.title, article.paragraphs) == ("a", "A: the first", ["One.", "Two."])


def test_duplicate_ids_and_empty_directory_are_refused(tmp_path: Path):
    with pytest.raises(CorpusError, match="no articles"):
        load_articles(tmp_path)
    for name in ("one.md", "two.md"):
        (tmp_path / name).write_text("---\nid: same\ntitle: T\n---\nbody\n", encoding="utf-8")
    with pytest.raises(CorpusError, match="duplicate article id"):
        load_articles(tmp_path)


def test_shorten():
    assert shorten("short", 200) == "short"
    cut = shorten("word " * 100, 50)
    assert len(cut) <= 50 and cut.endswith("…") and not cut[:-1].endswith(" ")
