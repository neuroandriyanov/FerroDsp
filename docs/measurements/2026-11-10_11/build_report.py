"""Rebuild bilingual figures/PDFs from the published numeric derivatives.
Python 3.12: pip install numpy matplotlib reportlab
Run from any directory. Original WAV/video/depth archives are not required.
"""
from pathlib import Path
import json,os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle

ROOT=Path(__file__).resolve().parent; DATA=ROOT/'data'; FIG=ROOT/'figures'; FIG.mkdir(exist_ok=True)
REPO=ROOT.parents[2]; PDF=REPO/'output/pdf'; PDF.mkdir(parents=True,exist_ok=True)
phase=json.loads((DATA/'phase-summary.json').read_text(encoding='utf8'))
raw=json.loads((DATA/'optical-summary.json').read_text(encoding='utf8'))
sessions=json.loads((DATA/'lab-sessions.json').read_text(encoding='utf8'))
validation=json.loads((DATA/'transport-validation.json').read_text(encoding='utf8'))
COL=['#245e98','#cc7038','#42836a','#8564a4']; NAVY='#19334b'; GRAY='#536575'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.edgecolor':'#b0bbc4','axes.labelcolor':NAVY,'text.color':NAVY,'xtick.color':GRAY,'ytick.color':GRAY,'grid.alpha':.2,'figure.facecolor':'white','savefig.facecolor':'white'})
font=font_manager.findfont('DejaVu Sans'); bold=font_manager.findfont(font_manager.FontProperties(family='DejaVu Sans',weight='bold'))
pdfmetrics.registerFont(TTFont('Body',font));pdfmetrics.registerFont(TTFont('Bold',bold))
pdfmetrics.registerFontFamily('Body',normal='Body',bold='Bold',italic='Body',boldItalic='Bold')
def tr(ru,en,l):return ru if l=='ru' else en
def save(fig,name,l):
    fig.savefig(FIG/f'{name}.{l}.png',dpi=190,bbox_inches='tight');plt.close(fig)
def gapline(ax,t,y,mask=None,**kw):
    z=np.array(y,float,copy=True)
    if mask is not None:z[~mask]=np.nan
    dt=np.diff(t);z[np.r_[False,dt>1.8*np.median(dt)]]=np.nan
    ax.plot(t,z,**kw)
