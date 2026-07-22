"""LaTeX to Unicode conversion utilities."""

from __future__ import annotations

import re

from pylatexenc import latexwalker
from pylatexenc.latex2text import LatexNodes2Text
from pylatexenc.latexwalker import (
    LatexCharsNode,
    LatexGroupNode,
    LatexMacroNode,
    LatexNode,
)


# Additional LaTeX symbol mappings not handled by pylatexenc
_EXTRA_SYMBOLS = {  # config-globals: ignore -- LaTeX symbol table.
    "|": "‖",  # U+2016 double vertical line (norm)
    "Vert": "‖",  # U+2016 double vertical line (norm) - alias
    "lVert": "‖",  # U+2016 left double vertical line
    "rVert": "‖",  # U+2016 right double vertical line
    "implies": "⟹",  # U+27F9 long double rightarrow
    "iff": "⟺",  # U+27FA long double leftrightarrow
    "impliedby": "⟸",  # U+27F8 long double leftarrow
    "coloneqq": "≔",  # U+2254 colon equals
    "eqqcolon": "≕",  # U+2255 equals colon
    "bigodot": "⨀",  # U+2A00 n-ary circled dot operator
    # todos
    "checkmark": "✓",
    "xmark": "✗",
    "checkmarkemoji": "✅",
    "xmarkemoji": "❌",
    "plusemoji": "➕",
    "exclaim": "❗",
    "question": "❓",
    "wtf": "⁉️",
    "done": "☒",
    "todo": "☐",
    "warning": "⚠",
    # emoji
    "smiley": "☺",
    "frowny": "☹",
    "cool": "😎",
    "thinking": "🤔",
    "thumbsup": "👍",
    "thumbsdown": "👎",
    "heart": "♥",
    "ok": "👌",
    "rocket": "🚀",
    "100": "💯",
    "tada": "🎉",
    "fire": "🔥",
    "lightbulb": "💡",
    "eyes": "👀",
    "brain": "🧠",
    "shrug": "🤷",
    "facepalm": "🤦",
    # reference
    "bullet": "•",
    "star": "★",
    "dagger": "†",
    "ddagger": "‡",
    # cards
    "spadesuit": "♠",
    "clubsuit": "♣",
    "diamondsuit": "♦",
    "heartsuit": "♥",
    # misc
    "sparkles": "✨",
    "boom": "💥",
    "celebrate": "🙌",
    "pray": "🙏",
    "muscle": "💪",
}


# Unicode superscript mappings
_SUPERSCRIPTS = {  # config-globals: ignore -- Unicode mapping table.
    "0": "⁰",
    "1": "¹",
    "2": "²",
    "3": "³",
    "4": "⁴",
    "5": "⁵",
    "6": "⁶",
    "7": "⁷",
    "8": "⁸",
    "9": "⁹",
    "+": "⁺",
    "-": "⁻",
    "=": "⁼",
    "(": "⁽",
    ")": "⁾",
    "*": "⁎",  # U+204E low asterisk (for superscript)
    "a": "ᵃ",
    "b": "ᵇ",
    "c": "ᶜ",
    "d": "ᵈ",
    "e": "ᵉ",
    "f": "ᶠ",
    "g": "ᵍ",
    "h": "ʰ",
    "i": "ⁱ",
    "j": "ʲ",
    "k": "ᵏ",
    "l": "ˡ",
    "m": "ᵐ",
    "n": "ⁿ",
    "o": "ᵒ",
    "p": "ᵖ",
    "r": "ʳ",
    "s": "ˢ",
    "t": "ᵗ",
    "u": "ᵘ",
    "v": "ᵛ",
    "w": "ʷ",
    "x": "ˣ",
    "y": "ʸ",
    "z": "ᶻ",
    # Uppercase (limited Unicode support)
    "A": "ᴬ",
    "B": "ᴮ",
    "D": "ᴰ",
    "E": "ᴱ",
    "G": "ᴳ",
    "H": "ᴴ",
    "I": "ᴵ",
    "J": "ᴶ",
    "K": "ᴷ",
    "L": "ᴸ",
    "M": "ᴹ",
    "N": "ᴺ",
    "O": "ᴼ",
    "P": "ᴾ",
    "R": "ᴿ",
    "T": "ᵀ",
    "U": "ᵁ",
    "V": "ⱽ",
    "W": "ᵂ",
    # Greek letters
    "α": "ᵅ",
    "β": "ᵝ",
    "γ": "ᵞ",
    "δ": "ᵟ",
    "ε": "ᵋ",
    "θ": "ᶿ",
    "ι": "ᶥ",
    "φ": "ᵠ",
    "χ": "ᵡ",
}

