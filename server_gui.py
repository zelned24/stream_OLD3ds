"""Desktop control panel. Run with pythonw server_gui.py (no console window)."""
import argparse
import json
import os
from pathlib import Path
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

ROOT = Path(__file__).resolve().parent
BG, CARD, TEXT, MUTED, ACCENT = '#101821', '#1a2733', '#e9f2f5', '#97acbc', '#42ddbb'

class ServerWindow:
    def __init__(self, root, autostart=False):
        self.root=root
        self.process=None
        self.events=queue.Queue()
        self.stop_path=None
        self.closing=False
        root.title('Rogue Stream · Servidor')
        root.geometry('940x770')
        root.minsize(840,700)
        root.configure(bg=BG)
        style=ttk.Style(root); style.theme_use('clam')
        style.configure('.', font=('Segoe UI',10), background=BG, foreground=TEXT)
        style.configure('TFrame', background=BG)
        style.configure('Card.TFrame', background=CARD)
        style.configure('TLabel', background=BG, foreground=TEXT)
        style.configure('Muted.TLabel', foreground=MUTED)
        style.configure('Title.TLabel', font=('Segoe UI Semibold',25))
        style.configure('TButton', padding=(15,10), background=CARD, foreground=TEXT)
        style.map('TButton', background=[('active','#304554')])
        style.configure('Accent.TButton', background=ACCENT, foreground=BG)
        style.map('Accent.TButton', background=[('active','#77f0d3'),('disabled','#354d50')])
        style.configure('TEntry', fieldbackground=CARD, foreground=TEXT, padding=8)
        style.configure('TCombobox', fieldbackground=CARD, foreground=TEXT, padding=7)
        style.map('TCombobox', fieldbackground=[('readonly',CARD)], foreground=[('readonly',TEXT)])
        style.configure('TCheckbutton', background=BG, foreground=TEXT)
        style.configure('TLabelframe', background=BG, bordercolor=CARD)
        style.configure('TLabelframe.Label', foreground=MUTED)
        root.option_add('*TCombobox*Listbox.background', CARD)
        root.option_add('*TCombobox*Listbox.foreground', TEXT)
        outer=ttk.Frame(root,padding=24); outer.pack(fill='both',expand=True)
        header=ttk.Frame(outer); header.pack(fill='x')
        ttk.Label(header,text='ROGUE STREAM',style='Title.TLabel').pack(side='left')
        self.status=tk.StringVar(value='DETENIDO')
        tk.Label(header,textvariable=self.status,bg=CARD,fg=ACCENT,padx=14,pady=8,font=('Segoe UI Semibold',10)).pack(side='right')
        ttk.Label(outer,text='Tu PC ejecuta el juego. La consola muestra la imagen y envía los controles.',style='Muted.TLabel').pack(anchor='w',pady=(4,20))
        cards=ttk.Frame(outer); cards.pack(fill='x')
        self.metrics={}
        for column,(key,label) in enumerate([('rx','FPS RECIBIDOS'),('tx','FPS ENVIADOS'),('capture','CAPTURA'),('drops','DESCARTADOS / MUESTRA')]):
            card=ttk.Frame(cards,style='Card.TFrame',padding=14)
            card.grid(row=0,column=column,sticky='nsew',padx=(0,8 if column<3 else 0)); cards.columnconfigure(column,weight=1)
            tk.Label(card,text=label,bg=CARD,fg=MUTED,font=('Segoe UI',9)).pack(anchor='w')
            variable=tk.StringVar(value='—'); self.metrics[key]=variable
            tk.Label(card,textvariable=variable,bg=CARD,fg=ACCENT,font=('Segoe UI Semibold',23)).pack(anchor='w',pady=(5,0))
        self.url=tk.StringVar(value='https://pokerogue.net')
        self.mode=tk.StringVar(value='Azahar · esta PC')
        self.fps=tk.StringVar(value='30')
        self.quality=tk.StringVar(value='320 × 192 · equilibrio JPEG')
        self.capture=tk.StringVar(value='Directa · rápida')
        self.visible=tk.BooleanVar(value=True)
        self.audio=tk.BooleanVar(value=False)
        self.sharp=tk.BooleanVar(value=False)
        self.fec=tk.BooleanVar(value=False)
        self.load_settings()
        form=ttk.Frame(outer); form.pack(fill='x',pady=18)
        form.columnconfigure(0,weight=1); form.columnconfigure(1,weight=1)
        ttk.Label(form,text='DIRECCIÓN DEL JUEGO',style='Muted.TLabel').grid(row=0,column=0,columnspan=2,sticky='w')
        entry=ttk.Entry(form,textvariable=self.url); entry.grid(row=1,column=0,columnspan=2,sticky='ew',pady=(5,12))
        self.fields=[entry]
        for row,col,label,var,values in [
            (2,0,'DESTINO',self.mode,['Azahar · esta PC','Nintendo 3DS · red local']),
            (2,1,'FPS INICIALES',self.fps,['10','15','20','30','45','60']),
            (4,0,'RESOLUCIÓN INICIAL',self.quality,['400 × 240 · detalle JPEG','320 × 192 · equilibrio JPEG','200 × 120 · fluidez']),
            (4,1,'CAPTURA',self.capture,['Directa · rápida','PNG · compatible'])]:
            ttk.Label(form,text=label,style='Muted.TLabel').grid(row=row,column=col,sticky='w',padx=(0,12))
            combo=ttk.Combobox(form,textvariable=var,values=values,state='readonly')
            combo.grid(row=row+1,column=col,sticky='ew',padx=(0,12 if col==0 else 0),pady=(5,12)); self.fields.append(combo)
        check=ttk.Checkbutton(form,text='Mostrar navegador para iniciar sesión',variable=self.visible)
        check.grid(row=6,column=0,columnspan=2,sticky='w'); self.fields.append(check)
        audio_check=ttk.Checkbutton(form,text='Audio: transmitir salida Windows (incluye otros sonidos de PC)',variable=self.audio)
        audio_check.grid(row=7,column=0,columnspan=2,sticky='w'); self.fields.append(audio_check)
        for row, label, variable in [(8,'Nitidez: JPEG 4:4:4 sin filtros (puede reducir FPS)',self.sharp),
                                     (9,'Recuperar un paquete perdido por imagen JPEG',self.fec)]:
            option=ttk.Checkbutton(form,text=label,variable=variable)
            option.grid(row=row,column=0,columnspan=2,sticky='w'); self.fields.append(option)
        self.connection=tk.StringVar(value=self.network_hint())
        self.mode.trace_add('write',lambda *_:self.connection.set(self.network_hint()))
        ttk.Label(outer,textvariable=self.connection,style='Muted.TLabel').pack(anchor='w')
        actions=ttk.Frame(outer); actions.pack(fill='x',pady=(14,10))
        self.start_button=ttk.Button(actions,text='▶  Iniciar servidor',style='Accent.TButton',command=self.start)
        self.start_button.pack(side='left')
        self.stop_button=ttk.Button(actions,text='■  Detener',command=self.stop,state='disabled'); self.stop_button.pack(side='left',padx=8)
        ttk.Button(actions,text='Abrir Azahar ↗',command=self.open_azahar).pack(side='right')
        ttk.Label(outer,text='En la pantalla inferior: SELECT abre ajustes · pestaña Botones para reasignar.',style='Muted.TLabel').pack(anchor='w',pady=(0,14))
        log_frame=ttk.LabelFrame(outer,text=' ACTIVIDAD ',padding=8); log_frame.pack(fill='both',expand=True)
        self.log=tk.Text(log_frame,height=6,bg='#0b1118',fg=MUTED,insertbackground=TEXT,relief='flat',font=('Consolas',9),wrap='word',state='disabled')
        scrollbar=ttk.Scrollbar(log_frame,command=self.log.yview)
        self.log.configure(yscrollcommand=scrollbar.set); scrollbar.pack(side='right',fill='y'); self.log.pack(fill='both',expand=True)
        self.append('Listo. Los ajustes iniciales se aplican al conectar el cliente; después puedes cambiarlos desde la consola.')
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.after(100,self.poll)
        if autostart: root.after(400,self.start)

    def network_hint(self):
        if self.mode.get().startswith('Azahar'): return 'Conexión local · 127.0.0.1:5000'
        try: addresses=', '.join(socket.gethostbyname_ex(socket.gethostname())[2])
        except OSError: addresses='consulta ipconfig'
        return f'Red local · UDP 5000 · IP de esta PC: {addresses}'

    def load_settings(self):
        try:
            values=json.loads((ROOT/'server-settings.json').read_text(encoding='utf-8'))
            for key in ('url','mode','fps','quality','capture','visible','audio','sharp','fec'):
                if key in values: getattr(self,key).set(values[key])
        except (OSError,ValueError,tk.TclError): pass

    def append(self,text):
        self.log.configure(state='normal'); self.log.insert('end',text.rstrip()+'\n'); self.log.see('end')
        if int(self.log.index('end-1c').split('.')[0])>500: self.log.delete('1.0','100.0')
        self.log.configure(state='disabled')

    def start(self):
        if self.process and self.process.poll() is None: return
        if not self.url.get().startswith(('http://','https://')):
            messagebox.showerror('Dirección del juego','Introduce una dirección http:// o https://.'); return
        bind='127.0.0.1' if self.mode.get().startswith('Azahar') else '0.0.0.0'
        probe=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        try: probe.bind((bind,5000))
        except OSError:
            messagebox.showerror('Servidor ya abierto','El puerto UDP 5000 está ocupado. Detén el otro servidor antes de iniciar este.'); return
        finally: probe.close()
        settings={key:getattr(self,key).get() for key in ('url','mode','fps','quality','capture','visible','audio','sharp','fec')}
        (ROOT/'server-settings.json').write_text(json.dumps(settings,ensure_ascii=False,indent=2),encoding='utf-8')
        self.stop_path=ROOT/f'.server-stop-{os.getpid()}-{time.time_ns()}'
        python=Path(sys.executable).with_name('python.exe') if os.name=='nt' else Path(sys.executable)
        command=[str(python),'-u',str(ROOT/'server.py'),'--url',self.url.get(),'--bind',bind,
                 '--fps',self.fps.get(),'--channel','msedge','--profile',str(ROOT/'.browser-profile'),
                 '--capture','canvas' if self.capture.get().startswith('Directa') else 'screenshot',
                 '--stop-file',str(self.stop_path)]
        if self.visible.get(): command.append('--visible')
        command.extend(['--mode','1' if self.quality.get().startswith('200') else '2' if self.quality.get().startswith('320') else '0'])
        if self.audio.get(): command.append('--audio')
        if self.sharp.get(): command.append('--sharp')
        if self.fec.get(): command.append('--fec')
        try:
            self.process=subprocess.Popen(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                text=True,encoding='utf-8',errors='replace',env={**os.environ,'PYTHONIOENCODING':'utf-8'},
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        except OSError as error: messagebox.showerror('No se pudo iniciar',str(error)); return
        self.status.set('INICIANDO'); self.start_button.configure(state='disabled'); self.stop_button.configure(state='normal')
        for field in self.fields: field.configure(state='disabled')
        for variable in self.metrics.values(): variable.set('—')
        self.append('Iniciando navegador y servidor…')
        def reader(process):
            with (ROOT/'server.log').open('w',encoding='utf-8') as logfile:
                for line in process.stdout:
                    logfile.write(line); logfile.flush(); self.events.put(line)
        threading.Thread(target=reader,args=(self.process,),daemon=True).start()

    def stop(self):
        if self.process and self.process.poll() is None:
            self.status.set('DETENIENDO'); self.stop_button.configure(state='disabled')
            self.stop_path.touch()
            self.append('Cerrando el navegador y liberando la conexión…')

    def open_azahar(self):
        candidates=[Path(os.environ.get('LOCALAPPDATA',''))/'Programs/Azahar/azahar.exe',Path('D:/Proyectos/3ds/PokeRogue3DS/tools/emulator/azahar.exe')]
        executable=next((path for path in candidates if path.exists()),None)
        if not executable: messagebox.showerror('Azahar','No se encontró Azahar instalado.'); return
        subprocess.Popen([str(executable),str(ROOT/'client/rogue_stream.3dsx')],cwd=ROOT)

    def poll(self):
        while not self.events.empty():
            line=self.events.get_nowait(); self.append(line)
            if self.status.get()!='DETENIENDO':
                if 'Juego listo:' in line: self.status.set('ESPERANDO CONSOLA')
                if 'Video: TX=' in line: self.status.set('TRANSMITIENDO')
            for key,pattern in [('tx',r'TX=([\d.]+)'),('rx',r'RX=([\d.]+)'),('capture',r'captura=([\d.]+)'),('drops',r'descartados=(\d+)')]:
                match=re.search(pattern,line)
                if match: self.metrics[key].set(match[1]+(' ms' if key=='capture' else ''))
        if self.process and self.process.poll() is not None:
            code=self.process.returncode; self.process=None
            self.status.set('DETENIDO' if code==0 else 'ERROR · REVISAR ACTIVIDAD')
            self.append(f'Servidor detenido (código {code}).')
            self.start_button.configure(state='normal'); self.stop_button.configure(state='disabled')
            for field in self.fields: field.configure(state='readonly' if isinstance(field,ttk.Combobox) else 'normal')
            if self.stop_path: self.stop_path.unlink(missing_ok=True)
        if self.closing and self.process is None: self.root.destroy(); return
        self.root.after(100,self.poll)

    def close(self):
        self.closing=True; self.stop()

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--autostart',action='store_true')
    args=parser.parse_args()
    root=tk.Tk(); app=ServerWindow(root,args.autostart); root.mainloop()
