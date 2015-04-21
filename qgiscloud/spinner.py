# -*- coding: utf-8 -*-
"""
/***************************************************************************
 QgisCloudPluginDialog
                                 A QGIS plugin
 Publish maps on qgiscloud.com
                             -------------------
        begin                : 2011-04-04
        copyright            : (C) 2011 by Sourcepole
        email                : pka@sourcepole.ch
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from PyQt4.QtCore import *
from PyQt4.QtGui import *
import math


class Spinner(QWidget):

    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.ticks = 12
        self.counter = 0
        self.timer = None
        self.setMinimumSize(16, 16)

    def start(self):
        self.timer = self.startTimer(1000 / self.ticks)
        self.counter = 0

    def stop(self):
        if self.timer:
            self.killTimer(self.timer)
            self.timer = None
        self.counter = 0

    def timerEvent(self, ev):
        self.counter = (self.counter + 1) % self.ticks
        self.update()

    def paintEvent(self, ev):
        sz = self.size()
        l = 0.5 * min(sz.width(), sz.height())

        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        painter.setRenderHint(QPainter.Antialiasing, True)
        for i in range(0, self.ticks):
            painter.save()
            painter.translate(0.5 * sz.width(), 0.5 * sz.height())
            painter.rotate((360. * i) / self.ticks)
            painter.translate(0.4 * l, 0)
            k = float(self.ticks + (i - self.counter)) % self.ticks / self.ticks
            painter.setBrush(QColor(0, 0, 0, 255 * (0.9 * k + 0.1)))
            painter.drawRoundedRect(
                QRect(0, -0.1 * l, 0.6 * l, 0.2 * l), 0.15 * l, 0.1 * l)
            painter.restore()