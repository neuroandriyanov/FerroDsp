"""FerroDSP Lab: native D415 + optical I/Q research console."""
import bootstrap
import argparse
import copy
import json
import queue
import sys
import time
from pathlib import Path
import cv2
import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore,QtGui,QtWidgets as W
from engine import Engine,LOCAL,RECORDINGS
from control_api import ControlAPI
from processing import CHANNELS
from recording import dump

pg.setConfigOptions(antialias=False,background='#101923',foreground='#b9c8d7')
COLORS=['#36cfbd','#f2bc67','#6eabff','#d694f2','#d6dc78','#ff8395','#78cfec','#d5bba2']
ORIENTATIONS=[
    'Не задана',
    'Плоскость образца параллельна плоскости катушки',
    'Плоскость образца перпендикулярна плоскости катушки',
    'Продольная ось образца параллельна плоскости катушки',
    'Продольная ось образца перпендикулярна плоскости катушки',
]

class OrientationDelegate(W.QStyledItemDelegate):
    def createEditor(self,parent,option,index):
        editor=W.QComboBox(parent);editor.setEditable(True);editor.addItems(ORIENTATIONS)
        editor.setToolTip('Ориентация относительно плоскости катушки. Для наклонного положения укажите угол.')
        return editor
    def setEditorData(self,editor,index):editor.setCurrentText(str(index.data() or ORIENTATIONS[0]))
    def setModelData(self,editor,model,index):model.setData(index,editor.currentText().strip(),QtCore.Qt.ItemDataRole.EditRole)

def button(text,name,callback):
    b=W.QPushButton(text);b.setObjectName(name);b.clicked.connect(callback);return b

def double(value,minimum,maximum,step=1,decimals=1):
    s=W.QDoubleSpinBox();s.setDecimals(decimals);s.setRange(minimum,maximum);s.setSingleStep(step);s.setValue(value);return s

class Preview(W.QWidget):
    point=QtCore.Signal(int,int)
    region=QtCore.Signal(list)
    def __init__(self):
        super().__init__();self.setObjectName('cameraPreview');self.setMinimumSize(480,360)
        self.image=None;self.mode='';self.start=None;self.end=None;self.target=QtCore.QRectF()
    def set_frame(self,bgr):
        rgb=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)
        self.image=QtGui.QImage(rgb.data,640,480,1920,QtGui.QImage.Format.Format_RGB888).copy();self.update()
    def paintEvent(self,event):
        p=QtGui.QPainter(self);p.fillRect(self.rect(),QtGui.QColor('#080f17'))
        width=min(self.width(),self.height()*4/3);height=width*3/4
        self.target=QtCore.QRectF((self.width()-width)/2,(self.height()-height)/2,width,height)
        if self.image:p.drawImage(self.target,self.image)
        else:
            p.setPen(QtGui.QColor('#7e93a8'));p.drawText(self.rect(),QtCore.Qt.AlignmentFlag.AlignCenter,'D415 · ожидание кадров\n640 × 480')
        if self.mode=='roi' and self.start and self.end:
            p.setPen(QtGui.QPen(QtGui.QColor('#36cfbd'),2));p.drawRect(QtCore.QRectF(self.start,self.end).normalized())
    def pixel(self,pos):
        if not self.target.contains(pos):return None
        return [min(639,max(0,int((pos.x()-self.target.x())*640/self.target.width()))),
                min(479,max(0,int((pos.y()-self.target.y())*480/self.target.height())))]
    def mousePressEvent(self,event):
        if event.button()==QtCore.Qt.MouseButton.LeftButton:
            self.start=event.position();self.end=self.start
    def mouseMoveEvent(self,event):
        if self.start:self.end=event.position();self.update()
    def mouseReleaseEvent(self,event):
        pos=self.pixel(event.position())
        if self.mode=='points' and pos:self.point.emit(*pos)
        elif self.mode=='roi' and self.start and pos:
            begin=self.pixel(self.start)
            if begin:
                x,y=min(begin[0],pos[0]),min(begin[1],pos[1])
                self.region.emit([x,y,abs(pos[0]-begin[0])+1,abs(pos[1]-begin[1])+1])
        self.start=None;self.end=None;self.update()

