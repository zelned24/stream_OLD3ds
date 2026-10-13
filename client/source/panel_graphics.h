#pragma once
#include <3ds.h>
#include <cstring>

// RGB565 software renderer; independent of the top screen's video buffer.
namespace panelgfx {
constexpr u16 rgb(int r,int g,int b) { return ((r>>3)<<11)|((g>>2)<<5)|(b>>3); }
constexpr u16 background=rgb(43,28,36), surface=rgb(54,47,64), selected=rgb(73,56,71);
constexpr u16 border=rgb(188,56,33), bevel=rgb(231,90,52), shadow=rgb(24,17,26);
constexpr u16 white=rgb(245,239,243), muted=rgb(184,168,185), yellow=rgb(255,234,112);
constexpr u16 purple=rgb(159,149,252), green=rgb(134,221,167);
struct Rect {
    int x,y,w,h;
    bool contains(int px,int py) const { return px>=x && px<x+w && py>=y && py<y+h; }
};
struct Canvas {
    u16* pixels;
    const u8* font;
    void pixel(int x,int y,u16 color) {
        if(x>=0 && x<320 && y>=0 && y<240) pixels[x*240+239-y]=color;
    }
    void fill(Rect r,u16 color) {
        for(int x=r.x;x<r.x+r.w;++x) for(int y=r.y;y<r.y+r.h;++y) pixel(x,y,color);
    }
    void frame(Rect r,bool active=false) {
        fill({r.x+1,r.y+2,r.w,r.h},shadow);
        fill({r.x+2,r.y,r.w-4,r.h},border);
        fill({r.x,r.y+2,r.w,r.h-4},border);
        fill({r.x+2,r.y+2,r.w-4,r.h-4},active?selected:surface);
        fill({r.x+3,r.y+2,r.w-6,1},active?yellow:bevel);
        if(active) fill({r.x+3,r.y+r.h-3,r.w-6,1},bevel);
    }
    void arrow(int x,int y,u16 color=white) {
        for(int i=0;i<5;++i) fill({x+i,y+i,1,9-2*i},color);
    }
    void bounds(unsigned char c,int& left,int& right) const {
        left=0; right=7;
        u8 bits=0; for(int y=0;y<8;++y) bits|=font[c*8+y];
        if(!bits) { right=2; return; }
        while(left<7 && !(bits&(0x80>>left))) ++left;
        while(right>left && !(bits&(0x80>>right))) --right;
    }
    int width(const char* text) const {
        int n=0,l,r; while(*text) { bounds((unsigned char)*text++,l,r); n+=r-l+2; } return n;
    }
    void text(int x,int y,const char* value,u16 color=white) {
        while(*value) {
            unsigned char c=*value++; int l,r; bounds(c,l,r);
            for(int row=0;row<8;++row) for(int col=l;col<=r;++col)
                if(font[c*8+row]&(0x80>>col)) pixel(x+col-l,y+row,color);
            x+=r-l+2;
        }
    }
    void centered(Rect r,const char* value,u16 color=white) {
        int x=r.x+(r.w-width(value))/2, y=r.y+(r.h-8)/2;
        text(x+1,y+1,value,shadow); text(x,y,value,color);
    }
};
}