def figures(l):
    names={'copper':tr('Медь','Copper',l),'aluminium':tr('Алюминий','Aluminium',l),'aluminum':tr('Алюминий','Aluminium',l),'screw':tr('Винт M4 × 40','M4 × 40 screw',l),'ring':tr('Золотое кольцо','Gold ring',l),'gold_ring':tr('Золотое кольцо','Gold ring',l),'steel_plate':tr('Стальной диск','Steel plate',l)}
    chosen=[r for r in phase if r['label_status']!='distance_and_orientation_unconfirmed']
    fig,ax=plt.subplots(figsize=(10,5.2),layout='constrained')
    for i,r in enumerate(chosen):
        color=COL[1] if r['material']=='screw' else COL[0]
        lo,hi=float(r['corrected_min']),float(r['corrected_max'])
        ax.plot([lo,hi],[i,i],color=color,lw=3);ax.scatter([lo,hi],[i,i],color=color,s=28,zorder=3)
    labels=[f"{names[r['material']]} · {'∥' if r['orientation']=='parallel' else '⊥'} · {r['reported_distance_mm']} mm"+(' (2)' if r['stage_id']=='screw_perpendicular_02' else '') for r in chosen]
    ax.set_yticks(range(len(chosen)),labels);ax.invert_yaxis();ax.axvline(0,color=GRAY,lw=.8);ax.grid(axis='x');ax.set_xlabel(tr('Отклонение T22 от фона, относительные единицы','T22 deviation from background, relative units',l))
    ax.set_title(tr('10 ноября · диапазон отклика штатного детектора','10 November · native detector response range',l),loc='left',fontweight='bold');save(fig,'phase-ranges',l)
    fig,axs=plt.subplots(1,2,figsize=(10,5),layout='constrained')
    for ax,source in zip(axs,['rx','tx']):
        ss=[s for s in raw if s['source']==source]
        for i,s in enumerate(ss):
            lo,hi=s['active_phase_min_max_deg'];c=COL[1] if s['material']=='steel_plate' else COL[0]
            ax.plot([lo,hi],[i,i],color=c,lw=3);ax.scatter([lo,hi],[i,i],c=c,s=22)
        ax.set_yticks(range(len(ss)),[f"{names[s['material']]} {'∥' if s['orientation']=='parallel' else '⊥'}" for s in ss]);ax.invert_yaxis();ax.axvline(0,color=GRAY,lw=.8);ax.grid(axis='x');ax.set_xlabel(tr('Изменение взаимной фазы, °','Interchannel phase change, °',l));ax.set_title('RX0 / RX1' if source=='rx' else 'TX16 / TX17',loc='left')
    save(fig,'optical-ranges',l)
    fig,axs=plt.subplots(2,1,figsize=(10,5.3),sharex=True,layout='constrained')
    for material,c in [('copper',COL[0]),('steel_plate',COL[1])]:
        s=next(s for s in raw if s['source']=='rx' and s['material']==material and s['orientation']=='parallel')
        d=np.load(DATA/f"{s['stage']}-features.npz");t=d['t']-s['cue_s'];mask=(t>=-10)&(t<=s['reply_s']-s['cue_s'])
        for ax,key in zip(axs,['phase_deg','ratio_percent']):ax.plot(t[mask],d[key][mask],c=c,lw=1.2,label=f"{names[material]} · {int(s['distance_mm'])} mm")
    for ax in axs:ax.axvline(0,color=GRAY,lw=.8,ls='--');ax.grid();ax.legend(loc='lower left',fontsize=9)
    axs[0].set_ylabel(tr('Δ фазы, °','Phase change, °',l));axs[1].set_ylabel(tr('Δ отношения амплитуд, %','Amplitude ratio change, %',l));axs[-1].set_xlabel(tr('Время от инструкции оператору, с','Time from operator instruction, s',l));save(fig,'optical-traces',l)
    d=np.load(DATA/'transport-background.npz');t=d['time_s'];a=d['iq'];z=a[:,0::2]+1j*a[:,1::2];q=z/z[:,2,None];ph=np.angle(q,deg=True);valid=d['valid']
    fig,axs=plt.subplots(2,1,figsize=(10,4.8),sharex=True,layout='constrained',height_ratios=[3,1])
    for k in [0,1,3]:gapline(axs[0],t,ph[:,k]-np.median(ph[valid,k]),valid,c=COL[k],lw=1,label=['RX0','RX1','TX16','TX17'][k])
    axs[0].set_ylabel(tr('Фаза к TX16 минус медиана, °','Phase vs TX16 minus median, °',l));axs[0].legend(ncol=3);axs[0].grid()
    axs[1].fill_between(t,0,(~valid).astype(int),color=COL[1],step='mid');axs[1].set_yticks([0,1],[tr('Годен','Valid',l),tr('Исключён','Rejected',l)]);axs[1].set_xlabel(tr('Время записи, с','Recording time, s',l));save(fig,'transport-quality',l)
    d=np.load(DATA/(sessions[1]['id']+'.npz'));ts=d['signals__time_s'];tf=d['frames__time_s'];valid=d['signals__valid']&d['signals__timestamp_valid'];geom=d['frames__geometry_valid']&d['frames__timestamp_valid']
    fig,axs=plt.subplots(3,1,figsize=(10,7.3),sharex=True,layout='constrained')
    for k in [0,1,3]:
        gapline(axs[0],ts,d['signals__delta_phase_tx_deg'][:,k],valid&d['signals__phase_valid'][:,k],c=COL[k],lw=1,label=['RX0','RX1','TX16','TX17'][k])
        gapline(axs[1],ts,d['signals__amplitude'][:,k],valid,c=COL[k],lw=1)
    axs[0].legend(ncol=3);axs[0].set_ylabel(tr('Δ фазы к TX16, °','Phase change vs TX16, °',l));axs[1].set_ylabel(tr('Амплитуда |Z|, отн. ед.','Amplitude |Z|, relative units',l))
    gapline(axs[2],tf,d['frames__distance_mm'],geom,color='#b1b9c0',lw=.8,label=tr('Исходное расстояние','Original distance',l));gapline(axs[2],tf,d['frames__distance_filtered_mm'],geom,color=COL[0],lw=1.2,label=tr('После фильтра','Filtered',l));axs[2].legend(ncol=2,fontsize=9);axs[2].set_ylabel(tr('До плоскости катушки, мм','To coil plane, mm',l));axs[2].set_xlabel(tr('Общая временная шкала ПК, с','Common PC timeline, s',l))
    for ax in axs:ax.grid();ax.set_xlim(0,67.2)
    save(fig,'ring-timeline',l)