# Unicode subscript mappings
# Note: Unicode has limited subscript letters (no uppercase, few Greek)
_SUBSCRIPTS = {  # config-globals: ignore -- Unicode mapping table.
    "0": "₀",
    "1": "₁",
    "2": "₂",
    "3": "₃",
    "4": "₄",
    "5": "₅",
    "6": "₆",
    "7": "₇",
    "8": "₈",
    "9": "₉",
    "+": "₊",
    "-": "₋",
    "=": "₌",
    "(": "₍",
    ")": "₎",
    "*": "∗",  # U+2217 asterisk operator (no true subscript asterisk)
    "a": "ₐ",
    "e": "ₑ",
    "h": "ₕ",
    "i": "ᵢ",
    "j": "ⱼ",
    "k": "ₖ",
    "l": "ₗ",
    "m": "ₘ",
    "n": "ₙ",
    "o": "ₒ",
    "p": "ₚ",
    "r": "ᵣ",
    "s": "ₛ",
    "t": "ₜ",
    "u": "ᵤ",
    "v": "ᵥ",
    "x": "ₓ",
    # Greek letters (very limited)
    "β": "ᵦ",
    "γ": "ᵧ",
    "ρ": "ᵨ",
    "φ": "ᵩ",
    "χ": "ᵪ",
}

_FRACTIONS = {  # config-globals: ignore -- Unicode fraction table.
    ("1", "2"): "½",
    ("1", "3"): "⅓",
    ("2", "3"): "⅔",
    ("1", "4"): "¼",
    ("3", "4"): "¾",
    ("1", "5"): "⅕",
    ("2", "5"): "⅖",
    ("3", "5"): "⅗",
    ("4", "5"): "⅘",
    ("1", "6"): "⅙",
    ("5", "6"): "⅚",
    ("1", "7"): "⅐",
    ("1", "8"): "⅛",
    ("3", "8"): "⅜",
    ("5", "8"): "⅝",
    ("7", "8"): "⅞",
    ("1", "9"): "⅑",
    ("1", "10"): "⅒",
}


def latex2unicode(latex: str) -> str:
    r"""Convert LaTeX math to Unicode representation.

    Handles inline ($...$), display ($$...$$), and bracketed (\\[...\\]) math.
    Converts common math symbols and super/subscripts to Unicode equivalents.

    Uses AST parsing to properly handle subscripts/superscripts with correct scoping.

    Args:
      latex: LaTeX string, with or without delimiters ($, $$, \\[, etc.)

    Returns:
      unicode_math: Unicode representation of the math expression

    Example:
      >>> latex2unicode(r"$e^{i\\pi} + 1 = 0$")
      'eⁱ⁽π⁾ + 1 = 0'
      >>> latex2unicode(r"\\sum_{i=1}^n x_i^2")
      '∑ᵢ₌₁ⁿ xᵢ²'

    """
    # Strip common delimiters if present
    latex = latex.strip()
    if latex.startswith("$$") and latex.endswith("$$"):
        latex = latex[2:-2].strip()
    elif latex.startswith("$") and latex.endswith("$"):
        latex = latex[1:-1].strip()
    elif (latex.startswith(r"\[") and latex.endswith(r"\]")) or (
        latex.startswith(r"\(") and latex.endswith(r"\)")
    ):
        latex = latex[2:-2].strip()

    try:
        # Use AST-based conversion for proper subscript/superscript handling
        return _latex_to_unicode_ast(latex)
    except Exception:  # noqa: BLE001
        # If conversion fails, return original LaTeX
        return latex


def _latex_to_unicode_ast(latex: str) -> str:
    """Convert LaTeX to Unicode using AST parsing.

    This properly handles subscripts/superscripts by parsing the LaTeX structure.

    Args:
      latex: LaTeX string without delimiters

    Returns:
      unicode_math: Unicode representation

    """
    # Parse LaTeX into AST
    walker = latexwalker.LatexWalker(latex)
    nodes, _, _ = walker.get_latex_nodes()

    # Convert AST to Unicode
    result = _nodes_to_unicode(nodes)

    return result


