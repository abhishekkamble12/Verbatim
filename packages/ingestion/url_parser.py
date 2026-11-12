"""URL and HTML document extraction using Trafilatura."""

from pydantic import BaseModel


class ExtractedWebDocument(BaseModel):
    url: str | None = None
    title: str | None = None
    text: str
    author: str | None = None
    date: str | None = None


def parse_html_content(html: str, url: str | None = None) -> ExtractedWebDocument:
    """Extract clean article content and metadata from raw HTML."""
    import trafilatura

    extracted_text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        no_fallback=False,
    )
    if not extracted_text:
        # Fallback to plain regex tag stripping if trafilatura fails on minimal snippets
        import re
        extracted_text = re.sub(r"<[^>]+>", " ", html)
        extracted_text = re.sub(r"\s+", " ", extracted_text).strip()

    metadata = trafilatura.extract_metadata(html)
    title = metadata.title if metadata else None
    author = metadata.author if metadata else None
    date = metadata.date if metadata else None

    return ExtractedWebDocument(
        url=url,
        title=title,
        text=extracted_text or "",
        author=author,
        date=date,
    )


def parse_url(url: str) -> ExtractedWebDocument:
    """Fetch and parse webpage from URL safely with SSRF protection."""
    from packages.ingestion.ssrf_guard import validate_url_safe

    safe_url = validate_url_safe(url)
    import trafilatura

    downloaded = trafilatura.fetch_url(safe_url)
    if not downloaded:
        raise ValueError(f"Could not retrieve webpage content from {safe_url}")

    return parse_html_content(downloaded, url=safe_url)

