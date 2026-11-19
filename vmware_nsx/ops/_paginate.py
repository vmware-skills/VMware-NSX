"""Shared limit/offset validation and the next-page signal for list ops.

The family envelope (``vmware_policy.envelope.paginated``) has six keys and
every one describes the page in hand: how many rows came back, the limit that
produced them, the collection size, whether this is all of it, and a sentence
about that. None of them says where the *next* page starts, so a tool that
takes an ``offset`` still leaves an agent with nowhere to go.

``truncated`` is not that signal and cannot be made into one. It answers "is
``items`` the whole collection?", which stays true on the last page of a paged
walk — page three of three holds one row out of ten. A loop driven by it never
terminates. So the ops here add a ``next_offset`` extra alongside the six, and
that is what a loop stops on.
"""

from __future__ import annotations

from vmware_nsx.connection import _MAX_ITEMS

#: Default page size for list operations — the family list-tool convention
#: (bounded results; the agent pages or narrows for more).
DEFAULT_LIMIT = 50

#: Largest page a caller may ask for. Matches the connection layer's own
#: ``get_all`` backstop: a bigger limit could not be satisfied anyway, so
#: accepting one would promise a page this client cannot deliver.
MAX_LIMIT = _MAX_ITEMS


def validate_page_args(limit: int, offset: int) -> None:
    """Reject a page window that cannot mean what it says.

    ``limit`` is a page size: an integer from 1 to :data:`MAX_LIMIT`. It is
    never a synonym for "unlimited", "none" or "the default" — across this
    family ``limit=0`` had picked up all four readings, so a caller passing it
    could not know which tool did what. Here it is simply out of range.

    A *negative* limit is worse than ambiguous: ``items[offset:offset + limit]``
    is legal Python that quietly returns a shorter page than asked for, so the
    caller gets a truncated answer with nothing saying rows were dropped.

    ``offset`` is a count of rows to skip: an integer from 0 up.

    Raises:
        ValueError: If either value is outside its range. The message names the
            accepted range and points at ``offset``, since "limit too large"
            and "I need more rows" are the same request.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > MAX_LIMIT:
        raise ValueError(
            f"Invalid limit {limit!r}: it is a page size and must be an "
            f"integer from 1 to {MAX_LIMIT}. It is not a way to ask for "
            f"everything — 0 and negatives are rejected rather than guessed "
            f"at. To read more than one page, keep limit within range and "
            f"pass the response's 'next_offset' back as 'offset' until it is "
            f"null."
        )
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError(
            f"Invalid offset {offset!r}: it is the number of rows to skip and "
            f"must be an integer of 0 or more. Start at 0 and pass the "
            f"response's 'next_offset' back as 'offset' for each following "
            f"page, stopping when it is null."
        )


def paginate(items: list[dict], limit: int, offset: int) -> list[dict]:
    """Return the ``limit``-sized window of ``items`` starting at ``offset``.

    Callers validate first, so out-of-range values do not reach here. The guard
    stays anyway: it is the last thing between a negative limit and a page
    silently missing its final row, and it costs one comparison.
    """
    if limit <= 0:
        return []
    start = max(offset, 0)
    return items[start : start + limit]


def next_offset(returned: int, limit: int, offset: int, total: int | None) -> int | None:
    """The ``offset`` for the next page, or ``None`` when this page is the last.

    This — not ``truncated`` — is what a paging loop terminates on.

    With a ``total`` the answer is exact: there is a next page when rows remain
    behind the window this one consumed. Without one, a page filled exactly to
    the limit cannot be told apart from a page that was cut short, so it is
    reported as having a successor. Being wrong that way costs one more call
    that comes back empty and ends the walk; being wrong the other way costs
    rows the caller never learns exist.

    Args:
        returned: Rows in this page.
        limit: The validated page size that produced it.
        offset: The validated offset this page started at.
        total: The collection size when the manager reported one, else ``None``.

    Returns:
        The next offset, or ``None`` if this page ends the collection.
    """
    from vmware_policy.envelope import next_offset as shared_next_offset

    return shared_next_offset(returned, limit, offset, total)


def page_hint(
    returned: int, limit: int, offset: int, total: int | None, nxt: int | None
) -> str | None:
    """The sentence a caller should act on, or ``None`` when there is nothing to do.

    ``vmware_policy.paginated`` writes this field, and it cannot write it
    correctly: it is not given the ``offset``, so it cannot tell a page in the
    middle of a walk from the last one. Every truncated page therefore got the
    same sentence — "Raise limit or narrow the query with a filter to see the
    rest" — including the page that *is* the rest, and the page past the end
    where ``returned`` is 0. Raising a limit there returns nothing; narrowing a
    filter returns less than nothing. It was the one field in the envelope
    written for a reader rather than a machine, and it was the one field giving
    false advice.

    The remedy is not to redefine ``truncated``. That key answers "is ``items``
    the whole collection?" and on the last page of a walk the answer is still
    no — three rows out of twelve. It is ``next_offset`` that says the walk is
    over, and it already did. So the semantics stay and the sentence is
    rewritten from the offset the ops layer has and the shared package does not.
    """
    from vmware_policy.envelope import page_hint as shared_page_hint

    return shared_page_hint(returned, limit, offset, total, nxt)


def page_envelope(
    items: list[dict],
    *,
    limit: int,
    offset: int,
    total: int | None,
    **extra: object,
) -> dict:
    """The family envelope for one page of a walk, with a hint that fits it.

    One helper rather than the incantation
    ``paginated(rows, limit=..., total=..., next_offset=next_offset(...))``
    repeated at every list op: ten copies of a four-line rule is ten chances for
    the eleventh to differ, which is 形态 #6 — a fact with no mechanical relation
    to the code that has to keep it true. Everything the six family keys mean is
    unchanged; ``next_offset`` is still the stop signal and ``truncated`` still
    answers whether ``items`` is the whole collection.
    """
    from vmware_policy import page_envelope as shared_page_envelope

    return shared_page_envelope(items, limit=limit, offset=offset, total=total, **extra)