class Report:
    def __init__(self,l):
        self.l=l;self.path=PDF/f'FerroDSP-bench-2026-11-10_11.{l}.pdf';self.c=canvas.Canvas(str(self.path),pagesize=(595.276,841.89));self.c.setTitle(tr('FerroDSP | Стендовые измерения 10-11 ноября 2026','FerroDSP | Bench measurements 10-11 November 2026',l));self.c.setAuthor('FerroDSP project');self.page=0
    def start(self,title,kicker):
        if self.page:self.c.showPage()
        self.page+=1;self.c.setFillColor(HexColor(NAVY));self.c.rect(0,807,595.276,35,fill=1,stroke=0);self.c.setFillColor(HexColor('#ffffff'));self.c.setFont('Bold',10);self.c.drawString(42,820,'FerroDSP');self.c.setFont('Body',8);self.c.drawRightString(553,820,'BENCH NOTES  /  10-11.11.2026')
        self.c.setFillColor(HexColor(GRAY));self.c.setFont('Body',8);self.c.drawString(42,781,kicker.upper());self.c.setFillColor(HexColor(NAVY));self.c.setFont('Bold',21);self.c.drawString(42,748,title);self.y=722
        self.c.setStrokeColor(HexColor('#d6dfe6'));self.c.line(42,42,553,42);self.c.setFillColor(HexColor(GRAY));self.c.setFont('Body',8);self.c.drawString(42,28,'github.com/neuroandriyanov/FerroDsp');self.c.drawRightString(553,28,f'{self.l.upper()}  /  {self.page:02d}')
    def text(self,ru,en,size=10.1):
        p=Paragraph(tr(ru,en,self.l),ParagraphStyle('p',fontName='Body',fontSize=size,leading=size*1.5,textColor=HexColor(NAVY),spaceAfter=10));w,h=p.wrap(511,800);assert self.y-h>54,(self.page,self.y,h);p.drawOn(self.c,42,self.y-h);self.y-=h+12
    def image(self,name,height):
        self.c.drawImage(str(FIG/f'{name}.{self.l}.png'),42,self.y-height,511,height,preserveAspectRatio=True,anchor='c',mask='auto');self.y-=height+14
    def finish(self):self.c.save();(ROOT/self.path.name).write_bytes(self.path.read_bytes())

