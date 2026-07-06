"""message_dialog.py — App-Themed Error/Warning Prompt

Drop-in replacement for QMessageBox.critical()/warning(): same call shape
(``MessageDialog.critical(parent, title, text)``), but frameless and styled
like every other secondary window in the app instead of the native OS
message box.
"""
from __future__ import annotations

from PyQt5.QtWidgets import QHBoxLayout, QLabel, QPushButton

from localization import t
from ui.theme import PUSHBTN_QSS
from ui.frameless_dialog import FramelessDialogBase


class MessageDialog(FramelessDialogBase):
    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)

        body = QLabel(text)
        body.setObjectName("restoreBody")
        body.setWordWrap(True)
        self.body_layout.addWidget(body)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok_btn = QPushButton(t("dialog_ok"))
        ok_btn.setStyleSheet(PUSHBTN_QSS)
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)
        self.body_layout.addLayout(btn_row)

    @staticmethod
    def critical(parent, title: str, text: str):
        MessageDialog(title, text, parent).exec_()

    @staticmethod
    def warning(parent, title: str, text: str):
        MessageDialog(title, text, parent).exec_()