class CameraDialog(W.QDialog):
    def __init__(self,window):
        super().__init__(window);self.main=window;self.engine=window.engine
        self.setWindowTitle('Параметры D415 и измерения');self.resize(1120,740)
        layout=W.QVBoxLayout(self);tabs=W.QTabWidget();layout.addWidget(tabs)
        page=W.QWidget();form=W.QFormLayout(page);tabs.addTab(page,'Измерение и цвет')
        c=self.engine.config;self.fields={}
        specs=[('min_depth_m','Измерять от камеры: минимум, м',.05,10,.01,3),
               ('max_depth_m','Измерять от камеры: максимум, м',.05,10,.01,3),
               ('color_min_m','Палитра: ближняя граница, м',0,10,.01,3),
               ('color_max_m','Палитра: дальняя граница, м',0,10,.01,3),
               ('foreground_mm','Отличие от пустого фона, мм',1,200,1,1),
               ('distance_spike_mm','График расстояния: порог выбросов, мм',1,500,1,1),
               ('minimum_gap_mm','Исключить у плоскости катушки, мм',0,1000,1,1),
               ('maximum_gap_mm','Максимальный зазор до катушки, мм',1,10000,10,1),
               ('min_area_px','Минимальная связная область, пикс.',3,10000,1,0)]
        for key,label,lo,hi,step,dec in specs:
            field=double(c[key],lo,hi,step,dec);self.fields[key]=field;form.addRow(label,field)
        self.colormap=W.QComboBox();self.colormap.addItems(['Turbo','Jet','Viridis','Серый']);self.colormap.setCurrentText(c['colormap']);form.addRow('Цветовая шкала глубины',self.colormap)
        note=W.QLabel('Диапазоны здесь — программные ограничения, а не гарантия точности D415.\nНулевая/недостоверная глубина исключается. Измеряется видимая поверхность.');note.setWordWrap(True);form.addRow(note)
        form.addRow(button('Применить измерение и цвет','applyMeasurement',self.apply))
        form.addRow(button('Восстановить привязку — камера и катушка не перемещались','restoreGeometry',lambda:window.guard(self.engine.restore_geometry)))
        page2=W.QWidget();vl=W.QVBoxLayout(page2);tabs.addTab(page2,'Таблица параметров камеры')
        self.table=W.QTableWidget(0,8);self.table.setHorizontalHeaderLabels(['Сенсор','Параметр','Значение','Мин.','Макс.','Шаг','По умолч.','Доступ'])
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.ResizeToContents);vl.addWidget(self.table)
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows)
        hl=W.QHBoxLayout();self.value=double(0,-1e9,1e9,1,6);hl.addWidget(self.value)
        hl.addWidget(button('Применить выбранный параметр','applyCameraOption',self.apply_option))
        hl.addWidget(button('Обновить','refreshCameraOptions',self.refresh));vl.addLayout(hl)
        self.description=W.QLabel();self.description.setWordWrap(True);vl.addWidget(self.description)
        self.table.itemSelectionChanged.connect(self.select_option);self.refresh()
        layout.addWidget(button('Закрыть','closeCameraSettings',self.close))
    def refresh(self):
        self.rows=copy.deepcopy(self.engine.camera_options);self.table.setRowCount(len(self.rows))
        for i,r in enumerate(self.rows):
            vals=[r['sensor_name'],r['name'],r['value'],r['minimum'],r['maximum'],r['step'],r['default'],'чтение' if r['readonly'] else 'изменение']
            for j,v in enumerate(vals):
                text=f'{v:.7g}' if isinstance(v,float) else str(v)
                cell=W.QTableWidgetItem(text);cell.setToolTip(str(v));cell.setFlags(cell.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable);self.table.setItem(i,j,cell)
    def select_option(self):
        i=self.table.currentRow()
        if i<0:return
        r=self.rows[i];self.value.setRange(r['minimum'],r['maximum']);self.value.setSingleStep(max(r['step'],.000001));self.value.setValue(r['value'])
        self.description.setText(r['description']);self.value.setEnabled(not r['readonly'])
    def apply_option(self):
        i=self.table.currentRow()
        if i<0:return
        r=self.rows[i]
        self.main.guard(lambda:self.engine.set_camera_option(r['sensor'],r['option'],self.value.value()))
        QtCore.QTimer.singleShot(600,self.refresh)
    def apply(self):
        c={key:field.value() for key,field in self.fields.items()};c['min_area_px']=int(c['min_area_px']);c['colormap']=self.colormap.currentText()
        self.main.guard(lambda:self.engine.set_config(c))

class CaptureDialog(W.QDialog):
    def __init__(self,window):
        super().__init__(window);self.main=window;self.setWindowTitle('Настройки захвата');self.resize(700,440)
        form=W.QFormLayout(self);c=window.engine.config
        self.fps=W.QComboBox();self.fps.addItems(['30','15','6']);self.fps.setCurrentText(str(c['fps']))
        form.addRow('Глубина и цвет · 640×480 · кадр/с',self.fps)
        self.audio=W.QComboBox();self.audio.addItem('Автоматически: Sound Blaster G3 S/PDIF WASAPI',None)
        import sounddevice as sd
        hosts=sd.query_hostapis()
        for i,d in enumerate(sd.query_devices()):
            if 'spdif' in d['name'].lower() and d['max_input_channels']>=2 and hosts[d['hostapi']]['name']=='Windows WASAPI':
                self.audio.addItem(f"{i}: {d['name']}",i)
        for i in range(self.audio.count()):
            if self.audio.itemData(i)==c['audio_index']:self.audio.setCurrentIndex(i)
        form.addRow('Оптический вход · 96 кГц / 24 бит',self.audio)
        self.serial=W.QLineEdit(c['camera_serial'] or '');self.serial.setPlaceholderText('Автоматически, если подключена одна D415');form.addRow('Серийный номер D415',self.serial)
        self.color=W.QCheckBox('Сохранять совмещённые цветные кадры (JPEG в HDF5)');self.color.setChecked(c['save_color']);form.addRow(self.color)
        self.video=W.QCheckBox('Создавать демонстрацию: предмет, камера и графики справа');self.video.setChecked(c['save_video']);form.addRow(self.video)
        self.demo_seconds=double(c['demo_seconds'],2,60,1,0);form.addRow('Окно графиков в демонстрации, с',self.demo_seconds)
        self.camera_offset=double(c['camera_time_offset_ms'],-2000,2000,1,2);form.addRow('Поправка времени камеры, мс',self.camera_offset)
        self.audio_offset=double(c['audio_time_offset_ms'],-2000,2000,1,2);form.addRow('Поправка времени S/PDIF, мс',self.audio_offset)
        self.disk=double(c['minimum_disk_gb'],.2,1000,.5,1);form.addRow('Остановить при остатке диска менее, ГБ',self.disk)
        note=W.QLabel('Анализ: общая шкала времени, глубина/XYZ, фазы, амплитуды, I/Q, PCM24 и кадры.\nДемонстрация MP4 формируется после остановки по сохранённым меткам.\nПоправки добавляются к времени источника; положительная сдвигает его позже.\nОставьте 0 до измерения физической задержки. Часы устройств независимы.');note.setWordWrap(True);form.addRow(note)
        form.addRow('Каталог опытов',W.QLabel(str(RECORDINGS)))
        form.addRow(button('Сохранить','saveCaptureSettings',self.apply))
    def apply(self):
        try:
            self.main.engine.set_config(dict(fps=int(self.fps.currentText()),audio_index=self.audio.currentData(),
                                            camera_serial=self.serial.text().strip() or None,save_color=self.color.isChecked(),
                                            save_video=self.video.isChecked(),minimum_disk_gb=self.disk.value(),
                                            demo_seconds=self.demo_seconds.value(),camera_time_offset_ms=self.camera_offset.value(),
                                            audio_time_offset_ms=self.audio_offset.value()))
            self.accept()
        except Exception as exc:self.main.show_error(exc)