def _process_chars_with_scripts(chars: str) -> str:
    """Process character string containing unbraced ^x or _x patterns.

    Args:
      chars: String potentially containing ^ or _ followed by single character

    Returns:
      processed: String with super/subscripts converted to Unicode

    """
    converter = LatexNodes2Text()
    unicode_text = str(converter.latex_to_text(chars))
    return _convert_scripts(unicode_text)


def _nodes_to_unicode(nodes: list[LatexNode]) -> str:
    converter = LatexNodes2Text()
    result: list[str] = []
    i = 0

    while i < len(nodes):
        node = nodes[i]

        if isinstance(node, LatexCharsNode):
            processed, skip = _process_chars_node(node, nodes, i, converter)
            result.append(processed)
            i += skip

        elif isinstance(node, LatexMacroNode):
            processed, skip = _process_macro_node(node, nodes, i, converter)
            result.append(processed)
            i += skip

        elif isinstance(node, LatexGroupNode):
            group_unicode = _nodes_to_unicode(node.nodelist)
            result.append(group_unicode)
            i += 1

        else:
            i += 1

    return "".join(result)


def _process_chars_node(
    node: LatexCharsNode,
    nodes: list[LatexNode],
    i: int,
    converter: LatexNodes2Text,
) -> tuple[str, int]:
    chars = str(node.chars)

    # Handle trailing ^ or _ followed by group/macro
    if chars.endswith(("^", "_")):
        result, skip = _try_handle_script_after_chars(chars, nodes, i, converter)
        if result:
            return result, skip

    # Handle embedded ^ or _ (e.g., "x_i^2")
    if "^" in chars or "_" in chars:
        return _process_chars_with_scripts(chars), 1

    # Regular character sequence
    return str(converter.latex_to_text(chars)), 1


def _try_handle_script_after_chars(
    chars: str,
    nodes: list[LatexNode],
    i: int,
    converter: LatexNodes2Text,
) -> tuple[str, int]:
    if i + 1 >= len(nodes):
        return "", 0

    is_super = chars.endswith("^")
    next_node = nodes[i + 1]
    base = chars[:-1]
    scripts = _SUPERSCRIPTS if is_super else _SUBSCRIPTS
    open_p = "⁽" if is_super else "₍"
    close_p = "⁾" if is_super else "₎"

    if isinstance(next_node, LatexGroupNode):
        content = _nodes_to_unicode(next_node.nodelist)
        return base + _convert_to_script(content, scripts, open_p, close_p), 2

    if isinstance(next_node, LatexMacroNode):
        macro_text = "\\" + next_node.macroname
        content = str(converter.latex_to_text(macro_text))
        return base + _convert_to_script(content, scripts, open_p, close_p), 2

    return "", 0


def _process_macro_node(
    node: LatexMacroNode,
    nodes: list[LatexNode],
    i: int,
    converter: LatexNodes2Text,
) -> tuple[str, int]:
    macro_name = str(node.macroname)

    # Check custom symbols
    if macro_name in _EXTRA_SYMBOLS:
        return _EXTRA_SYMBOLS[macro_name], 1

    # Handle fractions specially
    if macro_name == "frac":
        result = _try_convert_fraction(node)
        if result:
            return result, 1

    # Convert macro normally
    macro_latex = _reconstruct_macro_latex(node)
    unicode_text = str(converter.latex_to_text(macro_latex))

    # Check if followed by ^{...} or _{...}
    result, skip = _try_handle_script_after_macro(unicode_text, nodes, i)
    if result:
        return result, skip

    return unicode_text, 1


def _try_convert_fraction(node: LatexMacroNode) -> str:
    args = node.nodeargd
    if not (args and args.argnlist and len(args.argnlist) >= 2):
        return ""

    numer_node = args.argnlist[0]
    denom_node = args.argnlist[1]
    if not (numer_node and denom_node):
        return ""

    numer = _nodes_to_unicode(numer_node.nodelist)
    denom = _nodes_to_unicode(denom_node.nodelist)
    return _convert_fraction(numer, denom)


