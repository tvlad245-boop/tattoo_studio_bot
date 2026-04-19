from __future__ import annotations

import html as html_lib


def esc(text: object) -> str:
    """Экранирование пользовательского текста для parse_mode=HTML."""
    return html_lib.escape(str(text), quote=True)
