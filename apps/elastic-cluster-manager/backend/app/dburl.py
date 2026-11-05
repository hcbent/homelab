"""Turn the SQLAlchemy database URL into a libpq URL with every part percent-encoded.

Pasting a password into a URL by string interpolation breaks as soon as it contains # / ? @ : or %, and the
failure can echo part of the password into a log. Building the URL from its parts, and encoding each one, does not.
"""
from urllib.parse import quote, urlencode

from sqlalchemy.engine import make_url


def libpq_url(sqlalchemy_url: str) -> str:
    """postgresql+psycopg://user:pw@host:5432/db  ->  postgresql://user:pw@host:5432/db, encoded.

    Returns an empty string for anything that is not PostgreSQL (the tests run on SQLite).
    """
    url = make_url(sqlalchemy_url)
    if url.get_backend_name() != "postgresql":
        return ""
    auth = ""
    if url.username is not None:
        auth = quote(url.username, safe="")
        if url.password is not None:
            auth += ":" + quote(url.password, safe="")
        auth += "@"
    host = url.host or ""
    if ":" in host:  # an IPv6 literal
        host = f"[{host}]"
    port = f":{url.port}" if url.port else ""
    database = "/" + quote(url.database, safe="") if url.database else ""
    query = "?" + urlencode(dict(url.query), doseq=True) if url.query else ""
    return f"postgresql://{auth}{host}{port}{database}{query}"