def _try_handle_script_after_macro(
    unicode_text: str,
    nodes: list[LatexNode],
    i: int,
) -> tuple[str, int]:
    if i + 2 >= len(nodes):
        return "", 0

    next_node = nodes[i + 1]
    if not isinstance(next_node, LatexCharsNode):
        return "", 0

    chars = str(next_node.chars)
    if chars not in ("^", "_"):
        return "", 0

    arg_node = nodes[i + 2]
    if not isinstance(arg_node, LatexGroupNode):
        return "", 0

    is_super = chars == "^"
    group_content = _nodes_to_unicode(arg_node.nodelist)
    script = _convert_to_script(
        group_content,
        _SUPERSCRIPTS if is_super else _SUBSCRIPTS,
        "⁽" if is_super else "₍",
        "⁾" if is_super else "₎",
    )
    return unicode_text + script, 3


def _reconstruct_macro_latex(node: LatexMacroNode) -> str:
    result = "\\" + node.macroname
    if node.nodeargd and node.nodeargd.argnlist:
        for arg in node.nodeargd.argnlist:
            if arg:
                arg_content = _reconstruct_nodes_latex(arg.nodelist)
                result += "{" + arg_content + "}"
    return result


def _reconstruct_nodes_latex(nodes: list[LatexNode]) -> str:
    result: list[str] = []
    for node in nodes:
        if isinstance(node, LatexCharsNode):
            result.append(str(node.chars))
        elif isinstance(node, LatexMacroNode):
            result.append(_reconstruct_macro_latex(node))
        elif isinstance(node, LatexGroupNode):
            content = _reconstruct_nodes_latex(node.nodelist)
            result.append("{" + content + "}")
    return "".join(result)


def _convert_fraction(numer: str, denom: str) -> str:
    """Convert fraction to Unicode if available.

    Args:
      numer: Numerator text
      denom: Denominator text

    Returns:
      unicode_frac: Unicode fraction or fallback to "numer/denom"

    """
    frac_unicode = _FRACTIONS.get((numer, denom))
    if frac_unicode:
        return frac_unicode
    return f"{numer}/{denom}"


def _convert_to_script(
    content: str,
    mapping: dict[str, str],
    open_paren: str,
    close_paren: str,
) -> str:
    """Convert content to Unicode super/subscript.

    Args:
      content: Text to convert
      mapping: Character mapping dict (superscripts or subscripts)
      open_paren: Opening parenthesis character (⁽ or ₍)
      close_paren: Closing parenthesis character (⁾ or ₎)

    Returns:
      converted: Unicode super/subscript text

    """
    result: list[str] = []
    unsupported: list[str] = []
    for c in content:
        if c in mapping:
            if unsupported:
                result.append(open_paren + "".join(unsupported) + close_paren)
                unsupported = []
            result.append(mapping[c])
        else:
            unsupported.append(c)
    if unsupported:
        result.append(open_paren + "".join(unsupported) + close_paren)
    return "".join(result)


def _convert_superscript_match(match: re.Match[str]) -> str:
    """Convert regex match to superscript."""
    content = match.group(1) or match.group(2)
    return _convert_to_script(content, _SUPERSCRIPTS, "⁽", "⁾")


def _convert_subscript_match(match: re.Match[str]) -> str:
    """Convert regex match to subscript."""
    content = match.group(1) or match.group(2)
    return _convert_to_script(content, _SUBSCRIPTS, "₍", "₎")


def _convert_scripts(text: str) -> str:
    """Convert ^x and _x notation to Unicode super/subscripts.

    Args:
      text: Text with ^x (superscript) and _x (subscript) notation

    Returns:
      text: Text with Unicode super/subscripts

    """
    # Match super/subscripts: ^{...} or ^xyz (until whitespace)
    # Include Greek, math operators (set/logic symbols), brackets, braces, and common symbols
    # This handles both LaTeX braced form and pylatexenc's stripped form
    #
    # Limitation: Cannot reliably distinguish _{1}P from _{1P} after pylatexenc processing
    # because braces are stripped. For cases like _{1}P^{111}, may over-match.
    # Workaround: Avoid whitespace before variables in LaTeX source, or process before
    # pylatexenc (would require significant refactoring).
    text = re.sub(
        r"\^(?:\{([^}]+)\}|([a-zA-Z0-9α-ωΑ-Ω+\-=∈∉⊂⊃⊆⊇∪∩∞ϵ*]+))",
        _convert_superscript_match,
        text,
    )
    text = re.sub(
        r"_(?:\{([^}]+)\}|([a-zA-Z0-9α-ωΑ-Ω+\-=∈∉⊂⊃⊆⊇∪∩∞ϵ*]+))",
        _convert_subscript_match,
        text,
    )

    return text
