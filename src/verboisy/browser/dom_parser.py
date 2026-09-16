"""
DOM cleaning and parsing utility for optimizing LLM context windows.
"""

from bs4 import BeautifulSoup, Comment

from verboisy.utils.logger import get_logger

logger = get_logger(__name__)


class DOMParser:
    """Cleans raw HTML into a streamlined, LLM-friendly textual/structural representation."""

    @staticmethod
    def clean_html(html_content: str) -> str:
        """
        Remove unnecessary tags (scripts, styles, SVGs, comments) from HTML
        and return a clean, compact HTML string.

        Args:
            html_content: Raw HTML string from page.content()

        Returns:
            str: Cleaned HTML string.
        """
        soup = BeautifulSoup(html_content, "html.parser")

        # Remove unwanted tags
        for tag in soup(["script", "style", "svg", "noscript", "iframe", "footer", "header"]):
            tag.decompose()

        # Remove comments
        comments = soup.findAll(text=lambda text: isinstance(text, Comment))
        for comment in comments:
            comment.extract()

        # Strip attributes that bloat tokens (e.g. inline styles, massive classes)
        for tag in soup.find_all(True):
            allowed_attrs = {}
            for attr in ["href", "src", "alt", "title", "id", "name"]:
                if tag.has_attr(attr):
                    allowed_attrs[attr] = tag[attr]
            tag.attrs = allowed_attrs

        cleaned = str(soup)
        # Collapse multiple newlines/spaces
        cleaned = "\n".join([line.strip() for line in cleaned.splitlines() if line.strip()])
        return cleaned

    @staticmethod
    def extract_interactive_elements(html_content: str) -> str:
        """
        Extract interactive elements (inputs, buttons, links) to help the LLM planner.

        Args:
            html_content: Raw HTML string.

        Returns:
            str: Summarized list of interactive selectors.
        """
        soup = BeautifulSoup(html_content, "html.parser")
        elements = []

        for el in soup.find_all(["a", "button", "input", "select"]):
            tag = el.name
            text = el.get_text(strip=True)[:50]
            href = el.get("href", "")
            el_id = el.get("id", "")
            el_class = " ".join(el.get("class", []))

            elements.append(f"<{tag} id='{el_id}' class='{el_class}' href='{href}'>{text}</{tag}>")

        return "\n".join(elements[:100])  # Cap to 100 elements for token safety
    
    def clean_html(html_content: str) -> str:
        """Clean HTML using DOMParser."""
        return DOMParser.clean_html(html_content)
