"""The shared continuation signal terminates independently of legacy truncated."""

from vmware_nsx.ops._paginate import page_envelope


def page(rows, limit, offset):
    return page_envelope(rows[offset:offset + limit], limit=limit, offset=offset, total=len(rows))

def test_first_and_last_pages_have_a_continuation_contract():
    rows = [{"n": n} for n in range(5)]
    first = page(rows, 2, 0)
    last = page(rows, 2, 4)
    assert first["offset"] == 0
    assert first["next_offset"] == 2
    assert last["next_offset"] is None
    assert last["items"] == [{"n": 4}]
    assert last["truncated"] is True

def test_walk_recovers_every_row_once():
    rows = [{"n": n} for n in range(5)]
    found = []
    seen = set()
    offset = 0
    while offset is not None:
        assert offset not in seen
        seen.add(offset)
        result = page(rows, 2, offset)
        found.extend(result["items"])
        offset = result["next_offset"]
    assert found == rows
    assert page(rows, 2, 9)["next_offset"] is None
