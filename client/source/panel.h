#pragma once
#include <3ds.h>
#include <cstdio>
#include <cstring>
#include "panel_graphics.h"

static constexpr int fpsOptions[]={10,15,20,30,45,60};
static constexpr const char* keyLabels[]={"Sin asignar","Arriba","Abajo","Izquierda","Derecha",
    "Z / confirmar","X / cancelar","Enter","Escape","C","V","Q","E","Espacio","Shift"};
static constexpr const char* keyLabelsShort[]={
    "Sin asignar","Arriba","Abajo",
    "Izquierda","Derecha","Z / Conf",
    "X / Canc","Enter","Escape",
    "C","V","Q",
    "E","Espacio","Shift"
};
static constexpr u8 defaultMapping[]={5,6,9,10,11,12,7};
struct Panel {
    bool menu=false, paused=false, dirty=true, reconnect=false, quit=false;
    bool picking=false;
    int pickerItem=0, pickerSelected=0;
    int tab=0, selected=0, fpsIndex=3, mode=2;
    bool audioAvailable=false;
    u8 mapping[7]={5,6,9,10,11,12,7};
    u32 revision=1, acknowledged=0;
    float fps=0, kbps=0;
    u32 dropped=0, ping=0, recovered=0;
    bool online=false;
    static constexpr panelgfx::Rect accept{12,185,142,36}, back{166,185,142,36};
    int count() const { return tab==0?3:tab==1?8:2; }
    void changed() { ++revision; dirty=true; }
    void activate(int direction) {
        if(tab==0) {
            if(selected==0) fpsIndex=(fpsIndex+direction+6)%6;
            if(selected==1) mode=(mode+direction+3)%3;
            if(selected==2) paused=!paused;
            changed();
        } else if(tab==1) {
            if(selected<7) {
                picking=true; pickerItem=selected; pickerSelected=mapping[selected];
                dirty=true;
            } else {
                memcpy(mapping,defaultMapping,7);
                changed();
            }
        } else {
            if(selected==0) reconnect=true; else quit=true;
            dirty=true;
        }
    }
    panelgfx::Rect itemRect(int item) const {
        if(tab==0) return item<2?panelgfx::Rect{12+154*item,92,142,38}:panelgfx::Rect{12,138,296,28};
        if(tab==1) return {12+154*(item%2),92+40*((item%4)/2),142,32};
        return {12+154*item,134,142,32};
    }
    panelgfx::Rect pickerRect(int k) const {
        int col=k%3, row=k/3;
        return {12+col*100, 42+row*30, 96, 26};
    }
    void touch(int x,int y) {
        if(picking) {
            if(panelgfx::Rect{12,198,296,28}.contains(x,y)) {
                picking=false; dirty=true; return;
            }
            for(int k=0;k<15;++k) {
                if(pickerRect(k).contains(x,y)) {
                    mapping[pickerItem]=k;
                    picking=false;
                    changed(); dirty=true; return;
                }
            }
            return;
        }
        for(int i=0;i<3;++i) if(panelgfx::Rect{12+101*i,44,94,26}.contains(x,y)) {
            tab=i; selected=0; menu=true; dirty=true; return;
        }
        if(back.contains(x,y)) { menu=false; dirty=true; return; }
        if(accept.contains(x,y)) {
            if(!menu) menu=true; else activate(1);
            dirty=true; return;
        }
        if(tab==1 && panelgfx::Rect{238,73,70,15}.contains(x,y)) {
            selected=selected<4?4:0; menu=true; dirty=true; return;
        }
        int first=tab==1?(selected/4)*4:0, last=tab==1?first+4:count();
        for(int i=first;i<last;++i) if(itemRect(i).contains(x,y)) {
            if(tab==1 && i<7) {
                selected=i; picking=true; pickerItem=i; pickerSelected=mapping[i];
                menu=true; dirty=true; return;
            }
            if(menu && selected==i) activate(1);
            selected=i; menu=true; dirty=true; return;
        }
    }
    void input(u32 down) {
        if(down & KEY_SELECT) {
            if(picking) picking=false;
            else menu=!menu;
            dirty=true; return;
        }
        if(down & KEY_TOUCH) { touchPosition p; hidTouchRead(&p); touch(p.px,p.py); }
        if(picking) {
            if(down & KEY_B) { picking=false; dirty=true; return; }
            if(down & KEY_A) {
                mapping[pickerItem]=pickerSelected;
                picking=false;
                changed(); dirty=true; return;
            }
            if(down & KEY_DUP) { pickerSelected=(pickerSelected+12)%15; dirty=true; }
            if(down & KEY_DDOWN) { pickerSelected=(pickerSelected+3)%15; dirty=true; }
            if(down & KEY_DLEFT) { pickerSelected=(pickerSelected+14)%15; dirty=true; }
            if(down & KEY_DRIGHT) { pickerSelected=(pickerSelected+1)%15; dirty=true; }
            return;
        }
        if(!menu) return;
        if(down & KEY_B) { menu=false; dirty=true; return; }
        if(down & KEY_L) { tab=(tab+2)%3; selected=0; dirty=true; }
        if(down & KEY_R) { tab=(tab+1)%3; selected=0; dirty=true; }
        if(down & KEY_DUP) { selected=(selected+count()-1)%count(); dirty=true; }
        if(down & KEY_DDOWN) { selected=(selected+1)%count(); dirty=true; }
        if(down & KEY_DLEFT) activate(-1);
        if(down & KEY_DRIGHT) activate(1);
        if(down & KEY_A) {
            if(tab==1 && selected<7) {
                picking=true; pickerItem=selected; pickerSelected=mapping[selected];
                dirty=true; return;
            }
            activate(1);
        }
    }
    void draw(const char* ip) {
        if(!dirty) return;
        using namespace panelgfx;
        Canvas c{reinterpret_cast<u16*>(gfxGetFramebuffer(GFX_BOTTOM,GFX_LEFT,nullptr,nullptr)),consoleGetDefault()->font.gfx};
        if(picking) {
            c.fill({0,0,320,240},background);
            const char* names[]={"A","B","X","Y","L","R","Start"};
            char title[64];
            snprintf(title,sizeof(title),"Asignar tecla para boton: %s",names[pickerItem]);
            c.frame({12,8,296,28}); c.text(24,18,title,yellow);
            for(int k=0;k<15;++k) {
                Rect r=pickerRect(k);
                bool isCurrent=mapping[pickerItem]==k;
                bool isFocused=pickerSelected==k;
                c.frame(r,isFocused);
                if(isFocused) c.arrow(r.x+6,r.y+9);
                c.centered(r,keyLabelsShort[k],isFocused?yellow:(isCurrent?green:white));
            }
            Rect rCancel{12,198,296,28};
            c.frame(rCancel);
            c.centered(rCancel,"B: Cancelar  |  Toca una tecla para asignar",muted);
            dirty=false;
            return;
        }
        c.fill({0,0,320,240},background);
        c.frame({12,8,296,28}); c.text(24,18,"Configuracion del stream");
        c.fill({291,18,7,7},online?green:border);
        const char* tabs[]={"Video","Botones","Red"};
        for(int i=0;i<3;++i) { Rect r{12+101*i,44,94,26}; c.frame(r,tab==i); c.centered(r,tabs[i],tab==i?yellow:white); }
        char text[96];
        if(tab==1) {
            snprintf(text,sizeof(text),"Mapeo de botones  %d/2",selected/4+1); c.text(14,78,text,muted);
            c.frame({238,73,70,15}); c.centered({238,73,70,15},"< Pagina >",purple);
            const char* names[]={"A","B","X","Y","L","R","Start","Restaurar"};
            int first=(selected/4)*4;
            for(int i=first;i<first+4;++i) {
                Rect r=itemRect(i); bool active=menu&&selected==i;
                c.frame(r,active); if(active) c.arrow(r.x+7,r.y+11);
                c.text(r.x+20,r.y+6,names[i],yellow);
                c.text(r.x+20,r.y+18,i<7?keyLabels[mapping[i]]:"Mapa original",white);
            }
        } else {
            snprintf(text,sizeof(text),"%s   %.1f FPS   %ums RTT",online?"En linea":"Sin conexion",fps,(unsigned)ping);
            c.text(14,78,text,online?green:muted);
            if(tab==0) {
                for(int i=0;i<3;++i) {
                    Rect r=itemRect(i); bool active=menu&&selected==i;
                    c.frame(r,active); if(active) c.arrow(r.x+7,r.y+(r.h-9)/2);
                    if(i==0) {
                        c.text(r.x+20,r.y+7,"FPS objetivo",muted);
                        snprintf(text,sizeof(text),"< %d FPS >",fpsOptions[fpsIndex]); c.text(r.x+20,r.y+22,text,yellow);
                    } else if(i==1) {
                        c.text(r.x+20,r.y+7,"Resolucion",muted);
                        c.text(r.x+20,r.y+22,mode==1?"200x120 fluido":mode==2?"320x192 JPEG":"400x240 JPEG",yellow);
                    } else c.centered(r,paused?"Video en pausa / reanudar":"Video activo / pausar",white);
                }
            } else {
                c.text(16,96,"Servidor",muted); c.text(83,96,ip,white);
                snprintf(text,sizeof(text),"%.0f KB/s  Drop:%lu FEC:%lu",kbps,(unsigned long)dropped,(unsigned long)recovered); c.text(16,111,text,muted);
                c.text(16,122,audioAvailable?"Audio DSP listo":"Audio: falta DSP firmware",muted);
                for(int i=0;i<2;++i) {
                    Rect r=itemRect(i); c.frame(r,menu&&selected==i);
                    if(menu&&selected==i) c.arrow(r.x+7,r.y+11);
                    c.centered(r,i==0?"Reconectar":"Salir del cliente",i==0?white:purple);
                }
            }
        }
        c.text(14,174,acknowledged==revision?"Ajustes sincronizados":"Aplicando ajustes...",muted);
        c.frame(accept); c.centered(accept,menu?"A: Elegir":"SELECT: Ajustes",yellow);
        c.frame(back); c.centered(back,"B: Jugar",purple);
        c.text(14,229,menu?"UP/DOWN elegir  A: Asignar  L/R pestana":"Toca una opcion o pulsa SELECT",white);
        dirty=false;
    }
};
