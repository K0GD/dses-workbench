#!/usr/bin/env python3
# -*- coding: utf-8 -*-

#
# SPDX-License-Identifier: GPL-3.0
#
# GNU Radio Python Flow Graph
# Title: B210 Spectrum Analyzer
# Description: Simple spectrum analyzer for the Ettus USRP B210
# GNU Radio version: 3.10.12.0

from PyQt5 import Qt
from gnuradio import qtgui
from PyQt5 import QtCore
from PyQt5.QtCore import QObject, pyqtSlot
from gnuradio import blocks
import numpy as np
from gnuradio import eng_notation
from gnuradio import gr
from gnuradio.filter import firdes
from gnuradio.fft import window
import sys
import signal
from PyQt5 import Qt
from argparse import ArgumentParser
from gnuradio.eng_arg import eng_float, intx
from gnuradio import uhd
import time
import foo
import sip
import threading
import os
from pathlib import Path



class b210_spectrum_analyzer(gr.top_block, Qt.QWidget):

    def __init__(self):
        gr.top_block.__init__(self, "B210 Spectrum Analyzer", catch_exceptions=True)
        Qt.QWidget.__init__(self)
        self.setWindowTitle("B210 Spectrum Analyzer")
        qtgui.util.check_set_qss()
        try:
            self.setWindowIcon(Qt.QIcon.fromTheme('gnuradio-grc'))
        except BaseException as exc:
            print(f"Qt GUI: Could not set Icon: {str(exc)}", file=sys.stderr)
        self.main_layout = Qt.QHBoxLayout(self)
        self.main_layout.setContentsMargins(4, 4, 4, 4)
        self.main_layout.setSpacing(4)

        self.plots_splitter = Qt.QSplitter(QtCore.Qt.Vertical)
        self.plots_splitter.setChildrenCollapsible(False)
        self.main_layout.addWidget(self.plots_splitter, 1)

        self.sidebar = Qt.QWidget()
        self.sidebar.setMinimumWidth(280)
        self.sidebar.setMaximumWidth(360)
        self.sidebar_layout = Qt.QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.addWidget(self.sidebar, 0)

        self._tuning_group = Qt.QGroupBox("Tuning")
        self._tuning_group_layout = Qt.QVBoxLayout(self._tuning_group)
        self.sidebar_layout.addWidget(self._tuning_group)

        self._rx_group = Qt.QGroupBox("RX")
        self._rx_group_layout = Qt.QVBoxLayout(self._rx_group)
        self.sidebar_layout.addWidget(self._rx_group)

        self._record_group = Qt.QGroupBox("Recording")
        self._record_group_layout = Qt.QVBoxLayout(self._record_group)
        self.sidebar_layout.addWidget(self._record_group)

        self.sidebar_layout.addStretch(1)

        self.settings = Qt.QSettings("gnuradio/flowgraphs", "b210_spectrum_analyzer")

        default_recording_dir = str(Path.home() / "Documents" / "B210_Recordings")
        self.recording_dir = self.settings.value("recording_dir", default_recording_dir, type=str)
        os.makedirs(self.recording_dir, exist_ok=True)

        self._recording_dir_button = Qt.QPushButton("Folder: " + self._elided_dir())
        self._recording_dir_button.setToolTip(self.recording_dir)
        self._recording_dir_button.clicked.connect(self._on_change_recording_dir)
        self._record_group_layout.addWidget(self._recording_dir_button)

        self.resize(1280, 780)
        try:
            geometry = self.settings.value("geometry")
            if geometry:
                self.restoreGeometry(geometry)
        except BaseException as exc:
            print(f"Qt GUI: Could not restore geometry: {str(exc)}", file=sys.stderr)
        self.flowgraph_started = threading.Event()

        ##################################################
        # Variables
        ##################################################
        self.freq_preset = freq_preset = 408e6
        self.freq_offset_0 = freq_offset_0 = 0
        self.freq_offset = freq_offset = 0
        self.freq_manual = freq_manual = 100e6
        self.samp_rate = samp_rate = 20e6
        self.record = record = 0
        self.gain = gain = 40
        self.center_freq = center_freq = (freq_manual if freq_preset == 0 else freq_preset) + freq_offset + freq_offset_0

        ##################################################
        # Blocks
        ##################################################

        # Create the options list
        self._samp_rate_options = [1000000.0, 2000000.0, 4000000.0, 5000000.0, 8000000.0, 10000000.0, 16000000.0, 20000000.0, 25000000.0]
        # Create the labels list
        self._samp_rate_labels = ['1 MHz', '2 MHz', '4 MHz', '5 MHz', '8 MHz', '10 MHz', '16 MHz', '20 MHz', '25 MHz']
        # Create the combo box
        self._samp_rate_tool_bar = Qt.QToolBar(self)
        self._samp_rate_tool_bar.addWidget(Qt.QLabel("Sample Rate" + ": "))
        self._samp_rate_combo_box = Qt.QComboBox()
        self._samp_rate_tool_bar.addWidget(self._samp_rate_combo_box)
        for _label in self._samp_rate_labels: self._samp_rate_combo_box.addItem(_label)
        self._samp_rate_callback = lambda i: Qt.QMetaObject.invokeMethod(self._samp_rate_combo_box, "setCurrentIndex", Qt.Q_ARG("int", self._samp_rate_options.index(i)))
        self._samp_rate_callback(self.samp_rate)
        self._samp_rate_combo_box.currentIndexChanged.connect(
            lambda i: self.set_samp_rate(self._samp_rate_options[i]))
        # Create the radio buttons
        self._rx_group_layout.addWidget(self._samp_rate_tool_bar)
        # Create the options list
        self._record_options = [0, 1]
        # Create the labels list
        self._record_labels = ['Stopped', 'Recording']
        # Create the combo box
        self._record_tool_bar = Qt.QToolBar(self)
        self._record_tool_bar.addWidget(Qt.QLabel("Record" + ": "))
        self._record_combo_box = Qt.QComboBox()
        self._record_tool_bar.addWidget(self._record_combo_box)
        for _label in self._record_labels: self._record_combo_box.addItem(_label)
        self._record_callback = lambda i: Qt.QMetaObject.invokeMethod(self._record_combo_box, "setCurrentIndex", Qt.Q_ARG("int", self._record_options.index(i)))
        self._record_callback(self.record)
        self._record_combo_box.currentIndexChanged.connect(
            lambda i: self.set_record(self._record_options[i]))
        # Create the radio buttons
        self._record_group_layout.addWidget(self._record_tool_bar)
        self._gain_range = qtgui.Range(0, 76, 1, 40, 200)
        self._gain_win = qtgui.RangeWidget(self._gain_range, self.set_gain, "RX Gain (dB)", "counter_slider", float, QtCore.Qt.Horizontal)
        self._rx_group_layout.addWidget(self._gain_win)
        self.uhd_usrp_source_0 = uhd.usrp_source(
            ",".join(('serial=3273A91', '')),
            uhd.stream_args(
                cpu_format="fc32",
                args='recv_frame_size=8192,num_recv_frames=1024',
                channels=list(range(0,1)),
            ),
        )
        self.uhd_usrp_source_0.set_samp_rate(samp_rate)
        self.uhd_usrp_source_0.set_time_unknown_pps(uhd.time_spec(0))

        self.uhd_usrp_source_0.set_center_freq(center_freq, 0)
        self.uhd_usrp_source_0.set_antenna("RX2", 0)
        self.uhd_usrp_source_0.set_gain(gain, 0)
        self.qtgui_waterfall_sink_x_0 = qtgui.waterfall_sink_c(
            1024, #size
            window.WIN_BLACKMAN_hARRIS, #wintype
            center_freq, #fc
            samp_rate, #bw
            "Waterfall", #name
            1, #number of inputs
            None # parent
        )
        self.qtgui_waterfall_sink_x_0.set_update_time(0.10)
        self.qtgui_waterfall_sink_x_0.enable_grid(False)
        self.qtgui_waterfall_sink_x_0.enable_axis_labels(True)



        labels = ['', '', '', '', '',
                  '', '', '', '', '']
        colors = [0, 0, 0, 0, 0,
                  0, 0, 0, 0, 0]
        alphas = [1.0, 1.0, 1.0, 1.0, 1.0,
                  1.0, 1.0, 1.0, 1.0, 1.0]

        for i in range(1):
            if len(labels[i]) == 0:
                self.qtgui_waterfall_sink_x_0.set_line_label(i, "Data {0}".format(i))
            else:
                self.qtgui_waterfall_sink_x_0.set_line_label(i, labels[i])
            self.qtgui_waterfall_sink_x_0.set_color_map(i, colors[i])
            self.qtgui_waterfall_sink_x_0.set_line_alpha(i, alphas[i])

        self.qtgui_waterfall_sink_x_0.set_intensity_range(-140, 10)

        self._qtgui_waterfall_sink_x_0_win = sip.wrapinstance(self.qtgui_waterfall_sink_x_0.qwidget(), Qt.QWidget)

        self.plots_splitter.addWidget(self._qtgui_waterfall_sink_x_0_win)
        self.qtgui_freq_sink_x_0 = qtgui.freq_sink_c(
            1024, #size
            window.WIN_BLACKMAN_hARRIS, #wintype
            center_freq, #fc
            samp_rate, #bw
            "Spectrum", #name
            1,
            None # parent
        )
        self.qtgui_freq_sink_x_0.set_update_time(0.10)
        self.qtgui_freq_sink_x_0.set_y_axis((-140), 10)
        self.qtgui_freq_sink_x_0.set_y_label('Relative Gain', 'dB')
        self.qtgui_freq_sink_x_0.set_trigger_mode(qtgui.TRIG_MODE_FREE, 0.0, 0, "")
        self.qtgui_freq_sink_x_0.enable_autoscale(False)
        self.qtgui_freq_sink_x_0.enable_grid(True)
        self.qtgui_freq_sink_x_0.set_fft_average(1.0)
        self.qtgui_freq_sink_x_0.enable_axis_labels(True)
        self.qtgui_freq_sink_x_0.enable_control_panel(False)
        self.qtgui_freq_sink_x_0.set_fft_window_normalized(False)



        labels = ['', '', '', '', '',
            '', '', '', '', '']
        widths = [1, 1, 1, 1, 1,
            1, 1, 1, 1, 1]
        colors = ["blue", "red", "green", "black", "cyan",
            "magenta", "yellow", "dark red", "dark green", "dark blue"]
        alphas = [1.0, 1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0, 1.0]

        for i in range(1):
            if len(labels[i]) == 0:
                self.qtgui_freq_sink_x_0.set_line_label(i, "Data {0}".format(i))
            else:
                self.qtgui_freq_sink_x_0.set_line_label(i, labels[i])
            self.qtgui_freq_sink_x_0.set_line_width(i, widths[i])
            self.qtgui_freq_sink_x_0.set_line_color(i, colors[i])
            self.qtgui_freq_sink_x_0.set_line_alpha(i, alphas[i])

        self._qtgui_freq_sink_x_0_win = sip.wrapinstance(self.qtgui_freq_sink_x_0.qwidget(), Qt.QWidget)
        self.plots_splitter.insertWidget(0, self._qtgui_freq_sink_x_0_win)
        self.plots_splitter.setStretchFactor(0, 1)
        self.plots_splitter.setStretchFactor(1, 1)
        self.plots_splitter.setSizes([400, 400])
        # Create the options list
        self._freq_preset_options = [408000000.0, 680500000.0, 1299500000.0, 1422000000.0, 1666000000.0, 2304000000.0, 0]
        # Create the labels list
        self._freq_preset_labels = ['408 MHz', '680.5 MHz', '1299.5 MHz', '1422 MHz (HI)', '1666 MHz (OH)', '2304 MHz', 'Manual']
        # Create the combo box
        # Create the radio buttons
        self._freq_preset_group_box = Qt.QGroupBox("Pulsar Band" + ": ")
        self._freq_preset_box = Qt.QVBoxLayout()
        class variable_chooser_button_group(Qt.QButtonGroup):
            def __init__(self, parent=None):
                Qt.QButtonGroup.__init__(self, parent)
            @pyqtSlot(int)
            def updateButtonChecked(self, button_id):
                self.button(button_id).setChecked(True)
        self._freq_preset_button_group = variable_chooser_button_group()
        self._freq_preset_group_box.setLayout(self._freq_preset_box)
        for i, _label in enumerate(self._freq_preset_labels):
            radio_button = Qt.QRadioButton(_label)
            self._freq_preset_box.addWidget(radio_button)
            self._freq_preset_button_group.addButton(radio_button, i)
        self._freq_preset_callback = lambda i: Qt.QMetaObject.invokeMethod(self._freq_preset_button_group, "updateButtonChecked", Qt.Q_ARG("int", self._freq_preset_options.index(i)))
        self._freq_preset_callback(self.freq_preset)
        self._freq_preset_button_group.buttonClicked[int].connect(
            lambda i: self.set_freq_preset(self._freq_preset_options[i]))
        self._tuning_group_layout.addWidget(self._freq_preset_group_box)
        self._freq_offset_0_range = qtgui.Range(-100e6, 100e6, 100e3, 0, 200)
        self._freq_offset_0_win = qtgui.RangeWidget(self._freq_offset_0_range, self.set_freq_offset_0, "Coarse Tune (Hz)", "counter_slider", float, QtCore.Qt.Horizontal)
        self._tuning_group_layout.addWidget(self._freq_offset_0_win)
        self._freq_offset_range = qtgui.Range(-10e6, 10e6, 100e3, 0, 200)
        self._freq_offset_win = qtgui.RangeWidget(self._freq_offset_range, self.set_freq_offset, "Fine Tune (Hz)", "counter_slider", float, QtCore.Qt.Horizontal)
        self._tuning_group_layout.addWidget(self._freq_offset_win)
        self._freq_manual_tool_bar = Qt.QToolBar(self)
        self._freq_manual_tool_bar.addWidget(Qt.QLabel("Manual Frequency (Hz)" + ": "))
        self._freq_manual_line_edit = Qt.QLineEdit(str(self.freq_manual))
        self._freq_manual_tool_bar.addWidget(self._freq_manual_line_edit)
        self._freq_manual_line_edit.editingFinished.connect(
            lambda: self.set_freq_manual(eng_notation.str_to_num(str(self._freq_manual_line_edit.text()))))
        self._tuning_group_layout.addWidget(self._freq_manual_tool_bar)
        self.foo_valve_0 = foo.valve(item_size=gr.sizeof_gr_complex*1, open=bool(not record))
        self.blocks_sigmf_sink_minimal_0 = blocks.sigmf_sink_minimal(
            item_size=gr.sizeof_gr_complex,
            filename=os.path.join(self.recording_dir, 'DSES_Spectrum_Analyzer'),
            sample_rate=samp_rate,
            center_freq=center_freq,
            author='Rick',
            description='B210 capture, RX2 antenna',
            hw_info='Ettus USRP B210',
            is_complex=True)


        ##################################################
        # Connections
        ##################################################
        self.connect((self.foo_valve_0, 0), (self.blocks_sigmf_sink_minimal_0, 0))
        self.connect((self.uhd_usrp_source_0, 0), (self.foo_valve_0, 0))
        self.connect((self.uhd_usrp_source_0, 0), (self.qtgui_freq_sink_x_0, 0))
        self.connect((self.uhd_usrp_source_0, 0), (self.qtgui_waterfall_sink_x_0, 0))


    def closeEvent(self, event):
        self.settings = Qt.QSettings("gnuradio/flowgraphs", "b210_spectrum_analyzer")
        self.settings.setValue("geometry", self.saveGeometry())
        self.stop()
        self.wait()

        event.accept()

    def _elided_dir(self):
        d = self.recording_dir
        if len(d) > 32:
            return "..." + d[-29:]
        return d

    def _on_change_recording_dir(self):
        new_dir = Qt.QFileDialog.getExistingDirectory(
            self,
            "Choose recording folder",
            self.recording_dir,
        )
        if not new_dir:
            return
        self.recording_dir = new_dir
        self.settings.setValue("recording_dir", new_dir)
        self._recording_dir_button.setText("Folder: " + self._elided_dir())
        self._recording_dir_button.setToolTip(new_dir)
        Qt.QMessageBox.information(
            self,
            "Recording folder changed",
            "New folder will be used the next time the program is launched."
        )

    def get_freq_preset(self):
        return self.freq_preset

    def set_freq_preset(self, freq_preset):
        self.freq_preset = freq_preset
        self.set_center_freq((self.freq_manual if self.freq_preset == 0 else self.freq_preset) + self.freq_offset + self.freq_offset_0)
        self._freq_preset_callback(self.freq_preset)

    def get_freq_offset_0(self):
        return self.freq_offset_0

    def set_freq_offset_0(self, freq_offset_0):
        self.freq_offset_0 = freq_offset_0
        self.set_center_freq((self.freq_manual if self.freq_preset == 0 else self.freq_preset) + self.freq_offset + self.freq_offset_0)

    def get_freq_offset(self):
        return self.freq_offset

    def set_freq_offset(self, freq_offset):
        self.freq_offset = freq_offset
        self.set_center_freq((self.freq_manual if self.freq_preset == 0 else self.freq_preset) + self.freq_offset + self.freq_offset_0)

    def get_freq_manual(self):
        return self.freq_manual

    def set_freq_manual(self, freq_manual):
        self.freq_manual = freq_manual
        self.set_center_freq((self.freq_manual if self.freq_preset == 0 else self.freq_preset) + self.freq_offset + self.freq_offset_0)
        Qt.QMetaObject.invokeMethod(self._freq_manual_line_edit, "setText", Qt.Q_ARG("QString", eng_notation.num_to_str(self.freq_manual)))

    def get_samp_rate(self):
        return self.samp_rate

    def set_samp_rate(self, samp_rate):
        self.samp_rate = samp_rate
        self._samp_rate_callback(self.samp_rate)
        self.qtgui_freq_sink_x_0.set_frequency_range(self.center_freq, self.samp_rate)
        self.qtgui_waterfall_sink_x_0.set_frequency_range(self.center_freq, self.samp_rate)
        self.uhd_usrp_source_0.set_samp_rate(self.samp_rate)

    def get_record(self):
        return self.record

    def set_record(self, record):
        self.record = record
        self._record_callback(self.record)
        self.foo_valve_0.set_open(bool(not self.record))

    def get_gain(self):
        return self.gain

    def set_gain(self, gain):
        self.gain = gain
        self.uhd_usrp_source_0.set_gain(self.gain, 0)

    def get_center_freq(self):
        return self.center_freq

    def set_center_freq(self, center_freq):
        self.center_freq = center_freq
        self.qtgui_freq_sink_x_0.set_frequency_range(self.center_freq, self.samp_rate)
        self.qtgui_waterfall_sink_x_0.set_frequency_range(self.center_freq, self.samp_rate)
        self.uhd_usrp_source_0.set_center_freq(self.center_freq, 0)




def main(top_block_cls=b210_spectrum_analyzer, options=None):

    qapp = Qt.QApplication(sys.argv)

    tb = top_block_cls()

    tb.start()
    tb.flowgraph_started.set()

    tb.show()

    def sig_handler(sig=None, frame=None):
        tb.stop()
        tb.wait()

        Qt.QApplication.quit()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    timer = Qt.QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None)

    qapp.exec_()

if __name__ == '__main__':
    main()
