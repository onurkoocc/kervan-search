"""Knowledge base articles: data/kb/*.md with `id` and `title` front matter."""

from dataclasses import dataclass
from pathlib import Path

from .text import tokens

DEFAULT_KB_DIR = Path(__file__).resolve().parents[2] / "data" / "kb"
SNIPPET_CHARS = 200


class CorpusError(Exception):
    pass


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    body: str

    @property
    def paragraphs(self) -> list[str]:
        return [" ".join(p.split()) for p in self.body.split("\n\n") if p.strip()]

    def snippet(self, query: str) -> str:
        """The paragraph sharing the most terms with the query (first on ties), shortened."""
        wanted = set(tokens(query))
        paragraphs = self.paragraphs
        best = max(paragraphs, key=lambda p: len(wanted.intersection(tokens(p))), default="")
        return shorten(best, SNIPPET_CHARS)


def shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0]
    return cut.rstrip(",;:") + "…"


def parse_article(text: str, source: str) -> Article:
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0] != "---":
        raise CorpusError(f"{source}: missing front matter")
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise CorpusError(f"{source}: unterminated front matter") from None
    meta: dict[str, str] = {}
    for line in lines[1:end]:
        key, sep, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not sep or not key or not value:
            raise CorpusError(f"{source}: malformed front matter line {line!r}")
        if key not in ("id", "title"):
            raise CorpusError(f"{source}: unknown front matter key {key!r}")
        if key in meta:
            raise CorpusError(f"{source}: duplicate front matter key {key!r}")
        meta[key] = value
    for key in ("id", "title"):
        if key not in meta:
            raise CorpusError(f"{source}: front matter needs {key!r}")
    body = "\n".join(lines[end + 1 :]).strip()
    if not body:
        raise CorpusError(f"{source}: empty article")
    return Article(id=meta["id"], title=meta["title"], body=body)


def load_articles(kb_dir: Path = DEFAULT_KB_DIR) -> list[Article]:
    """All articles, sorted by id. Refuses an empty directory and duplicate ids."""
    articles: dict[str, Article] = {}
    for path in sorted(kb_dir.glob("*.md")):
        article = parse_article(path.read_text(encoding="utf-8"), path.name)
        if article.id in articles:
            raise CorpusError(f"{path.name}: duplicate article id {article.id!r}")
        articles[article.id] = article
    if not articles:
        raise CorpusError(f"no articles in {kb_dir}")
    return [articles[i] for i in sorted(articles)]
