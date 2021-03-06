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
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from PyQt4.QtCore import *
from PyQt4.QtGui import *
from PyQt4.QtXml import *
from qgis.core import *
from ui_qgiscloudplugin import Ui_QgisCloudPlugin
from ui_login import Ui_LoginDialog
from qgiscloudapi.qgiscloudapi import *
from db_connections import DbConnections
from local_data_sources import LocalDataSources
from data_upload import DataUpload
from doAbout import DlgAbout
from error_report_dialog import ErrorReportDialog
import os.path
import sys
import traceback
import string
import re
import time
import platform
from distutils.version import StrictVersion


class QgisCloudPluginDialog(QDockWidget):
    COLUMN_LAYERS = 0
    COLUMN_DATA_SOURCE = 1
    COLUMN_TABLE_NAME = 2
    COLUMN_GEOMETRY_TYPE = 3
    COLUMN_SRID = 4

    FREE_SIZE = 50
    PRO_SIZE = 500
    RESELLER_SIZE = 5000

    GEOMETRY_TYPES = {
        QGis.WKBUnknown: "Unknown",
        QGis.WKBPoint: "Point",
        QGis.WKBMultiPoint: "MultiPoint",
        QGis.WKBLineString: "LineString",
        QGis.WKBMultiLineString: "MultiLineString",
        QGis.WKBPolygon: "Polygon",
        QGis.WKBMultiPolygon: "MultiPolygon",
        # Workaround (missing Python binding?): QGis.WKBNoGeometry /
        # ogr.wkbNone
        100: "No geometry",
        QGis.WKBPoint25D: "Point",
        QGis.WKBLineString25D: "LineString",
        QGis.WKBPolygon25D: "Polygon",
        QGis.WKBMultiPoint25D: "MultiPoint",
        QGis.WKBMultiLineString25D: "MultiLineString",
        QGis.WKBMultiPolygon25D: "MultiPolygon"
    }

    def __init__(self, iface, version):
        QDockWidget.__init__(self, None)
        self.iface = iface
        self.clouddb = True
        self.version = version
        # Set up the user interface from Designer.
        self.ui = Ui_QgisCloudPlugin()
        self.ui.setupUi(self)

        myAbout = DlgAbout()
        self.ui.aboutText.setText(
            myAbout.aboutString() +
            myAbout.contribString() +
            myAbout.licenseString() +
            "<p>Versions:<ul>" +
            "<li>QGIS: %s</li>" % QGis.QGIS_VERSION +
            "<li>Python: %s</li>" % sys.version.replace("\n", " ") +
            "<li>OS: %s</li>" % platform.platform() +
            "</ul></p>")
        self.ui.lblVersionPlugin.setText(self.version)

        self.ui.tblLocalLayers.setColumnCount(5)
        header = ["Layers", "Data source",
                  "Table name", "Geometry type", "SRID"]
        self.ui.tblLocalLayers.setHorizontalHeaderLabels(header)
        self.ui.tblLocalLayers.resizeColumnsToContents()
        self.ui.tblLocalLayers.setEditTriggers(QAbstractItemView.NoEditTriggers)

        self.ui.btnUploadData.setEnabled(False)
        self.ui.progressWidget.hide()
        self.ui.btnLogout.hide()
        self.ui.lblLoginStatus.hide()
        self.ui.widgetServices.hide()
        self.ui.widgetDatabases.setEnabled(False)
        self.ui.labelOpenLayersPlugin.hide()

        try:
            if QGis.QGIS_VERSION_INT >= 20300:
                from openlayers_menu import OpenlayersMenu
            else:
                # QGIS 1.x - QGIS-2.2
                from openlayers_menu_compat import OpenlayersMenu
            self.ui.btnBackgroundLayer.setMenu(OpenlayersMenu(self.iface))
        except:
            self.ui.btnBackgroundLayer.hide()
            self.ui.labelOpenLayersPlugin.show()

        # map<data source, table name>
        self.data_sources_table_names = {}
        # flag to disable update of local data sources during upload
        self.do_update_local_data_sources = True

        QObject.connect(self.ui.btnLogin, SIGNAL("clicked()"), self.check_login)
        QObject.connect(
            self.ui.btnDbCreate, SIGNAL("clicked()"), self.create_database)
        QObject.connect(
            self.ui.btnDbDelete, SIGNAL("clicked()"), self.delete_database)
        QObject.connect(
            self.ui.btnDbRefresh, SIGNAL("clicked()"), self.refresh_databases)
        QObject.connect(self.ui.tabDatabases, SIGNAL(
            "itemSelectionChanged()"), self.select_database)
        QObject.connect(
            self.ui.btnPublishMap, SIGNAL("clicked()"), self.publish_map)
        QObject.connect(self.ui.btnRefreshLocalLayers, SIGNAL(
            "clicked()"), self.refresh_local_data_sources)
        QObject.connect(
            self.iface, SIGNAL("newProjectCreated()"), self.reset_load_data)
        QObject.connect(QgsMapLayerRegistry.instance(), SIGNAL(
            "layerWillBeRemoved(QString)"), self.remove_layer)
        QObject.connect(QgsMapLayerRegistry.instance(), SIGNAL(
            "layerWasAdded(QgsMapLayer *)"), self.add_layer)
        QObject.connect(self.ui.cbUploadDatabase, SIGNAL(
            "currentIndexChanged(int)"), lambda idx: self.activate_upload_button())
        QObject.connect(
            self.ui.btnUploadData, SIGNAL("clicked()"), self.upload_data)

        self.ui.editServer.textChanged.connect(self.serverURL)
        self.ui.resetUrlBtn.clicked.connect(self.resetApiUrl)

        self.read_settings()
        self.api = API()
        self.db_connections = DbConnections()
        self.local_data_sources = LocalDataSources()
        self.data_upload = DataUpload(
            self.iface, self.statusBar(), self.ui.lblProgress, self.api,
            self.db_connections)

        if self.URL == "":
            self.ui.editServer.setText(self.api.api_url())
        else:
            self.ui.editServer.setText(self.URL)

        self.palette_red = QPalette(self.ui.lblVersionPlugin.palette())
        self.palette_red.setColor(QPalette.WindowText, Qt.red)

    def __del__(self):
        self.do_update_local_data_sources = False
        if self.iface:
            QObject.disconnect(
                self.iface, SIGNAL("newProjectCreated()"),
                self.reset_load_data)
        if QgsMapLayerRegistry.instance():
            QObject.disconnect(QgsMapLayerRegistry.instance(), SIGNAL(
                "layerWillBeRemoved(QString)"), self.remove_layer)
            QObject.disconnect(QgsMapLayerRegistry.instance(), SIGNAL(
                "layerWasAdded(QgsMapLayer *)"), self.add_layer)

    def statusBar(self):
        return self.iface.mainWindow().statusBar()

    def map(self):
        project = QgsProject.instance()
        name = os.path.splitext(
            os.path.basename(unicode(project.fileName())))[0]
        # Allowed chars for QGISCloud map name: /\A[A-Za-z0-9\_\-]*\Z/
        name = unicode(name).encode(
            'ascii', 'replace')  # Replace non-ascii chars
        # Replace withespace
        name = re.compile("\W+", re.UNICODE).sub("_", name)
        return name

    def resetApiUrl(self):
        self.ui.editServer.setText(self.api.api_url())

    def serverURL(self, URL):
        self.URL = URL
        self.store_settings()

    def store_settings(self):
        s = QSettings()
        s.setValue("qgiscloud/user", self.user)
        s.setValue("qgiscloud/URL", self.URL)

    def read_settings(self):
        s = QSettings()
        self.user = s.value("qgiscloud/user", "", type=str)
        self.URL = s.value("qgiscloud/URL", "", type=str)

    def _update_clouddb_mode(self, clouddb):
        self.clouddb = clouddb
        self.ui.widgetDatabases.setVisible(self.clouddb)
        tab_index = 1
        tab_name = QApplication.translate("QgisCloudPlugin", "Upload Data")
        visible = (self.ui.tabWidget.indexOf(self.ui.uploadTab) == tab_index)
        if visible and not self.clouddb:
            self.ui.tabWidget.removeTab(tab_index)
        elif not visible and self.clouddb:
            self.ui.tabWidget.insertTab(tab_index, self.ui.uploadTab, tab_name)

    def _version_info(self):
        return {
            'versions': {
                'plugin': self.version,
                'QGIS': QGis.QGIS_VERSION,
                'OS': platform.platform(),
                'Python': sys.version
            }
        }

    def check_login(self):
        version_ok = True
        if not self.api.check_auth():
            login_dialog = QDialog(self)
            login_dialog.ui = Ui_LoginDialog()
            login_dialog.ui.setupUi(login_dialog)
            login_dialog.ui.editUser.setText(self.user)
            login_ok = False
            while not login_ok and version_ok:
                self.api.set_url(self.api_url())
                if not login_dialog.exec_():
                    self.api.set_auth(
                        user=login_dialog.ui.editUser.text(), password=None)
                    return login_ok
                self.api.set_auth(
                    user=login_dialog.ui.editUser.text(),
                    password=login_dialog.ui.editPassword.text())
                try:
                    login_info = self.api.check_login(
                        version_info=self._version_info())
                    #{u'paid_until': None, u'plan': u'Free'
                    # u'current_plugin': u'0.8.0'}
                    self.user = login_dialog.ui.editUser.text()
                    self._update_clouddb_mode(login_info['clouddb'])
                    version_ok = StrictVersion(self.version) >= StrictVersion(login_info['current_plugin'])
                    if not version_ok:
                        self.ui.lblVersionPlugin.setPalette(self.palette_red)
                    self.store_settings()
                    self.ui.btnLogin.hide()
                    self.ui.lblSignup.hide()
                    self.ui.btnLogout.show()
                    self.ui.widgetDatabases.setEnabled(True)

                    self.ui.lblLoginStatus.setText(
                        self.tr_uni("Logged in as {0} ({1})").format(self.user, login_info['plan']))
                    self.ui.lblLoginStatus.show()
                    self._push_message(
                        self.tr("QGIS Cloud"),
                        self.tr_uni("Logged in as {0}").format(self.user),
                        level=0, duration=2)
                    self.refresh_databases()
                    if not version_ok:
                        self._push_message(self.tr("QGIS Cloud"), self.tr(
                            "Unsupported versions detected. Please check your versions first!"), level=1)
                        version_ok = False
                        self.ui.tabWidget.setCurrentWidget(self.ui.aboutTab)
                    login_ok = True
                except (UnauthorizedError, TokenRequiredError, ConnectionException):
                    QMessageBox.critical(
                        self, self.tr("Login failed"),
                        self.tr("Wrong user name or password"))
                    login_ok = False
        return version_ok

    def create_database(self):
        db = self.api.create_database()
        # {u'username': u'jhzgpfwi_qgiscloud',
        # u'host': u'beta.spacialdb.com', u'password': u'11d7338c',
        # u'name': u'jhzgpfwi_qgiscloud', u'port': 9999}
        self.show_api_error(db)
        self.refresh_databases()

    def delete_database(self):
        name = self.ui.tabDatabases.currentItem().text()
        msgBox = QMessageBox()
        msgBox.setText(self.tr("Delete QGIS Cloud database."))
        msgBox.setInformativeText(
            self.tr_uni("Do you want to delete the database \"%s\"?") % name)
        msgBox.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        msgBox.setDefaultButton(QMessageBox.Cancel)
        msgBox.setIcon(QMessageBox.Question)
        ret = msgBox.exec_()
        if ret == QMessageBox.Ok:
            self.setCursor(Qt.WaitCursor)
            result = self.api.delete_database(name)
            self.show_api_error(result)
            self.ui.btnDbDelete.setEnabled(False)
            time.sleep(2)
            self.refresh_databases()
            self.unsetCursor()

    def select_database(self):
        self.ui.btnDbDelete.setEnabled(
            len(self.ui.tabDatabases.selectedItems()) > 0)

    @pyqtSignature('')
    def on_btnLogout_clicked(self):
        self.api.reset_auth()
        self.ui.btnLogout.hide()
        self.ui.lblLoginStatus.hide()
        self.ui.btnLogin.show()
        self.ui.widgetServices.hide()
        self.ui.tabDatabases.clear()
        self.ui.lblDbSize.setText("")
        self.ui.lblDbSizeUpload.setText("")
        self.ui.cbUploadDatabase.clear()
        self.ui.widgetDatabases.setEnabled(False)
        self.activate_upload_button()

    def refresh_databases(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        if self.clouddb:
            db_list = self.api.read_databases()
            if self.show_api_error(db_list):
                QApplication.restoreOverrideCursor()
                return
            self.db_connections = DbConnections()
            for db in db_list:
                # db example:
                # {"host":"spacialdb.com","connection_string":"postgres://sekpjr_jpyled:d787b609@spacialdb.com:9999/sekpjr_jpyled","name":"sekpjr_jpyled","username":"sekpjr_jpyled","port":9999,"password":"d787b609"}
                self.db_connections.add_from_json(db)

            self.ui.tabDatabases.clear()
            self.ui.btnDbDelete.setEnabled(False)
            self.ui.cbUploadDatabase.clear()
            self.ui.cbUploadDatabase.setEditable(True)
            self.ui.cbUploadDatabase.lineEdit().setReadOnly(True)
            if self.db_connections.count() == 0:
                self.ui.cbUploadDatabase.setEditText(self.tr("No databases"))
            else:
                for name, db in self.db_connections.iteritems():
                    it = QListWidgetItem(name)
                    it.setToolTip(db.description())
                    self.ui.tabDatabases.addItem(it)
                    self.ui.cbUploadDatabase.addItem(name)
                if self.ui.cbUploadDatabase.count() > 1:
                    # Display the "Select database" text if more than one db is available
                    self.ui.cbUploadDatabase.setCurrentIndex(-1)
                    self.ui.cbUploadDatabase.setEditText(self.tr("Select database"))
            self.db_connections.refresh(self.user)

        self.db_size(self.db_connections)
        QApplication.restoreOverrideCursor()

    def api_url(self):
        return unicode(self.ui.editServer.text())

    def update_urls(self):
        self.update_url(self.ui.lblWebmap, self.api_url(),
                        'http://', u'{0}/{1}'.format(self.user, self.map()))
        if self.clouddb:
            self.update_url(
                self.ui.lblMobileMap, self.api_url(),
                'http://m.', u'{0}/{1}'.format(self.user, self.map()))
            self.update_url(
                self.ui.lblWMS, self.api_url(),
                'http://wms.', u'{0}/{1}'.format(self.user, self.map()))
        else:
            self.update_url(self.ui.lblMobileMap, self.api_url(
            ), 'http://', u'{0}/{1}/mobile'.format(self.user, self.map()))
            self.update_url(self.ui.lblWMS, self.api_url(
            ), 'http://', u'{0}/{1}/wms'.format(self.user, self.map()))
        self.update_url(self.ui.lblMaps, self.api_url(), 'http://', 'maps')
        self.ui.widgetServices.show()

    def update_url(self, label, api_url, prefix, path):
        base_url = string.replace(api_url, 'https://api.', prefix)
        url = u'{0}/{1}'.format(base_url, path)
        text = re.sub(r'http[^"]+', url, unicode(label.text()))
        label.setText(text)

    def read_maps(self):
        #map = self.api.read_map("1")
        if self.check_login():
            self.api.read_maps()

    def check_project_saved(self):
        cancel = False
        project = QgsProject.instance()
        fname = unicode(project.fileName())
        if project.isDirty() or fname == '':
            msgBox = QMessageBox()
            msgBox.setText(self.tr("The project has been modified."))
            msgBox.setInformativeText(
                self.tr("Do you want to save your changes?"))
            if not fname:
                msgBox.setStandardButtons(
                    QMessageBox.Save | QMessageBox.Cancel)
            else:
                msgBox.setStandardButtons(
                    QMessageBox.Save | QMessageBox.Ignore | QMessageBox.Cancel)
            msgBox.setDefaultButton(QMessageBox.Save)
            ret = msgBox.exec_()
            if ret == QMessageBox.Save:
                if not fname:
                    project.setFileName(
                        QFileDialog.getSaveFileName(
                            self, "Save Project", "",
                            "QGIS Project Files  (*.qgs)"))
                if not unicode(project.fileName()):
                    cancel = True
                else:
                    project.write()
            elif ret == QMessageBox.Cancel:
                cancel = True
        return cancel

    def publish_map(self):
        cancel = self.check_project_saved()
        if cancel:
            self.statusBar().showMessage(self.tr("Cancelled"))
            return
        if self.check_login() and self.check_layers():
            self.statusBar().showMessage(self.tr("Publishing map"))
            try:
                fullExtent = self.iface.mapCanvas().fullExtent()
                config = {
                    'fullExtent': {
                        'xmin': fullExtent.xMinimum(),
                        'ymin': fullExtent.yMinimum(),
                        'xmax': fullExtent.xMaximum(),
                        'ymax': fullExtent.yMaximum()
                        #},
                        # 'svgPaths': QgsApplication.svgPaths() #For resolving absolute symbol paths in print composer
                    }
                }
                fname = unicode(QgsProject.instance().fileName())
                map = self.api.create_map(self.map(), fname, config)['map']
                self.show_api_error(map)
                if map['config']['missingSvgSymbols']:
                    self.publish_symbols(map['config']['missingSvgSymbols'])
                self.update_urls()
                self._push_message(self.tr("QGIS Cloud"), self.tr(
                    "Map successfully published"), level=0, duration=2)
                self.statusBar().showMessage(
                    self.tr("Map successfully published"))
            except Exception as e:
                self.statusBar().showMessage("")
                ErrorReportDialog(self.tr("Error uploading project"), self.tr("An error occured."), str(e) + "\n" + traceback.format_exc(), self.user, self).exec_()

    def publish_symbols(self, missingSvgSymbols):
        self.statusBar().showMessage(self.tr("Uploading SVG symbols"))
        search_paths = QgsApplication.svgPaths()
        if hasattr(QgsProject.instance(), 'homePath'):
            search_paths += [QgsProject.instance().homePath()]
        # Search and upload symbol files
        for sym in missingSvgSymbols:
            # Absolute custom path
            if os.path.isfile(sym):
                self.api.create_graphic(sym, sym)
            else:
                for path in search_paths:
                    fullpath = os.path.join(unicode(path), sym)
                    if os.path.isfile(fullpath):
                        self.api.create_graphic(sym, fullpath)
        self.statusBar().showMessage("")

    def reset_load_data(self):
        self.update_local_data_sources([])
        self.ui.btnUploadData.setEnabled(False)

    def remove_layer(self, layer_id):
        if self.do_update_local_data_sources:
            # skip layer if layer will be removed
            self.update_local_layers(layer_id)
            self.activate_upload_button()

    def add_layer(self):
        if self.do_update_local_data_sources:
            self.update_local_layers()
            self.activate_upload_button()

    def update_local_layers(self, skip_layer_id=None):
        local_layers, unsupported_layers = self.local_data_sources.local_layers(
            skip_layer_id)
        try:
            self.update_local_data_sources(local_layers)
        except Exception as e:
            ErrorReportDialog(self.tr("Error checking local data sources"), self.tr("An error occured."), str(e) + "\n" + traceback.format_exc(), self.user, self).exec_()

        return local_layers, unsupported_layers

    def check_layers(self):
        local_layers, unsupported_layers = self.update_local_layers()
        if (local_layers and self.clouddb) or unsupported_layers:
            message = ""

            if local_layers:
                title = self.tr("Local layers found")
                message += self.tr(
                    "Some layers are using local data. You can upload local layers to your cloud database in the 'Upload Data' tab.\n\n")

            if unsupported_layers:
                title = self.tr("Unsupported layers found")
                message += self.tr(
                    "Raster, plugin or geometryless layers are not supported:\n\n")
                layer_types = ["No geometry", "Raster", "Plugin"]
                for layer in sorted(unsupported_layers, key=lambda layer: layer.name()):
                    message += self.tr_uni("  -  %s (%s)\n") % (
                        layer.name(), layer_types[layer.type()])
                message += self.tr(
                    "\nPlease remove or replace above layers before publishing your map.\n")
                message += self.tr(
                    "For raster data you can use public WMS layers or the OpenLayers Plugin.")

            QMessageBox.information(self, title, message)

            self.refresh_databases()
            self.ui.tabWidget.setCurrentWidget(self.ui.uploadTab)
            return False

        return True

    def update_local_data_sources(self, local_layers):
        # update table names lookup
        self.update_data_sources_table_names()

        self.local_data_sources.update_local_data_sources(local_layers)

        # update GUI
        while self.ui.tblLocalLayers.rowCount() > 0:
            self.ui.tblLocalLayers.removeRow(0)

        for data_source, layers in self.local_data_sources.iteritems():
            layer_names = []
            for layer in layers:
                layer_names.append(unicode(layer.name()))
            layers_item = QTableWidgetItem(", ".join(layer_names))
            layers_item.setToolTip("\n".join(layer_names))
            data_source_item = QTableWidgetItem(data_source)
            data_source_item.setToolTip(data_source)
            # find a better table name if there are multiple layers with same
            # data source?
            table_name = layers[0].name()
            if data_source in self.data_sources_table_names:
                # use current table name if available to keep changes by user
                table_name = self.data_sources_table_names[data_source]
            table_name_item = QTableWidgetItem(
                QgisCloudPluginDialog.launder_pg_name(table_name))
            wkbType = layers[0].wkbType()
            if wkbType not in self.GEOMETRY_TYPES:
                QMessageBox.warning(self.iface.mainWindow(), self.tr("Unsupported geometry type"), pystring(self.tr(
                    "Unsupported geometry type '{type}' in layer '{layer}'")).format(type=self.__wkbTypeString(wkbType), layer=layers[0].name()))
                continue
            geometry_type_item = QTableWidgetItem(self.GEOMETRY_TYPES[wkbType])
            if layers[0].providerType() == "ogr":
                geometry_type_item.setToolTip(
                    self.tr("Note: OGR features will be converted to MULTI-type"))
            srid_item = QTableWidgetItem(layers[0].crs().authid())

            row = self.ui.tblLocalLayers.rowCount()
            self.ui.tblLocalLayers.insertRow(row)
            self.ui.tblLocalLayers.setItem(
                row, self.COLUMN_LAYERS, layers_item)
            self.ui.tblLocalLayers.setItem(
                row, self.COLUMN_DATA_SOURCE, data_source_item)
            self.ui.tblLocalLayers.setItem(
                row, self.COLUMN_TABLE_NAME, table_name_item)
            self.ui.tblLocalLayers.setItem(
                row, self.COLUMN_GEOMETRY_TYPE, geometry_type_item)
            self.ui.tblLocalLayers.setItem(row, self.COLUMN_SRID, srid_item)

        if self.local_data_sources.count() > 0:
            self.ui.tblLocalLayers.resizeColumnsToContents()
            self.ui.tblLocalLayers.setColumnWidth(self.COLUMN_LAYERS, 100)
            self.ui.tblLocalLayers.setColumnWidth(self.COLUMN_DATA_SOURCE, 100)
            self.ui.tblLocalLayers.sortItems(self.COLUMN_DATA_SOURCE)
            self.ui.tblLocalLayers.setSortingEnabled(False)
        else:
            self.ui.btnUploadData.setEnabled(False)

        self.statusBar().showMessage(self.tr("Updated local data sources"))

    def __wkbTypeString(self, wkbType):
        if wkbType == QGis.WKBUnknown:
            return "WKBUnknown"
        elif wkbType == QGis.WKBPoint:
            return "WKBPoint"
        elif wkbType == QGis.WKBLineString:
            return "WKBLineString"
        elif wkbType == QGis.WKBMultiLineString:
            return "WKBMultiLineString"
        elif wkbType == QGis.WKBPolygon:
            return "WKBPolygon"
        elif wkbType == QGis.WKBMultiPoint:
            return "WKBMultiPoint"
        elif wkbType == QGis.WKBMultiPolygon:
            return "WKBMultiPolygon"
        elif wkbType == QGis.WKBNoGeometry:
            return "WKBNoGeometry"
        elif wkbType == QGis.WKBPoint25D:
            return "WKBPoint25D"
        elif wkbType == QGis.WKBLineString25D:
            return "WKBLineString25D"
        elif wkbType == QGis.WKBPolygon25D:
            return "WKBPolygon25D"
        elif wkbType == QGis.WKBMultiPoint25D:
            return "WKBMultiPoint25D"
        elif wkbType == QGis.WKBMultiLineString25D:
            return "WKBMultiLineString25D"
        elif wkbType == QGis.WKBMultiPolygon25D:
            return "WKBMultiPolygon25D"
        return self.tr("Unknown type")

    @staticmethod
    def launder_pg_name(name):
        # OGRPGDataSource::LaunderName
        # return re.sub(r"[#'-]", '_', unicode(name).lower())
        input_string = unicode(name).lower().encode('ascii', 'replace')
        return re.compile("\W+", re.UNICODE).sub("_", input_string)

    def refresh_local_data_sources(self):
        self.do_update_local_data_sources = True
        self.update_local_layers()
        self.activate_upload_button()

    def update_data_sources_table_names(self):
        if self.local_data_sources.count() == 0:
            self.data_sources_table_names.clear()
        else:
            # remove table names without data sources
            keys_to_remove = []
            for key in self.data_sources_table_names.iterkeys():
                if self.local_data_sources.layers(key) is None:
                    keys_to_remove.append(key)

            for key in keys_to_remove:
                del self.data_sources_table_names[key]

            # update table names
            for row in range(0, self.ui.tblLocalLayers.rowCount()):
                data_source = unicode(
                    self.ui.tblLocalLayers.item(row, self.COLUMN_DATA_SOURCE).text())
                table_name = unicode(
                    self.ui.tblLocalLayers.item(row, self.COLUMN_TABLE_NAME).text())
                self.data_sources_table_names[data_source] = table_name

    def activate_upload_button(self):
        self.ui.btnUploadData.setEnabled(self.local_data_sources.count() > 0)

    def upload_data(self):
        if self.check_login():
            if self.local_data_sources.count() == 0:
                return

            if self.db_connections.count() == 0:
                QMessageBox.warning(self, self.tr("No database available"), self.tr("Please create a database in the 'Account' tab."))
                return

            if not self.ui.cbUploadDatabase.currentIndex() >= 0:
                QMessageBox.warning(self, self.tr("No database selected"), self.tr("Please select a database to upload data."))
                return

            db_name = self.ui.cbUploadDatabase.currentText()

            if not self.db_connections.isPortOpen(db_name):
                uri = self.db_connections.cloud_layer_uri(db_name, "", "")
                host = str(uri.host())
                port = uri.port()
                QMessageBox.critical(self, self.tr("Network Error"),
                                     self.tr("Could not connect to database server ({0}) on port {1}. Please contact your system administrator or internet provider".format(host, port)))
                return

            # disable update of local data sources during upload, as there are
            # temporary layers added and removed
            self.do_update_local_data_sources = False
            self.statusBar().showMessage(self.tr("Uploading data..."))
            self.setCursor(Qt.WaitCursor)
            self.ui.btnUploadData.hide()
            self.ui.spinner.start()
            self.ui.progressWidget.show()

            # Map<data_source, {table: table, layers: layers}>
            data_sources_items = {}
            for row in range(0, self.ui.tblLocalLayers.rowCount()):
                data_source = unicode(
                    self.ui.tblLocalLayers.item(
                        row, self.COLUMN_DATA_SOURCE).text())
                layers = self.local_data_sources.layers(data_source)
                if layers is not None:
                    table_name = unicode(
                        self.ui.tblLocalLayers.item(
                            row, self.COLUMN_TABLE_NAME).text())
                    data_sources_items[data_source] = {
                        'table': table_name, 'layers': layers}

            login_info = self.api.check_login(version_info=self._version_info())
            if login_info['plan'] == 'Free':
                maxSize = self.FREE_SIZE
            elif login_info['plan'] == 'Pro' or login_info['plan'] == 'Pro Beta':
                maxSize = self.PRO_SIZE
            elif login_info['plan'] == 'Enterprise/Reseller':
                maxSize = self.RESELLER_SIZE

            try:
                upload_count = self.data_upload.upload(
                    self.db_connections.db(db_name), data_sources_items, maxSize)
            except Exception as e:
                ErrorReportDialog(self.tr("Upload error"), self.tr("The data upload failed."), str(e) + "\n" + traceback.format_exc(), self.user, self).exec_()
                upload_count = 0

            self.ui.spinner.stop()
            self.ui.progressWidget.hide()
            self.ui.btnUploadData.show()
            self.unsetCursor()
            self.statusBar().showMessage("")
            self.do_update_local_data_sources = True
            # Refresh used space after upload
            self.db_size(self.db_connections)

            if upload_count > 0:
                self.update_local_layers()

                # Switch to map tab
                self.ui.tabWidget.setCurrentWidget(self.ui.mapTab)

                # show save project dialog
                msgBox = QMessageBox()
                msgBox.setWindowTitle(self.tr("QGIS Cloud"))
                msgBox.setText(self.tr("The project is ready for publishing."))
                msgBox.setInformativeText(
                    self.tr("Do you want to save your changes?"))
                msgBox.setStandardButtons(
                    QMessageBox.Save | QMessageBox.Cancel)
                msgBox.setDefaultButton(QMessageBox.Save)
                ret = msgBox.exec_()
                if ret == QMessageBox.Save:
                    self.iface.actionSaveProjectAs().trigger()

    def _push_message(self, title, text, level=0, duration=0):
        # QGIS >= 2.0
        if hasattr(self.iface, 'messageBar') and hasattr(self.iface.messageBar(), 'pushMessage'):
            self.iface.messageBar().pushMessage(title, text, level, duration)
        else:
            QMessageBox.information(self, title, text)

    def show_api_error(self, result):
        if 'error' in result:
            QMessageBox.critical(
                self, self.tr("QGIS Cloud Error"), "%s" % result['error'])
            self.statusBar().showMessage(self.tr("Error"))
            return True
        else:
            return False

    def tr_uni(self, str):
        return unicode(self.tr(str))

    def db_size(self,  db_connections):
        usedSpace = 0
        for db in db_connections._dbs.keys():
            try:
                conn = db_connections.db(db).psycopg_connection()
            except:
                continue
            cursor = conn.cursor()
            sql = "SELECT pg_database_size('" + str(db) + "')"
            cursor.execute(sql)
            usedSpace += int(cursor.fetchone()[0])

        # Used space in MB
        usedSpace /= 1024 * 1024

        login_info = self.api.check_login(
            version_info=self._version_info())
        if login_info['plan'] == 'Free':
            maxSize = self.FREE_SIZE
        elif login_info['plan'] == 'Pro' or login_info['plan'] == 'Pro Beta':
            maxSize = self.PRO_SIZE
        elif login_info['plan'] == 'Enterprise/Reseller':
            maxSize = self.RESELLER_SIZE

        lblPalette = QPalette(self.ui.lblDbSize.palette())
        usage = usedSpace / float(maxSize)

        if usage < 0.8:
            bg_color = QColor(255, 0, 0, 0)
        elif usage >= 0.8 and usage < 1:
            bg_color = QColor(255, 0, 0, 100)
        elif usage >= 1:
            bg_color = QColor(255, 0, 0, 255)

        lblPalette.setColor(QPalette.Window, QColor(bg_color))

        self.ui.lblDbSize.setAutoFillBackground(True)
        self.ui.lblDbSize.setPalette(lblPalette)
        self.ui.lblDbSize.setText(
            self.tr("Used DB Storage: ") + "%d / %d MB" % (usedSpace, maxSize))

        self.ui.lblDbSizeUpload.setAutoFillBackground(True)
        self.ui.lblDbSizeUpload.setPalette(lblPalette)
        self.ui.lblDbSizeUpload.setText(
            self.tr("Used DB Storage: ") + "%d / %d MB" % (usedSpace, maxSize))
