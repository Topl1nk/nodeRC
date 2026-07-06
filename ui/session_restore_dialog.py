"""session_restore_dialog.py — "Restore previous session?" Prompt

Shown once at app startup when a previous run's session (see core/session.py)
is available. Modal (``exec_()``) so the caller can block synchronously for
one decision. Three buttons instead of a Yes/No + checkbox: "Always Yes" both
answers now and remembers the choice, since a plain checkbox reads ambiguously
next to three otherwise-equal buttons.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton

from localization import t
from ui.theme import PUSHBTN_QSS
from ui.frameless_dialog import FramelessDialogBase


class SessionRestoreDialog(FramelessDialogBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("session_restore_title"))

        # "yes" | "no" | "always" — read by the caller after exec_() returns.
        self.choice: str = "no"

        body = QLabel(t("session_restore_body"))
        body.setObjectName("restoreBody")
        body.setWordWrap(True)
        self.body_layout.addWidget(body)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        for label_key, choice in (
            ("session_restore_yes", "yes"),
            ("session_restore_no", "no"),
            ("session_restore_always_yes", "always"),
        ):
            btn = QPushButton(t(label_key))
            btn.setStyleSheet(PUSHBTN_QSS)
            btn.clicked.connect(lambda _checked=False, c=choice: self._choose(c))
            btn_row.addWidget(btn)
        self.body_layout.addLayout(btn_row)

    def _choose(self, choice: str):
        self.choice = choice
        self.accept()
