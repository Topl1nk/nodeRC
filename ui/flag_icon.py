"""flag_icon.py — Window Icon Reflecting the Active UI Language

Paints a small flag pixmap in memory so the taskbar/titlebar icon always shows
which locale the editor is running in — no bundled image assets to go stale.
"""
from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

_ICON_W, _ICON_H = 32, 24


def _paint_ukrainian(painter: QPainter):
    stripe_h = _ICON_H // 2
    painter.fillRect(0, 0, _ICON_W, stripe_h, QColor("#0057B7"))
    painter.fillRect(0, stripe_h, _ICON_W, _ICON_H - stripe_h, QColor("#FFD700"))


def _paint_english(painter: QPainter):
    # Dual USA/UK flag: USA on the left half, UK on the right half.
    painter.save()
    painter.setClipRect(0, 0, 16, 24)
    painter.fillRect(0, 0, 16, 24, QColor("#FFFFFF"))
    stripe_h = 24.0 / 7.0
    for i in range(0, 7, 2):
        painter.fillRect(0, int(i * stripe_h), 16, int(stripe_h), QColor("#B22234"))
    painter.fillRect(0, 0, 9, 12, QColor("#3C3B6E"))
    painter.setPen(QColor("#FFFFFF"))
    painter.drawPoint(2, 3)
    painter.drawPoint(6, 3)
    painter.drawPoint(4, 6)
    painter.drawPoint(2, 9)
    painter.drawPoint(6, 9)
    painter.restore()

    painter.save()
    painter.setClipRect(16, 0, 16, 24)
    painter.fillRect(16, 0, 16, 24, QColor("#012169"))

    painter.setPen(QPen(QColor("#FFFFFF"), 3))
    painter.drawLine(16, 0, 32, 24)
    painter.drawLine(16, 24, 32, 0)

    painter.setPen(QPen(QColor("#C8102E"), 1))
    painter.drawLine(16, 0, 32, 24)
    painter.drawLine(16, 24, 32, 0)

    painter.fillRect(24 - 3, 0, 6, 24, QColor("#FFFFFF"))
    painter.fillRect(16, 12 - 3, 16, 6, QColor("#FFFFFF"))

    painter.fillRect(24 - 1, 0, 2, 24, QColor("#C8102E"))
    painter.fillRect(16, 12 - 1, 16, 2, QColor("#C8102E"))
    painter.restore()


def language_flag_icon(lang: str) -> QIcon:
    pixmap = QPixmap(_ICON_W, _ICON_H)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    if lang == "uk":
        _paint_ukrainian(painter)
    else:
        _paint_english(painter)

    # Thin gray outline keeps the flag readable on both dark and light taskbars.
    painter.setPen(QPen(QColor("#555555"), 1))
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(0, 0, _ICON_W - 1, _ICON_H - 1)

    painter.end()
    return QIcon(pixmap)
