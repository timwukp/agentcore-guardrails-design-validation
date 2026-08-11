"""`ar_surface.walk_shape` against hand-built shapes, including self-referential ones.

F8-8's entire content is *which fields the pinned SDK exposes*: it reports TRUE — "no request
surface exists for an AutomatedReasoning language or mode" — on the strength of a sweep finding
nothing. A sweep that finds nothing because it stopped early is indistinguishable from one that
finds nothing because there is nothing, and the verdict is the same either way. So the walker is
tested against shapes constructed here rather than against the live service model, for two
reasons:

1. **The live model cannot exhibit the failure.** botocore's bedrock models may or may not
   contain a cycle today; if they do not, a test over them proves the walker terminates on
   *acyclic* input and says nothing about the case that would crash it. A self-referential shape
   built here always exercises it.
2. **A recursion crash reads as a bug, not as a finding.** The default limit would raise
   RecursionError deep inside a sweep, and the honest reading of that is "the scan did not
   complete" — but F8-8's TRUE is produced by an empty result set, so a partial scan that was
   caught and swallowed anywhere upstream would produce the same TRUE.

The stubs are duck-typed on the four attributes `walk_shape` reads (`name`, `type_name`,
`members`, `member`/`value`, `enum`), which is the same surface botocore's `Shape` exposes. A
real botocore model is used in exactly one test, to confirm the stubs are not a private dialect.
"""

from __future__ import annotations

import pytest

import ar_surface as A


# --------------------------------------------------------------------------- stubs

class Shape:
    """A botocore-Shape-shaped object: only what `walk_shape` actually reads."""

    def __init__(self, name, type_name="string", members=None, member=None,
                 value=None, enum=None):
        self.name = name
        self.type_name = type_name
        self.members = members or {}
        if member is not None:
            self.member = member
        if value is not None:
            self.value = value
        if enum is not None:
            self.enum = enum


def S(_shape_name, **members):
    """A structure. The parameter is underscore-prefixed because `name` is itself a plausible
    member name (`CreateGuardrail` has one), and a positional `name` would collide with it —
    which is how this helper first failed."""
    return Shape(_shape_name, "structure", members=members)


def L(_shape_name, member):
    return Shape(_shape_name, "list", member=member)


def Mp(_shape_name, value):
    return Shape(_shape_name, "map", value=value)


def Str(_shape_name, enum=None):
    return Shape(_shape_name, "string", enum=enum)


# ------------------------------------------------------------------ flat structures

def test_walks_a_flat_structure():
    shape = S("Req", name=Str("Name"), count=Shape("Count", "integer"))
    rows = A.walk_shape(shape)
    assert {r["member"] for r in rows} == {"name", "count"}
    assert {r["path"] for r in rows} == {"name", "count"}


def test_records_is_string_and_enum_separately():
    """The sweep asks two questions per member: does the NAME look like a language field,
    and does the TYPE admit a mode value. A row carrying only the name answers just one."""
    shape = S("Req", mode=Str("Mode", enum=["DETECT", "ENFORCE"]),
              note=Str("Note"), n=Shape("N", "integer"))
    rows = {r["member"]: r for r in A.walk_shape(shape)}
    assert rows["mode"]["is_string"] is True
    assert rows["mode"]["enum"] == ["DETECT", "ENFORCE"]
    assert rows["note"]["is_string"] is True and rows["note"]["enum"] == []
    assert rows["n"]["is_string"] is False


def test_nested_paths_are_dotted():
    shape = S("Req", policy=S("Policy", language=Str("Lang")))
    paths = {r["path"] for r in A.walk_shape(shape)}
    assert "policy" in paths
    assert "policy.language" in paths


def test_list_members_are_marked_with_brackets():
    shape = S("Req", rules=L("Rules", S("Rule", text=Str("Text"))))
    paths = {r["path"] for r in A.walk_shape(shape)}
    assert "rules" in paths
    assert "rules[].text" in paths


def test_map_values_are_marked_with_braces():
    shape = S("Req", tags=Mp("Tags", S("Tag", key=Str("Key"))))
    paths = {r["path"] for r in A.walk_shape(shape)}
    assert "tags{}.key" in paths


def test_an_empty_structure_yields_no_rows_and_does_not_raise():
    assert A.walk_shape(S("Empty")) == []


def test_none_yields_no_rows():
    """`operation_inventory` hands input_shape straight through and it can be None for an
    operation taking no request payload."""
    assert A.walk_shape(None) == []


def test_a_scalar_top_level_shape_yields_no_rows():
    """Not an error: a scalar has no members. It must not be reported as a swept structure."""
    assert A.walk_shape(Str("Bare")) == []