QUANTITIES=['Δ фазы RX/TX, °','Фаза RX/TX, °','Амплитуда |Z|','I/Q','S/PDIF L/R']

class PlotDialog(W.QDialog):
    def __init__(self,window):
        super().__init__(window);self.main=window;self.setWindowTitle('Осциллограммы и масштаб');self.resize(640,530)
        form=W.QFormLayout(self);s=window.plot_settings
        self.top=W.QComboBox();self.top.addItems(QUANTITIES);self.top.setCurrentText(s['top'])
        self.bottom=W.QComboBox();self.bottom.addItems(QUANTITIES);self.bottom.setCurrentText(s['bottom'])
        form.addRow('Верхний график',self.top);form.addRow('Нижний график',self.bottom)
        group=W.QWidget();h=W.QHBoxLayout(group);self.channels=[]
        for i,label in enumerate(CHANNELS):
            b=W.QCheckBox(label);b.setChecked(i in s['channels']);h.addWidget(b);self.channels.append(b)
        form.addRow('Отображать каналы',group)
        self.seconds=double(s['seconds'],1,120,1,0);form.addRow('Общее окно сигналов и расстояния, с',self.seconds)
        self.raw_ms=double(s['raw_ms'],1,100,1,1);form.addRow('Окно сырого S/PDIF, мс',self.raw_ms)
        self.autos=[];self.lows=[];self.highs=[]
        for i,label in enumerate(['Верхний','Нижний']):
            a=W.QCheckBox('Автомасштаб Y');a.setChecked(s['auto'][i]);self.autos.append(a);form.addRow(label,a)
            row=W.QWidget();r=W.QHBoxLayout(row)
            lo=double(s['limits'][i][0],-1e6,1e6,.01,6);hi=double(s['limits'][i][1],-1e6,1e6,.01,6)
            self.lows.append(lo);self.highs.append(hi);r.addWidget(lo);r.addWidget(hi);form.addRow('Y минимум / максимум',row)
        self.distance_auto=W.QCheckBox('Автомасштаб Y');self.distance_auto.setChecked(s['distance_auto']);form.addRow('Расстояние',self.distance_auto)
        row=W.QWidget();r=W.QHBoxLayout(row)
        self.distance_lo=double(s['distance_limits'][0],0,10000,10,1);self.distance_hi=double(s['distance_limits'][1],0,10000,10,1)
        r.addWidget(self.distance_lo);r.addWidget(self.distance_hi);form.addRow('Расстояние: Y минимум / максимум, мм',row)
        form.addRow(W.QLabel('Пропуски показаны разрывами. Сырой S/PDIF — кодированный транспорт,\nа не четыре широкополосных АЦП. Масштаб не меняет записанные данные.'))
        form.addRow(button('Применить','applyPlotSettings',self.apply))
    def apply(self):
        if any(lo.value()>=hi.value() for lo,hi in zip(self.lows,self.highs)) or self.distance_lo.value()>=self.distance_hi.value():
            self.main.show_error('Минимум Y должен быть меньше максимума');return
        self.main.plot_settings=dict(top=self.top.currentText(),bottom=self.bottom.currentText(),
            channels=[i for i,c in enumerate(self.channels) if c.isChecked()],seconds=self.seconds.value(),raw_ms=self.raw_ms.value(),
            auto=[a.isChecked() for a in self.autos],limits=[[lo.value(),hi.value()] for lo,hi in zip(self.lows,self.highs)],
            distance_auto=self.distance_auto.isChecked(),distance_limits=[self.distance_lo.value(),self.distance_hi.value()])
        self.main.save_plot_settings();self.accept()