def report(l):
    r=Report(l)
    r.start(tr('Стендовые измерения','Bench measurements',l),tr('Ноябрь 2026 · экспериментальный прототип','November 2026 · experimental prototype',l))
    r.text('Два дня исследований: отклик образцов, передача четырёх комплексных каналов через S/PDIF и совместная регистрация сигналов с камерой глубины. Это журнал опытов на одном экземпляре, а не спецификация глубины поиска или готовый классификатор.','Two days of research: target responses, four complex channels over S/PDIF, and joint recording with a depth camera. These are observations from one prototype, not a detection-depth specification or a validated classifier.')
    r.text('<b>Стенд.</b> Датчик расположен горизонтально, примерно в 650 мм над деревянным полом. Под настилом находится бетон с арматурой. Размер деревянного слоя около 100 мм указан оператором без уточнения конструкции. Образцы перемещались между полом и катушкой. Расстояния 10 ноября заданы оператором приблизительно.','<b>Setup.</b> The coil is horizontal, approximately 650 mm above a wooden floor over reinforced concrete. The operator reported an approximately 100 mm wooden layer; the detailed construction was not established. Targets moved between the floor and coil. Distances on 10 November were approximate operator estimates.')
    r.text('<b>Оборудование.</b> FerroDSP: ADAU1452 (Analog Devices), два PCM1808 и PCM5102A (Texas Instruments), усилитель TX TDA2050 (STMicroelectronics). Настройка: SigmaStudio 4.7 и USBi; производитель конкретного адаптера USBi не подтверждён. Аудиозахват: Creative Sound Blaster G3, оптический вход. Камера: Intel RealSense D415, USB, активное стерео глубины и цветное изображение. Отдельная плата видеозахвата не использовалась.','<b>Equipment.</b> FerroDSP: ADAU1452 (Analog Devices), two PCM1808 ADCs and PCM5102A DAC (Texas Instruments), TDA2050 TX amplifier (STMicroelectronics). Configuration: SigmaStudio 4.7 and USBi; the maker of the particular USBi adapter is unconfirmed. Audio capture: Creative Sound Blaster G3 optical input. Camera: Intel RealSense D415, USB, active stereo depth and color imaging. No separate video capture card was used.')
    r.text('<b>Режимы.</b> Fs DSP и аудиозахвата 96 кГц; генератор 15,2 кГц. Штатный фазовый проект: TX -30 дБ. Прямые оптические опыты и PC Stream: TX -18 дБ. Уровни относятся к цифровому генератору, не к мощности в ваттах. WAV использует контейнер PCM24; это не измерение эффективной разрядности G3.','<b>Operating modes.</b> DSP and audio capture run at 96 kHz; excitation is 15.2 kHz. Native phase project: TX -30 dB. Direct optical trials and PC Stream: TX -18 dB. These are digital generator levels, not power in watts. WAV uses a PCM24 container; this does not establish the effective resolution of the G3.')
    r.text('<b>Главный результат.</b> Для разработки сохраняются все четыре комплексных входа. Взаимная фаза RX0/RX1 не дала универсального правила «знак = тип металла». Размер, ориентация и расстояние остаются смешанными факторами.','<b>Main result.</b> All four complex inputs are retained for algorithm development. RX0/RX1 interchannel phase did not yield a universal “sign = metal class” rule. Size, orientation and distance remain confounding factors.')
    r.start(tr('Отклик фазового детектора','Native phase response',l),tr('10 ноября · чтение через USBi','10 November · USBi readback',l))
    r.image('phase-ranges',300)
    r.text('T22 - знаковый отфильтрованный выход балансного детектора в относительных единицах; это <b>не угол в градусах</b>. Отрезки показывают минимум и максимум после коррекции фона, а не доверительные интервалы. ∥ / ⊥ относятся к плоскости фольги или кольца, для винта - к его оси относительно плоскости катушки.','T22 is the signed, filtered balance-detector output in relative units; it is <b>not an angle in degrees</b>. Segments show the background-corrected minimum and maximum, not confidence intervals. ∥ / ⊥ refer to foil/ring planes; for the screw they refer to its axis relative to the coil plane.')
    r.text('Медь около 50 × 70 мм, алюминий 70 × 70 мм, винт M4 × 40 мм, золотое обручальное кольцо. Минимумы: медь ∥ 400 мм -0,03239; алюминий ∥ 400 мм -0,04396; кольцо ∥ 200 мм -0,03332. Винт ∥ 200 мм: диапазон -0,00678…+0,00619, около 3 фоновых σ. На 100 мм максимум винта достигал +0,01589.','Copper approximately 50 × 70 mm, aluminium 70 × 70 mm, an M4 × 40 mm screw and a gold wedding ring. Minima: copper ∥ at 400 mm -0.03239; aluminium ∥ at 400 mm -0.04396; ring ∥ at 200 mm -0.03332. Screw ∥ at 200 mm: -0.00678…+0.00619, approximately 3 background σ. At 100 mm the screw maximum reached +0.01589.')
    r.text('Показаны 10 размеченных записей. Одна запись винта исключена из графика: расстояние 200 мм и ориентация не подтверждены. Запись screw_perpendicular_02 исправлена по уточнению оператора: ось параллельна катушке, 100 мм. Результаты не определяют предельную глубину обнаружения.','The graph contains 10 labeled recordings. One screw recording is excluded because its 200 mm distance and orientation were not confirmed. The screw_perpendicular_02 label was corrected from the operator’s clarification: axis parallel to the coil, 100 mm. These observations do not establish maximum detection depth.')
    r.start(tr('Прямые оптические записи','Direct optical recordings',l),tr('10 ноября · RX и TX в отдельных проходах','10 November · separate RX and TX passes',l))
    r.image('optical-ranges',270)
    r.text('16 записей: RX0/RX1 и TX16/TX17, четыре образца, две ориентации. Фольга и кольцо - около 200 мм, стальной диск - около 400 мм для уменьшения перегрузки. Поэтому амплитуды разных материалов нельзя сравнивать как измерения при одинаковой геометрии.','16 recordings: RX0/RX1 and TX16/TX17, four targets, two orientations. Foil and ring were approximately 200 mm away; the steel plate was approximately 400 mm away to reduce overload. Amplitudes across materials therefore do not represent identical geometry.')
    r.text('Обработка: комплексная демодуляция 15,2 кГц, окно Hann 20 мс, 50 оценок/с. Отношение q = Z0/Z1 нормировано по медиане фона за 12…2 с до инструкции. Для просмотра использованы медианный фильтр 5 отсчётов и двунаправленный ФНЧ 3 Гц. Это офлайн-обработка. Границы - инструкция и ответ оператора, не точные моменты каждого прохода.','Processing: complex demodulation at 15.2 kHz, a 20 ms Hann window, 50 estimates/s. The ratio q = Z0/Z1 is normalized to the median background 12…2 s before the instruction. A five-sample median filter and bidirectional 3 Hz low-pass filter are used for inspection. This is offline processing. Bounds correspond to the instruction and reply, not exact physical pass times.')
    r.text('<b>Вывод:</b> отрицательные изменения взаимной фазы RX наблюдались и для цветных образцов, и для стали. RX и TX записывались последовательно; из этих опытов нельзя восстановить синхронную фазу RX относительно TX.','<b>Finding:</b> negative RX interchannel phase changes occurred for both nonferrous samples and steel. RX and TX were recorded sequentially; these trials cannot reconstruct simultaneous RX-to-TX phase.')
    r.start(tr('Передача четырёх каналов','Four-channel transport',l),'ferrodsp-am-iq-v1')
    r.image('transport-quality',255)
    r.text('В DSP каждый вход умножается на синус/косинус 15,2 кГц и проходит ФНЧ 100 Гц четвёртого порядка. Восемь величин I/Q передаются на несущих 1500 / 3700 / 5900 / 8100 Гц: левый канал I, правый Q, пилот 10300 Гц. ПК: окно Hann 40 мс, шаг 10 мс, 100 комплектов/с. Это комплексные огибающие, не четыре полнополосных потока АЦП.','Each DSP input is mixed with 15.2 kHz sine/cosine references and passed through a fourth-order 100 Hz low-pass filter. Eight I/Q values are carried at 1500 / 3700 / 5900 / 8100 Hz: left = I, right = Q, pilot = 10300 Hz. PC decoding uses a 40 ms Hann window and 10 ms hop, yielding 100 sets/s. These are complex envelopes, not four full-bandwidth ADC streams.')
    r.text('Проверка импульсами: найдены 20 из 20 ожидаемых плато. На 396 установившихся кадрах максимальное абсолютное смещение 8,97 × 10⁻⁷, RMS ошибки I/Q 2,77 × 10⁻⁷…9,29 × 10⁻⁷; переходы ±100 мс исключены. Это проверка передачи заданных значений, не точности измерения металла.','Pulse check: all 20 expected plateaus were found. Across 396 settled frames, maximum absolute bias was 8.97 × 10⁻⁷ and I/Q RMS error ranged from 2.77 × 10⁻⁷ to 9.29 × 10⁻⁷; ±100 ms around transitions was excluded. This validates transmission of prescribed values, not metal measurement accuracy.')
    r.text('Фон 60 с: 5825/5997 годных комплектов, 123 исключённых после первой секунды, семь интервалов нарушения временной непрерывности. Разрывы оставлены на графике. Общий такт генератора и АЦП не предотвращает потери при захвате на ПК.','60 s background: 5825/5997 valid sets, 123 rejected after the first second, and seven timing-discontinuity intervals. Gaps remain visible. A shared generator/ADC clock does not prevent capture losses on the PC.')
    r.start(tr('Сигнал и положение образца','Signal and target position',l),tr('11 ноября · золотое кольцо 21 × 3 мм','11 November · gold ring 21 × 3 mm',l))
    r.image('ring-timeline',390)
    r.text('Плоскость кольца параллельна катушке. D415: глубина и цвет 640 × 480, 15 кадр/с. Записано 6715 I/Q-комплектов, 99,4937% годных, 999 кадров камеры; 905 полных наблюдений. Максимальное расхождение ближайшей пары сигнал/кадр 5,027 мс на шкале ПК. <b>Физическая задержка камеры относительно аудио не откалибрована.</b>','Ring plane parallel to the coil. D415: depth and color at 640 × 480, 15 fps. Recorded 6715 I/Q sets, 99.4937% valid, 999 camera frames and 905 complete observations. Maximum nearest signal/frame difference was 5.027 ms on the PC timeline. <b>Physical camera-to-audio latency was not calibrated.</b>',9.6)
    r.text('Расстояние относится к ближайшей видимой поверхности перед пустым фоном и плоскости катушки; это может быть рука или держатель, а не центр кольца. Фильтр Hampel, окно 5 кадров, порог max(15 мм, 3 × 1,4826 MAD): исправлено 78 выбросов. Пропуски не заполнены; временная метка центрального кадра сохранена.','Distance refers to the nearest visible foreground surface and the coil plane; it may be a hand or holder rather than the ring center. A five-frame Hampel filter with threshold max(15 mm, 3 × 1.4826 MAD) corrected 78 outliers. Gaps were not filled; center-frame timestamps were preserved.',9.6)
    r.start(tr('Лаборатория и выводы','Laboratory and findings',l),tr('Воспроизводимость и дальнейшие проверки','Reproducibility and next checks',l))
    r.c.drawImage(str(REPO/'фото/screenS.png'),42,r.y-275,511,275,preserveAspectRatio=True,anchor='c');r.y-=289
    r.text('Скриншот интерфейса предоставлен автором; счётчики относятся к накопленной сессии и не заменяют проверку отдельной записи. Демонстрация: H.264/AVC, 1280 × 640, 15 кадр/с, 67,2 с. <link href="https://media.neuroandriyanov.com/demonstration_ferrodsp_lab.mp4" color="#245e98">Открыть видео</link>.','The author supplied this interface screenshot; its counters are cumulative and do not replace per-recording validation. Demonstration: H.264/AVC, 1280 × 640, 15 fps, 67.2 s. <link href="https://media.neuroandriyanov.com/demonstration_ferrodsp_lab.mp4" color="#245e98">Open video</link>.',9.5)
    r.text('Три сохранённых до раскрытия ответа предположения совпали с названиями знакомых образцов: алюминий, медь, кольцо. В двух опытах ориентация отличалась от инструкции. Для магнитного штангенциркуля около 250 мм сохранён ответ «неопределённо». Это не независимая проверка точности классификации.','Three predictions saved before reveal matched the identities of familiar objects: aluminium, copper and ring. Two trials differed from the instructed orientation. A magnetic caliper at approximately 250 mm received the saved answer “uncertain”. This is not an independent classifier accuracy evaluation.',9.5)
    r.text('<b>Следующий алгоритм:</b> контроль качества → комплексная нормировка к TX16 → оценка фона с замораживанием при цели → признаки ΔI/ΔQ обоих RX и отношения TX16/TX17 → проверка по целым проходам и новым предметам. Сначала сохраняются все четыре канала. Оценка размера, материала и глубины требует контролируемой геометрии и отдельной тестовой выборки.','<b>Next algorithm:</b> quality gating → complex normalization to TX16 → background estimation frozen during target events → ΔI/ΔQ features from both RX channels plus the TX16/TX17 ratio → evaluation by whole passes and unseen objects. Retain all four channels initially. Size, material and depth estimation require controlled geometry and a separate test set.',9.5)
    r.text('Числовые производные, контрольные суммы исходных файлов, методика и скрипт построения: <link href="https://github.com/neuroandriyanov/FerroDsp/tree/main/docs/measurements/2026-11-10_11" color="#245e98">материалы отчёта на GitHub</link>. Исходные WAV и массивы глубины остаются в локальном архиве; опубликованные NPZ позволяют перестроить приведённые графики.','Numeric derivatives, source hashes, methodology and build script: <link href="https://github.com/neuroandriyanov/FerroDsp/tree/main/docs/measurements/2026-11-10_11" color="#245e98">report materials on GitHub</link>. Original WAV and depth arrays remain in the local archive; published NPZ files reproduce these plots.',9.1)
    r.finish()
for lang in ['ru','en']:figures(lang);report(lang)
print('Built two reports and ten figures')
