"""The LaTeX → Unicode converter.

It runs both on hosts without a TeX toolchain and when one specific formula fails
to compile, so its hard requirement is that no markup ever reaches the frame: a
rendered `\tau_{\rm cw}` is worse than no formula at all.
"""

from __future__ import annotations

import pytest

from eduharness.stage2.adapters.manim import _latex_to_plain


@pytest.mark.parametrize(
    "tex, expected",
    [
        (r"\tau = F \times r_{\perp}", "τ = F × r⊥"),
        (r"\tau_{\rm cw} = \tau_{\rm ccw}", "τ_cw = τ_ccw"),
        (r"r = 0.5\ \rm m", "r = 0.5 m"),
        (r"F_1 r_1 = F_2 r_2", "F₁ r₁ = F₂ r₂"),
        (r"\frac{F_1}{F_2} = \frac{r_2}{r_1}", "F₁/F₂ = r₂/r₁"),
        (r"x^2 + y^{2} = z^{2}", "x² + y² = z²"),
        (r"\sqrt{a^2+b^2}", "√(a²+b²)"),
        (r"\text{Torque } \tau = F \cdot d", "Torque τ = F · d"),
        (r"10\,\mathrm{N} \times 0.3\,\mathrm{m}", "10 N × 0.3 m"),
        (r"\theta \approx 45^\circ", "θ ≈ 45°"),
        (r"\unknowncmd{keep me}", "keep me"),
        (r"50\%", "50%"),
        ("", "equation"),
    ],
)
def test_known_conversions(tex: str, expected: str) -> None:
    assert _latex_to_plain(tex) == expected


@pytest.mark.parametrize(
    "tex",
    [
        r"\tau_{\rm cw} = \tau_{\rm ccw}",
        r"r = 0.5\ \rm m",
        r"\frac{\partial f}{\partial x}\Big|_{x=0}",
        r"\begin{aligned} a &= b \\ c &= d \end{aligned}",
        r"\vec{F} \cdot \hat{n}\;\mathrm{[N]}",
        r"\left\{ \frac{1}{2} \right\}",
        r"\alpha\beta\gamma_{\mathrm{total}}^{(2)}",
        "\\",
        "{{{",
    ],
)
def test_never_leaks_markup(tex: str) -> None:
    out = _latex_to_plain(tex)
    assert "\\" not in out, out
    assert "{" not in out and "}" not in out, out
    assert out.strip(), "must never render empty"


def test_subscript_uses_unicode_when_every_character_maps() -> None:
    assert _latex_to_plain(r"F_{12}") == "F₁₂"
    # 'c' and 'w' have no Unicode subscript, so the marker is kept instead
    assert _latex_to_plain(r"\tau_{cw}") == "τ_cw"


def test_over_escaped_raw_strings_are_repaired() -> None:
    """Models emitting code inside JSON often double-escape a raw string, and
    `\\` before a letter is never valid TeX — it reaches LaTeX as a line break
    plus the bare word. Assert on the literal's *value*, not on escape soup."""
    import ast

    from eduharness.stage2.adapters.manim import normalize_tex_escapes

    bs = chr(92)
    broken = 'f = MathTex(r"' + bs * 2 + "tau = F " + bs * 2 + 'times r")'
    value = ast.parse(normalize_tex_escapes(broken)).body[0].value.args[0].value
    assert value == bs + "tau = F " + bs + "times r"

    healthy = 'f = MathTex(r"' + bs + 'tau = F")'
    kept = ast.parse(normalize_tex_escapes(healthy)).body[0].value.args[0].value
    assert kept == bs + "tau = F"


def test_repaired_formula_converts_cleanly() -> None:
    """End to end: an over-escaped formula must survive both paths."""
    import ast

    from eduharness.stage2.adapters.manim import normalize_tex_escapes

    bs = chr(92)
    broken = 'f = MathTex(r"' + bs * 2 + "tau_{" + bs * 2 + 'rm cw}")'
    value = ast.parse(normalize_tex_escapes(broken)).body[0].value.args[0].value
    assert _latex_to_plain(value) == "τ_cw"


def test_upright_units_and_thin_spaces_read_as_prose() -> None:
    """The regression that shipped a broken frame: `\\mathrm` leaked as the word
    "mathrm" and `\\,` vanished without a space, so a worked solution rendered as
    `tau_mathrmcw= tau_mathrmccw`. Every unit wrapper is transparent and every
    LaTeX spacer becomes one real space."""
    bs = chr(92)
    cases = {
        bs + "tau_{" + bs + "mathrm{cw}} = " + bs + "tau_{" + bs + "mathrm{ccw}}":
            "τ_cw = τ_ccw",
        "10" + bs + "," + bs + "mathrm{N} " + bs + "times 0.3" + bs + "," + bs + "mathrm{m}":
            "10 N × 0.3 m",
        "3" + bs + "," + bs + "mathrm{N{" + bs + "cdot}m} = 6r":
            "3 N·m = 6r",
        "r = 0.5" + bs + "," + bs + "mathrm{m}":
            "r = 0.5 m",
    }
    for tex, expected in cases.items():
        assert _latex_to_plain(tex) == expected


def test_over_escaped_thin_spaces_are_repaired_but_line_breaks_are_kept() -> None:
    """`\\\\,` is a line break followed by a literal comma, which is how a one-line
    formula shipped shredded across four lines with stray commas down its left
    edge. A real `\\\\` break -- followed by whitespace -- must survive."""
    import ast

    from eduharness.stage2.adapters.manim import normalize_tex_escapes

    bs = chr(92)

    def literal(src: str) -> str:
        return ast.parse(normalize_tex_escapes(src)).body[0].value.args[0].value

    broken = "f = MathTex('10" + bs * 4 + "," + bs * 2 + "mathrm{N}')"
    assert literal(broken) == "10" + bs + "," + bs + "mathrm{N}"
    assert _latex_to_plain(literal(broken)) == "10 N"

    for spacer in ";:!":
        src = "f = MathTex('a" + bs * 4 + spacer + "b')"
        assert literal(src) == "a" + bs + spacer + "b"

    kept = 'f = MathTex(r"x' + bs * 2 + ' y")'
    assert literal(kept) == "x" + bs * 2 + " y", "a deliberate line break must survive"