class MainWindow(W.QMainWindow):
    def __init__(self,autostart=False):
        super().__init__();self.setWindowTitle('FerroDSP Lab — D415 + S/PDIF');self.setObjectName('ferrodspLab')
        self.resize(1580,1000);self.setMinimumSize(1100,760)
        self.engine=Engine();self.api=ControlAPI(self.engine,LOCAL)
        self.baseline=None;self.dialogs=[];self.ui_error=None;self.last_frame_id=None
        self.close_when_done=False
        self.legend_state=[None,None]
        self.plot_settings=dict(top='Δ фазы RX/TX, °',bottom='Амплитуда |Z|',channels=[0,1,2,3],seconds=15,raw_ms=10,
                                auto=[True,True],limits=[[-1,1],[-.2,.2]],distance_auto=True,distance_limits=[0,700])
        if (LOCAL/'plots.json').exists():
            try:self.plot_settings.update(json.loads((LOCAL/'plots.json').read_text(encoding='utf-8')))
            except Exception:pass
        root=W.QWidget();self.setCentralWidget(root);layout=W.QVBoxLayout(root);layout.setSpacing(10)
        header=W.QHBoxLayout();brand=W.QLabel('FerroDSP  /  LAB');brand.setObjectName('brand');header.addWidget(brand)
        self.state_label=W.QLabel('Исследование · четыре синхронных I/Q');header.addWidget(self.state_label);header.addStretch()
        self.connect_btn=button('Подключить','connectDevices',lambda:self.guard(self.toggle_connection));header.addWidget(self.connect_btn)
        header.addWidget(button('Параметры камеры','cameraSettings',lambda:self.open_dialog(CameraDialog)))
        header.addWidget(button('Настройки захвата','captureSettings',lambda:self.open_dialog(CaptureDialog)));layout.addLayout(header)
        splitter=W.QSplitter(QtCore.Qt.Orientation.Horizontal);layout.addWidget(splitter,1)
        left=W.QWidget();l=W.QVBoxLayout(left);l.setContentsMargins(0,0,8,0)
        self.distance=W.QLabel('—  мм');self.distance.setObjectName('distance');l.addWidget(self.distance)
        self.measure_note=W.QLabel('Предмет → плоскость катушки · нужна калибровка');l.addWidget(self.measure_note)
        self.preview=Preview();l.addWidget(self.preview,1)
        self.preview.point.connect(lambda x,y:self.guard(lambda:self.add_point(x,y)))
        self.preview.region.connect(lambda roi:self.guard(lambda:self.set_roi(roi)))
        modes=W.QHBoxLayout();self.mode=W.QComboBox();self.mode.addItem('Наложение','overlay');self.mode.addItem('Цвет','color');self.mode.addItem('Глубина','depth')
        self.mode.setCurrentIndex(self.mode.findData(self.engine.config['view']));self.mode.currentIndexChanged.connect(self.display_settings)
        modes.addWidget(W.QLabel('Вид'));modes.addWidget(self.mode)
        self.alpha_color=W.QSlider(QtCore.Qt.Orientation.Horizontal);self.alpha_depth=W.QSlider(QtCore.Qt.Orientation.Horizontal)
        for slider,key,label in [(self.alpha_color,'alpha_color','Цвет'),(self.alpha_depth,'alpha_depth','Глубина')]:
            slider.setRange(0,100);slider.setValue(round(self.engine.config[key]*100));slider.setObjectName(key);slider.valueChanged.connect(self.display_settings)
            modes.addWidget(W.QLabel(label));modes.addWidget(slider)
        l.addLayout(modes)
        geom=W.QHBoxLayout();self.points_btn=button('Точки плоскости','selectPlanePoints',self.point_mode);geom.addWidget(self.points_btn)
        geom.addWidget(button('Принять плоскость','fitCoilPlane',lambda:self.guard(self.fit_plane)))
        geom.addWidget(button('Сброс точек','clearPlanePoints',lambda:self.guard(self.engine.clear_points)));l.addLayout(geom)
        geom2=W.QHBoxLayout();geom2.addWidget(button('Область измерения','selectROI',self.roi_mode))
        geom2.addWidget(button('Пустой фон','captureBackground',lambda:self.guard(self.engine.capture_background)))
        geom2.addWidget(button('Задать плоскость вручную','manualCoilPlane',self.manual_plane));l.addLayout(geom2)
        self.camera_status=W.QLabel('Камера отключена');self.camera_status.setWordWrap(True);l.addWidget(self.camera_status)
        splitter.addWidget(left)
        right=W.QWidget();r=W.QVBoxLayout(right);r.setContentsMargins(8,0,0,0)
        plots_header=W.QHBoxLayout();plots_header.addWidget(W.QLabel('СИГНАЛЫ  /  S/PDIF'));plots_header.addStretch()
        plots_header.addWidget(button('Графики и масштаб','plotSettings',lambda:self.open_dialog(PlotDialog)))
        plots_header.addWidget(button('Зафиксировать фон фазы','phaseBaseline',lambda:self.guard(self.phase_baseline)));r.addLayout(plots_header)
        self.plots=[];self.curves=[]
        for i in range(2):
            plot=pg.PlotWidget();plot.setObjectName(f'oscilloscope{i}');plot.showGrid(x=True,y=True,alpha=.15)
            plot.addLegend(offset=(10,10));plot.setLabel('bottom','Время','с');r.addWidget(plot,1)
            plot.getAxis('left').setWidth(64)
            self.plots.append(plot);self.curves.append([plot.plot(pen=pg.mkPen(COLORS[j],width=1.4),name=f'{j}') for j in range(8)])
        self.distance_plot=pg.PlotWidget();self.distance_plot.setObjectName('distanceChart')
        self.distance_plot.showGrid(x=True,y=True,alpha=.15);self.distance_plot.setLabel('bottom','Время','с')
        self.distance_plot.getAxis('left').setWidth(64)
        self.distance_plot.setTitle('Расстояние до катушки, мм · фильтр выбросов',size='11pt')
        self.distance_curve=self.distance_plot.plot(pen=pg.mkPen('#5ee1d1',width=1.6));r.addWidget(self.distance_plot,1)
        self.audio_status=W.QLabel('Оптический вход отключён');self.audio_status.setWordWrap(True);r.addWidget(self.audio_status)
        splitter.addWidget(right);splitter.setSizes([720,830])
        target_header=W.QHBoxLayout();target_header.addWidget(W.QLabel('ОБРАЗЕЦ ДЛЯ ИЗМЕРЕНИЯ'));target_header.addStretch()
        target_header.addWidget(button('+ Добавить образец','addTarget',self.add_item));target_header.addWidget(button('Убрать строку','removeTarget',self.remove_item));layout.addLayout(target_header)
        self.table=W.QTableWidget(0,6);self.table.setObjectName('targetTable')
        self.table.setHorizontalHeaderLabels(['Образец','Материал','Размеры, мм','Ориентация относительно катушки','Плановое расстояние, мм','Примечание / проход'])
        self.table.setItemDelegateForColumn(3,OrientationDelegate(self.table))
        self.table.horizontalHeader().setSectionResizeMode(W.QHeaderView.ResizeMode.Stretch);self.table.setSelectionBehavior(W.QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(W.QAbstractItemView.SelectionMode.SingleSelection);self.table.setMaximumHeight(150);self.table.setMinimumHeight(105)
        self.table.itemChanged.connect(self.sync_items);self.table.itemSelectionChanged.connect(self.select_item);layout.addWidget(self.table);self.refresh_items()
        controls=W.QHBoxLayout();self.record_btn=button('●  Начать запись','startRecording',lambda:self.guard(self.start_recording));self.record_btn.setObjectName('recordButton')
        self.stop_btn=button('■  Остановить','stopRecording',lambda:self.guard(self.stop_recording));self.stop_btn.setEnabled(False)
        controls.addWidget(self.record_btn);controls.addWidget(self.stop_btn)
        self.record_label=W.QLabel('Выберите предмет · задайте плоскость · сохраните пустой фон');self.record_label.setWordWrap(True);controls.addWidget(self.record_label,1)
        controls.addWidget(button('Папка опытов','openRecordings',lambda:QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(RECORDINGS)))))
        layout.addLayout(controls)
        self.message=W.QLabel('Перед записью выберите образец, укажите ориентацию и плановое расстояние.');self.message.setWordWrap(True);layout.addWidget(self.message)
        self.timer=QtCore.QTimer(self);self.timer.timeout.connect(self.tick);self.timer.start(100)
        if autostart:QtCore.QTimer.singleShot(300,lambda:self.guard(self.engine.start))

    def show_error(self,exc):
        self.ui_error=str(exc);self.message.setText('Ошибка: '+str(exc));self.message.setStyleSheet('color:#ff9292')
    def guard(self,fn):
        try:
            result=fn();self.ui_error=None;self.message.setStyleSheet('color:#86b9b2')
            if isinstance(result,str):self.message.setText(result)
            return result
        except Exception as exc:self.show_error(exc)
    def open_dialog(self,cls):
        try:
            d=cls(self);d.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose);self.dialogs.append(d);d.show()
        except Exception as exc:self.show_error(exc)
    def toggle_connection(self):
        if self.engine.running:self.engine.stop()
        else:self.engine.start()
    def display_settings(self):
        self.guard(lambda:self.engine.set_config(dict(view=self.mode.currentData(),alpha_color=self.alpha_color.value()/100,alpha_depth=self.alpha_depth.value()/100)))
    def point_mode(self):
        self.preview.mode='points';self.message.setText('Нажмите минимум 3, лучше 5–6, широко разнесённых точек на одной поверхности катушки. Затем «Принять плоскость».')
    def roi_mode(self):
        self.preview.mode='roi';self.message.setText('Протяните прямоугольник под катушкой. Вне этой области предметы не измеряются.')
    def set_roi(self,roi):
        self.engine.set_config({'roi':roi});self.preview.mode='';return 'Область измерения сохранена'
    def add_point(self,x,y):
        result=self.engine.add_point(x,y);return f"Точек плоскости: {result['count']}"
    def fit_plane(self):
        plane=self.engine.calibrate();self.preview.mode='';return f"Плоскость принята; СКО выбранных точек {plane['rms_mm']:.2f} мм. Сохраните пустой фон."
    def manual_plane(self):
        value,ok=W.QInputDialog.getDouble(self,'Плоскость параллельна камере','Расстояние от оптического центра камеры до плоскости катушки, мм.\nЭто приближение для строго параллельной установки:',650,100,5000,1)
        if ok:self.guard(lambda:self.engine.manual_plane(value))
    def refresh_items(self):
        self.table.blockSignals(True);self.table.setRowCount(len(self.engine.items))
        for i,row in enumerate(self.engine.items):
            for j,key in enumerate(['name','material','dimensions_mm','orientation','distance_mm','notes']):
                cell=W.QTableWidgetItem(str(row.get(key,'')));cell.setToolTip(cell.text());self.table.setItem(i,j,cell)
        if 0<=self.engine.selected_item<len(self.engine.items):self.table.selectRow(self.engine.selected_item)
        self.table.blockSignals(False)
    def sync_items(self):
        if self.engine.recorder:return
        rows=[]
        for i in range(self.table.rowCount()):
            rows.append({key:self.table.item(i,j).text() if self.table.item(i,j) else ''
                         for j,key in enumerate(['name','material','dimensions_mm','orientation','distance_mm','notes'])})
        self.engine.items=rows;self.engine.save_settings()
    def select_item(self):
        if not self.engine.recorder:self.engine.selected_item=self.table.currentRow()
    def add_item(self):
        if self.engine.recorder:return
        self.engine.items.append(dict(name='',material='неизвестно',dimensions_mm='',orientation=ORIENTATIONS[0],distance_mm='',notes=''))
        self.engine.selected_item=len(self.engine.items)-1;self.refresh_items();self.table.editItem(self.table.item(self.engine.selected_item,0));self.engine.save_settings()
    def remove_item(self):
        if self.engine.recorder:return
        i=self.engine.selected_item
        if 0<=i<len(self.engine.items):self.engine.items.pop(i)
        self.engine.selected_item=min(i,len(self.engine.items)-1);self.refresh_items();self.engine.save_settings()
    def phase_baseline(self):
        if self.engine.recorder:raise ValueError('Фон фазы фиксируется до записи')
        with self.engine.iq_lock:rows=list(self.engine.iq)[-200:]
        good=[r for r in rows if r['valid']]
        if len(good)<100:raise ValueError('Нужна секунда достоверных I/Q')
        iq=np.array([r['iq'] for r in good]);z=iq[:,0::2]+1j*iq[:,1::2]
        z=z[np.abs(z[:,2])>1e-8]
        if len(z)<100:raise ValueError('Слабый опорный сигнал TX')
        ratios=z/z[:,2,None];self.baseline=np.mean(ratios,axis=0)
        return 'Фон фазы зафиксирован. Он не изменяет исходные I/Q.'
    def save_plot_settings(self):dump(LOCAL/'plots.json',self.plot_settings)
    def start_recording(self):
        self.sync_items();path=self.engine.start_recording(dict(settings=copy.deepcopy(self.plot_settings),
            phase_baseline=[[float(v.real),float(v.imag)] for v in self.baseline] if self.baseline is not None else None))
        self.engine.recorder.submit('event',dict(type='plot_settings',host_ns=time.perf_counter_ns(),settings=self.plot_settings,
             phase_baseline=[[float(v.real),float(v.imag)] for v in self.baseline] if self.baseline is not None else None))
        return 'Запись: '+path
    def stop_recording(self):
        result=self.engine.stop_recording();return 'Завершаю запись: '+result['path'] if result else 'Запись не идёт'

    def update_plots(self):
        with self.engine.iq_lock:rows=list(self.engine.iq)
        with self.engine.distance_lock:distances=list(self.engine.distances)
        s=self.plot_settings;last=(time.perf_counter_ns()-self.engine.started_ns)/1e9
        distances=[p for p in distances if (p['host_ns']-self.engine.started_ns)/1e9>=last-s['seconds']]
        dt=np.array([(p['host_ns']-self.engine.started_ns)/1e9-last for p in distances])
        dv=np.array([p['filtered_mm'] for p in distances],float)
        connected=np.zeros(len(dt),bool)
        if len(dt)>1:connected[:-1]=np.isfinite(dv[:-1]) & np.isfinite(dv[1:]) & (np.diff(dt)>0) & (np.diff(dt)<=1.8/self.engine.config['fps'])
        self.distance_curve.setData(dt,dv,connect=connected)
        self.distance_plot.setXRange(-s['seconds'],0,padding=0)
        if s['distance_auto']:self.distance_plot.enableAutoRange(axis='y',enable=True)
        else:self.distance_plot.disableAutoRange(axis='y');self.distance_plot.setYRange(*s['distance_limits'],padding=0)
        if not rows:return
        rows=[r for r in rows if r['time_s']>=last-s['seconds']]
        if not rows:
            for panel in self.curves:
                for curve in panel:curve.clear()
            return
        t=np.array([r['time_s']-last for r in rows]);iq=np.array([r['iq'] for r in rows]);valid=np.array([r['valid'] for r in rows])
        z=iq[:,0::2]+1j*iq[:,1::2];ref=z[:,2]
        ratio=np.full_like(z,np.nan);good=valid & (np.abs(ref)>1e-8);ratio[good]=z[good]/ref[good,None]
        for panel,quantity in enumerate([s['top'],s['bottom']]):
            if quantity=='I/Q':values=iq.copy();labels=[f'{ch} {axis}' for ch in CHANNELS for axis in ['I','Q']];selected=[j for j in range(8) if j//2 in s['channels']]
            elif quantity=='Амплитуда |Z|':values=np.abs(z);labels=CHANNELS;selected=s['channels']
            elif quantity=='S/PDIF L/R':
                raw=self.engine.raw[-round(s['raw_ms']*96):];values=raw.copy();labels=['S/PDIF L','S/PDIF R'];selected=[0,1]
            else:
                if quantity.startswith('Δ'):
                    values=np.angle(ratio*np.conj(self.baseline),deg=True) if self.baseline is not None else np.full(z.shape,np.nan)
                else:values=np.angle(ratio,deg=True)
                labels=CHANNELS;selected=s['channels']
            raw_mode=quantity=='S/PDIF L/R'
            x=np.arange(-len(values)+1,1)/96000 if raw_mode else t
            if not raw_mode:values[~valid]=np.nan
            plot=self.plots[panel];legend=plot.plotItem.legend
            legend_key=(quantity,tuple(selected))
            if self.legend_state[panel]!=legend_key:
                legend.clear()
                for j in selected:
                    if j<len(labels):legend.addItem(self.curves[panel][j],labels[j])
                self.legend_state[panel]=legend_key
            plot.setTitle(quantity+(' · зафиксируйте фон' if quantity.startswith('Δ') and self.baseline is None else ''),size='11pt')
            plot.setXRange(float(x[0]) if raw_mode else -s['seconds'],0,padding=0)
            for j,curve in enumerate(self.curves[panel]):
                if j<values.shape[1] and j in selected:
                    curve.setData(x,values[:,j],connect='finite');curve.setVisible(True)
                else:curve.clear();curve.setVisible(False)
            if s['auto'][panel]:plot.enableAutoRange(axis='y',enable=True)
            else:plot.disableAutoRange(axis='y');plot.setYRange(*s['limits'][panel],padding=0)

    def command(self,body):
        action=body.get('action');e=self.engine
        if action=='status':return e.status()
        if action=='connect':e.start();return True
        if action=='disconnect':e.stop();return True
        if action=='settings':e.set_config(body['values']);return e.config
        if action=='camera_option':e.set_camera_option(int(body['sensor']),int(body['option']),float(body['value']));return 'queued'
        if action=='background':return e.capture_background()
        if action=='plane_point':return e.add_point(body['x'],body['y'])
        if action=='plane_clear':e.clear_points();return True
        if action=='plane_fit':return e.calibrate()
        if action=='plane_manual':e.manual_plane(float(body['distance_mm']));return e.plane
        if action=='restore_geometry':return e.restore_geometry()
        if action=='phase_baseline':return self.phase_baseline()
        if action=='item_add':
            if e.recorder:raise ValueError('Нельзя менять предмет во время записи')
            item=body['item'];keys=['name','material','dimensions_mm','orientation','distance_mm','notes']
            if not str(item.get('name','')).strip():raise ValueError('Нужно имя предмета')
            e.items.append({k:str(item.get(k,'')) for k in keys});e.selected_item=len(e.items)-1;e.save_settings();self.refresh_items();return e.selected_item
        if action=='item_select':
            if e.recorder:raise ValueError('Идёт запись')
            index=int(body['index'])
            if not 0<=index<len(e.items):raise ValueError('Нет такой строки')
            e.selected_item=index;self.refresh_items();return index
        if action=='record_start':return self.start_recording()
        if action=='record_stop':return e.stop_recording()
        if action=='plots':
            values=body['values']
            if any(k not in self.plot_settings for k in values):raise ValueError('Неизвестный параметр графика')
            new=dict(self.plot_settings,**values)
            if new['top'] not in QUANTITIES or new['bottom'] not in QUANTITIES:raise ValueError('Неверный график')
            if not 1<=new['seconds']<=120 or not 1<=new['raw_ms']<=100:raise ValueError('Неверное окно времени')
            if any(ch not in range(4) for ch in new['channels']):raise ValueError('Неверный канал')
            if len(new['auto'])!=2 or len(new['limits'])!=2 or any(len(v)!=2 or v[0]>=v[1] for v in new['limits']):raise ValueError('Неверный масштаб')
            if len(new['distance_limits'])!=2 or not 0<=new['distance_limits'][0]<new['distance_limits'][1]<=10000:raise ValueError('Неверный масштаб расстояния')
            self.plot_settings=new;self.save_plot_settings();return new
        if action=='show_dialog':
            self.open_dialog({'camera':CameraDialog,'capture':CaptureDialog,'plots':PlotDialog}[body['dialog']]);return True
        if action=='close':
            QtCore.QTimer.singleShot(100,self.close);return 'closing'
        raise ValueError('Неизвестная команда')

    def tick(self):
        while not self.api.commands.empty():
            body,answer=self.api.commands.get_nowait()
            try:answer.put_nowait({'ok':True,'result':self.command(body)})
            except Exception as exc:answer.put_nowait({'ok':False,'error':str(exc)})
        e=self.engine;latest=e.latest;now=time.perf_counter_ns()
        if latest and latest['host_ns']!=self.last_frame_id:
            self.last_frame_id=latest['host_ns'];self.preview.set_frame(latest['preview'])
            ok,jpg=cv2.imencode('.jpg',latest['preview'],[cv2.IMWRITE_JPEG_QUALITY,85])
            if ok:self.api.preview_jpeg=jpg.tobytes()
        fresh=latest is not None and now-latest['host_arrival_ns']<1e9
        m=latest['measurement'] if fresh else {'valid':False,'reason':'Нет свежих кадров'}
        self.distance.setText(f"{m['distance_mm']:.1f}  мм" if m.get('valid') else '—  мм')
        self.measure_note.setText(m['reason']+(' · ручная параллельная плоскость' if e.plane and e.plane['method'].startswith('manual') else ''))
        self.camera_status.setText(e.camera_status+f'  |  Пропущено кадров: {e.camera_drops}'+
            ('  |  Фон: готов' if e.background is not None else f'  |  Фон: {e.background_progress}/15')+
            ('\n'+e.camera_error if e.camera_error else '')+('\nПараметр: '+e.option_error if e.option_error else ''))
        with e.iq_lock:recent=list(e.iq)[-100:]
        fraction=sum(r['valid'] for r in recent)/len(recent) if recent else 0
        self.audio_status.setText(e.audio_status+f'  |  I/Q пригодно: {fraction:.0%}  |  Ошибок захвата: {e.audio_flags}'+('\n'+e.audio_error if e.audio_error else ''))
        self.connect_btn.setText('Отключить' if e.running else 'Подключить')
        active=e.recorder is not None;self.record_btn.setEnabled(not active);self.stop_btn.setEnabled(active);self.table.setEnabled(not active)
        self.mode.setEnabled(not active);self.alpha_color.setEnabled(not active);self.alpha_depth.setEnabled(not active)
        if active:
            duration=(now-e.recorder.start_ns)/1e9;self.record_label.setText(f'● ЗАПИСЬ  {duration:.1f} с  ·  {e.items[e.selected_item]["name"]}\n{e.recorder.path.name}')
            if e.recorder.stop_ns is not None:
                self.stop_btn.setEnabled(False)
                stage={'capture':'дочитывание потоков','analysis':'сопоставление данных','demonstration':'создание видео','hashes':'проверка файлов','done':'готово'}.get(e.recorder.stage,'сохранение')
                self.record_label.setText(f'Сохранение: {stage} · видео {e.recorder.export_progress:.0%}\n{e.recorder.path.name}')
            if e.recorder.stop_ns is None and (e.camera_error or e.audio_error or e.recorder.error or not fresh or now-e.last_audio_ns>2e9):
                e.recorder.error=e.recorder.error or e.camera_error or e.audio_error or 'Потеря свежих данных'
                self.guard(lambda:e.stop_recording('device_or_writer_error'));self.show_error('Запись остановлена из-за ошибки; неполный опыт сохранён')
        elif e.last_recording:
            prefix='Сохранение файлов: ' if e.last_recording.get('status')=='finalizing' else ('Неполный опыт: ' if e.last_recording['error'] else 'Сохранено: ')
            self.record_label.setText(prefix+e.last_recording['path'])
        self.update_plots()
        if self.close_when_done and not e.recorder and not (e.finalizer and e.finalizer.is_alive()):
            QtCore.QTimer.singleShot(0,self.close)

    def closeEvent(self,event):
        if self.engine.recorder or (self.engine.finalizer and self.engine.finalizer.is_alive()):
            self.close_when_done=True
            self.engine.stop_recording()
            event.ignore();return
        try:self.engine.stop();self.api.close();self.engine.save_settings();event.accept()
        except Exception as exc:self.show_error(exc);event.ignore()

STYLE='''
QWidget { background:#17212d; color:#dbe5ef; font-family:"Segoe UI"; font-size:10pt; }
QMainWindow { background:#17212d; }
QPushButton { background:#26384a; border:1px solid #3c5065; border-radius:5px; padding:7px 11px; }
QPushButton:hover { background:#334b62; }
QPushButton:disabled { color:#627589; background:#1e2c39; }
QPushButton#recordButton { background:#ac3848; border:1px solid #df6371; font-weight:600; }
QLabel#brand { font-size:19pt; font-weight:700; color:#55d6c2; padding:5px; }
QLabel#distance { font-size:30pt; font-weight:600; color:#6ae4c8; }
QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox { background:#101923; border:1px solid #3b4d60; border-radius:3px; padding:4px; }
QTableWidget { background:#101923; gridline-color:#304154; selection-background-color:#28566c; }
QHeaderView::section { background:#26384a; color:#b9cbdc; padding:5px; border:0; }
QTabBar::tab { background:#26384a; padding:9px; }
QTabBar::tab:selected { background:#356071; }
QSlider::groove:horizontal {height:4px;background:#40566d;}
QSlider::handle:horizontal {width:12px;margin:-5px 0;background:#48cdb5;border-radius:5px;}
'''

def main():
    p=argparse.ArgumentParser()
    group=p.add_mutually_exclusive_group()
    group.add_argument('--connect',dest='connect',action='store_true')
    group.add_argument('--no-connect',dest='connect',action='store_false')
    p.set_defaults(connect=bootstrap.FROZEN)
    p.add_argument('--quit-after',type=int)
    p.add_argument('--self-test',type=Path,metavar='REPORT_JSON',help='Offline check of bundled components; no capture')
    a=p.parse_args();app=W.QApplication(sys.argv[:1]);app.setStyle('Fusion');app.setStyleSheet(STYLE)
    if a.self_test:
        from self_test import run
        return run(a.self_test,app)
    try:
        LOCAL.mkdir(parents=True,exist_ok=True)
        with (LOCAL/'write-check.tmp').open('w',encoding='utf-8') as f:f.write('ok')
        (LOCAL/'write-check.tmp').unlink()
    except OSError as exc:
        W.QMessageBox.critical(None,'FerroDSP Lab',f'Не удаётся сохранить настройки: {LOCAL}\nРаспакуйте программу в доступную для записи папку или задайте FERRODSP_DATA_DIR.\n{exc}')
        return 1
    if not bootstrap.FROZEN:
        dump(LOCAL/'runtime.json',{'python_executable':str(Path(sys.executable).with_name('python.exe'))})
    instance_lock=QtCore.QLockFile(str(LOCAL/'application.lock'));instance_lock.setStaleLockTime(0)
    if not instance_lock.tryLock(100):
        W.QMessageBox.information(None,'FerroDSP Lab','Окно лаборатории уже запущено. Используйте существующее окно.');return 1
    window=MainWindow(a.connect);window.show()
    if a.quit_after:QtCore.QTimer.singleShot(a.quit_after*1000,window.close)
    result=app.exec();instance_lock.unlock();return result

if __name__=='__main__':raise SystemExit(main())
