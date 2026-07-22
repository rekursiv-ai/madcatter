from ._unicode_to_latex_encoder import UnicodeToLatexEncoder

logger = ...

class PartialLatexToLatexEncoder(UnicodeToLatexEncoder):
    def __init__(
        self, keep_latex_chars=..., conversion_rules=..., **kwargs
    ) -> None: ...
