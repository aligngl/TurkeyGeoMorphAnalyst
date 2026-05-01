# -*- coding: utf-8 -*-
"""Progress dialog UI base."""

from PyQt5 import QtCore, QtWidgets


class Ui_ProgressDialog(object):
    """Small progress dialog used by long-running jobs."""

    def setupUi(self, ProgressDialog):
        ProgressDialog.setObjectName("ProgressDialog")
        ProgressDialog.resize(520, 180)
        self.verticalLayout = QtWidgets.QVBoxLayout(ProgressDialog)
        self.labelStatus = QtWidgets.QLabel(ProgressDialog)
        self.progressBar = QtWidgets.QProgressBar(ProgressDialog)
        self.textLog = QtWidgets.QTextEdit(ProgressDialog)
        self.textLog.setReadOnly(True)
        self.verticalLayout.addWidget(self.labelStatus)
        self.verticalLayout.addWidget(self.progressBar)
        self.verticalLayout.addWidget(self.textLog)
        self.retranslateUi(ProgressDialog)
        QtCore.QMetaObject.connectSlotsByName(ProgressDialog)

    def retranslateUi(self, ProgressDialog):
        _translate = QtCore.QCoreApplication.translate
        ProgressDialog.setWindowTitle(_translate("ProgressDialog", "İşlem Durumu"))
        self.labelStatus.setText(_translate("ProgressDialog", "Hazır"))