# ----------------------------------------------------------------- self-reference

def test_direct_self_reference_terminates():
    """A shape whose member is itself. Naive recursion raises RecursionError here.

    This is the case the `seen` set exists for, and it is the one a live-model test cannot be
    relied on to provide.
    """
    node = S("Node", label=Str("Label"))
    node.members["child"] = node
    rows = A.walk_shape(node)
    assert rows, "the walk returned nothing at all, which is not termination"
    assert any(r["member"] == "label" for r in rows)


def test_mutual_recursion_terminates():
    """A → B → A. The cycle is longer than one hop, so a depth-1 guard would miss it."""
    a = S("A", tag=Str("Tag"))
    b = S("B", back=a, note=Str("Note"))
    a.members["down"] = b
    rows = A.walk_shape(a)
    assert any(r["member"] == "note" for r in rows)


def test_self_referential_list_terminates():
    """A list whose element type contains the list. Cycles through the list branch too."""
    node = S("Node", name=Str("Name"))
    node.members["children"] = L("NodeList", node)
    rows = A.walk_shape(node)
    assert any(r["path"] == "children[].name" for r in rows)


def test_self_referential_map_terminates():
    node = S("Node", name=Str("Name"))
    node.members["by_id"] = Mp("NodeMap", node)
    rows = A.walk_shape(node)
    assert any(r["path"].startswith("by_id{}") for r in rows)


def test_the_cycle_is_cut_by_shape_and_path_not_by_shape_alone():
    """The same shape reused at two different paths must be reported at BOTH.

    Deduplicating on shape name alone would visit `left.value` and silently skip
    `right.value` — and a member absent from the sweep is exactly what F8-8 reads as "no such
    field exists". The under-reporting failure is the dangerous direction here, because it
    produces TRUE.
    """
    leaf = S("Leaf", value=Str("Value"))
    shape = S("Req", left=leaf, right=leaf)
    paths = {r["path"] for r in A.walk_shape(shape)}
    assert "left.value" in paths
    assert "right.value" in paths


# ------------------------------------------------------------------------- depth

def test_depth_is_bounded():
    """A chain longer than MAX_DEPTH is truncated rather than walked forever."""
    inner = S("D0", leaf=Str("Leaf"))
    for i in range(1, A.MAX_DEPTH + 6):
        inner = S(f"D{i}", down=inner)
    rows = A.walk_shape(inner)
    depths = [r["path"].count(".") for r in rows]
    assert max(depths) <= A.MAX_DEPTH + 1


def test_max_depth_is_deep_enough_for_the_real_models():
    """A bound low enough to truncate a genuine request shape would under-report.

    Truncation and absence are the same thing to the sweep, so the bound has to be above the
    deepest real nesting, not merely finite.
    """
    assert A.MAX_DEPTH >= 8


# ----------------------------------------------------- the stubs are not a dialect

def test_the_walker_handles_a_real_botocore_shape():
    """One test against the live model, so the stubs above cannot drift into a private dialect.

    Deliberately not an assertion about *which* members exist — that is F8-8's job and it reads
    the pinned interpreter. This only asserts the walker consumes a real Shape and produces the
    row keys the sweeps index by.
    """
    import botocore.session

    model = botocore.session.get_session().get_service_model("bedrock")
    op = model.operation_model("CreateGuardrail")
    rows = A.walk_shape(op.input_shape)
    assert rows
    assert {"path", "member", "shape", "type", "is_string", "enum"} <= set(rows[0])
    # A known-nested member, to prove the walk went past the top level.
    assert any(r["path"].startswith("contentPolicyConfig.filtersConfig[]") for r in rows)


def test_every_row_has_the_keys_the_sweeps_index_by():
    """`member_sweep`/`enum_sweep` read fixed keys; a renamed key would make them find nothing
    while still completing, which is the silent-empty failure mode again."""
    shape = S("Req", policy=S("P", mode=Str("Mode", enum=["A"])))
    for r in A.walk_shape(shape):
        assert set(r) == {"path", "member", "shape", "type", "is_string", "enum"}


def test_no_duplicate_paths():
    """A duplicated path would double-count a member in the sweep totals that DEV-P1-9 cites
    (251 members, 75 enums), turning a provenance figure into an artefact of the walk."""
    leaf = S("Leaf", value=Str("Value"))
    shape = S("Req", left=leaf, right=leaf, deep=S("Deep", inner=leaf))
    paths = [r["path"] for r in A.walk_shape(shape)]
    assert len(paths) == len(set(paths))
