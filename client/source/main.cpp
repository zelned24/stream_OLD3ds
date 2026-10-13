#include <3ds.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <fcntl.h>
#include <unistd.h>
#include <malloc.h>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cerrno>
#include "panel.h"
#include "media.h"
static JpegWorker jpeg;
static AudioPlayer audio;

// Change to the LAN IPv4 of the PC.
#ifndef STREAM_SERVER_IP
#define STREAM_SERVER_IP "192.168.1.100"
#endif
static char SERVER_IP[INET_ADDRSTRLEN] = STREAM_SERVER_IP;
static unsigned char assembly[96000], latest[96000], seen[80];
static unsigned char repair[1200];
static unsigned read16(const unsigned char* p) { return (p[0]<<8)|p[1]; }
static u32 read32(const unsigned char* p) { return (u32(p[0])<<24)|(u32(p[1])<<16)|(u32(p[2])<<8)|p[3]; }
static void put32(unsigned char* p, u32 n) { for(int i=3;i>=0;--i) { p[i]=n; n>>=8; } }

static int openSocket(const sockaddr_in& server) {
    int fd=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
    if(fd<0) return -1;
    int receiveBuffer=256*1024;
    setsockopt(fd,SOL_SOCKET,SO_RCVBUF,&receiveBuffer,sizeof(receiveBuffer));
    int flags=fcntl(fd,F_GETFL,0);
    if(flags<0 || fcntl(fd,F_SETFL,flags|O_NONBLOCK)<0 ||
       connect(fd,reinterpret_cast<const sockaddr*>(&server),sizeof(server))<0) {
        close(fd); return -1;
    }
    return fd;
}

int main() {
    gfxInit(GSP_BGR8_OES,GSP_RGB565_OES,false);
    gfxSet3D(false);
    // Optional SD configuration avoids recompiling when the PC address changes.
    if(FILE* config=fopen("sdmc:/3ds/rogue_stream/server.txt","r")) {
        char candidate[64]; in_addr parsed{};
        if(fgets(candidate,sizeof(candidate),config)) {
            candidate[strcspn(candidate,"\r\n \t")]=0;
            if(inet_pton(AF_INET,candidate,&parsed)==1) inet_ntop(AF_INET,&parsed,SERVER_IP,sizeof(SERVER_IP));
        }
        fclose(config);
    }
    auto* socBuffer = static_cast<u32*>(memalign(0x1000, 0x100000));
    bool socReady = socBuffer && R_SUCCEEDED(socInit(socBuffer, 0x100000));
    int fd = -1;
    sockaddr_in server{};
    server.sin_family=AF_INET; server.sin_port=htons(5000);
    bool addressValid=inet_pton(AF_INET,SERVER_IP,&server.sin_addr)==1;
    if(socReady && addressValid) fd=openSocket(server);
    bool ready=fd>=0;
    Panel panel;
    jpeg.start(); audio.start(); panel.audioAvailable=audio.available;
    u32 inputSeq=0, frameSeq=0;
    unsigned received=0;
    bool frameJpeg=false;
    bool haveRepair=false;
    unsigned frameSize=96000, latestSize=96000;
    bool haveSeq=false, haveImage=false;
    u16 previous=0xffff;
    u64 lastSend=0, frameStarted=0, lastStats=0;
    u64 lastConfig=0, lastPong=0, lastImage=0, lastRetry=0;
    u32 sentConfig=0, suppressed=0, oldCompleted=0;
    u32 completed=0, discarded=0, packets=0, videoBytes=0, oldVideoBytes=0;
    u8 colors[256][3];
    for(unsigned v=0;v<256;++v) {
        colors[v][0]=(v&3)*85; colors[v][1]=((v>>2)&7)*255/7; colors[v][2]=(v>>5)*255/7;
    }
    while(aptMainLoop()) {
        hidScanInput();
        u32 down=hidKeysDown(), held=hidKeysHeld();
        bool wasMenu=panel.menu;
        panel.input(down);
        if(panel.quit) break;
        if(wasMenu || panel.menu || panel.paused) suppressed|=held;
        suppressed &= held;
        const u32 keys[]={KEY_DUP,KEY_DDOWN,KEY_DLEFT,KEY_DRIGHT,KEY_A,KEY_B,KEY_START,KEY_X,KEY_Y,KEY_L,KEY_R};
        u16 mask=0;
        for(unsigned i=0;i<11;++i) if((held & ~suppressed) & keys[i]) mask|=1<<i;
        u64 now=osGetTime();
        if(panel.reconnect || (!ready && now-lastRetry>=1000)) {
            if(fd>=0) close(fd);
            fd=socReady&&addressValid?openSocket(server):-1;
            ready=fd>=0; panel.reconnect=false; panel.acknowledged=0;
            haveSeq=false; lastRetry=now; lastSend=0; lastConfig=0;
        }
        if(haveSeq && now-lastImage>2000 && now-frameStarted>2000) haveSeq=false;
        bool newImage=false;
        if(ready && (mask!=previous || now-lastSend>=50)) {
            unsigned char packet[10]={'P','R','I','1'};
            put32(packet+4,++inputSeq); packet[8]=mask>>8; packet[9]=mask;
            if(send(fd,packet,sizeof(packet),0)==sizeof(packet)) { previous=mask; lastSend=now; }
        }
        if(ready && (sentConfig!=panel.revision || now-lastConfig>=500)) {
            unsigned char config[19]={'P','R','C','2'};
            put32(config+4,panel.revision); config[8]=fpsOptions[panel.fpsIndex];
            config[9]=panel.mode; config[10]=panel.paused;
            memcpy(config+12,panel.mapping,7);
            if(send(fd,config,sizeof(config),0)==sizeof(config)) { lastConfig=now; sentConfig=panel.revision; }
        }
        // Both time and packet budgets prevent receive traffic starving HID.
        unsigned char packet[1217];
        u64 budgetStart=osGetTime();
        for(unsigned work=0;ready && work<256 && osGetTime()-budgetStart<10;++work) {
            int n=recv(fd,packet,sizeof(packet),0);
            if(n<0) {
                if(errno!=EAGAIN && errno!=EWOULDBLOCK) { ready=false; panel.dirty=true; }
                break;
            }
            if(n==19 && memcmp(packet,"PRA2",4)==0) {
                if(read32(packet+4)==panel.revision && panel.acknowledged!=panel.revision) {
                    for(int i=0;i<6;++i) if(fpsOptions[i]==packet[8]) panel.fpsIndex=i;
                    panel.mode=packet[9]<=2?packet[9]:1; panel.paused=packet[10]!=0;
                    for(int i=0;i<7;++i) if(packet[12+i]<15) panel.mapping[i]=packet[12+i];
                    panel.acknowledged=panel.revision; panel.dirty=true;
                }
                continue;
            }
            if(n==8 && memcmp(packet,"PRP1",4)==0) {
                panel.ping=u32(osGetTime())-read32(packet+4); lastPong=osGetTime(); continue;
            }
            if(n==328 && memcmp(packet,"PAU1",4)==0) {
                if(!panel.paused) audio.packet(read32(packet+4),packet+8);
                continue;
            }
            if(n<17 || n>1216) continue;
            bool isRepair=memcmp(packet,"PRX1",4)==0;
            bool isJpeg=isRepair || memcmp(packet,"PRJ1",4)==0;
            if(!isJpeg && memcmp(packet,"PRF2",4)!=0) continue;
            u32 seq=read32(packet+4);
            unsigned index=read16(packet+8);
            unsigned size=read32(packet+12), count=read16(packet+10);
            if(!size || size>96000 || count!=(size+1199)/1200 || index>=count) continue;
            if(!isJpeg && size!=24000) continue;
            unsigned payload=(index+1==count)?size-index*1200:1200;
            if(isRepair) {
                if(index!=0 || n!=1216) continue;
            } else if(unsigned(n)!=16+payload) continue;
            ++packets;
            videoBytes+=n;
            if(haveSeq && seq!=frameSeq && (seq-frameSeq)>=0x80000000u) continue;
            if(!haveSeq || seq!=frameSeq) {
                if(haveSeq && received!=(frameSize+1199)/1200) ++discarded;
                frameSeq=seq; haveSeq=true; received=0; frameStarted=osGetTime();
                frameSize=size; frameJpeg=isJpeg;
                memset(seen,0,sizeof(seen));
                haveRepair=false;
            }
            if(size!=frameSize || frameJpeg!=isJpeg) continue;
            if(osGetTime()-frameStarted>300 || received==count) continue;
            if(isRepair) {
                if(haveRepair) continue;
                memcpy(repair,packet+16,1200); haveRepair=true;
            } else {
                if(seen[index]) continue;
                memcpy(assembly+index*1200,packet+16,payload);
                seen[index]=1; ++received;
            }
            // Recover exactly one erasure, including the short final fragment.
            // Works when parity precedes data; never decode an incomplete JPEG.
            if(haveRepair && received+1==count) {
                unsigned missing=0;
                for(unsigned i=0;i<count;++i) {
                    if(!seen[i]) { missing=i; continue; }
                    unsigned length=(i+1==count)?size-i*1200:1200;
                    for(unsigned j=0;j<length;++j) repair[j]^=assembly[i*1200+j];
                }
                unsigned length=(missing+1==count)?size-missing*1200:1200;
                memcpy(assembly+missing*1200,repair,length);
                seen[missing]=1; ++received;
                ++panel.recovered;
            }
            if(received==count) {
                lastImage=osGetTime();
                if(isJpeg) jpeg.submit(assembly,size);
                else { memcpy(latest,assembly,size); latestSize=size; haveImage=true; newImage=true; ++completed; }
            }
        }
        if(haveImage && newImage) {
            // libctru framebuffer is column-major, bottom-to-top, BGR8.
            u8* fb=gfxGetFramebuffer(GFX_TOP,GFX_LEFT,nullptr,nullptr);
            for(unsigned x=0;x<400;++x) for(unsigned y=0;y<240;++y) {
                unsigned src=latestSize==24000?(y/2)*200+x/2:y*400+x;
                unsigned v=latest[src], dst=3*(x*240+239-y);
                fb[dst]=colors[v][0]; fb[dst+1]=colors[v][1]; fb[dst+2]=colors[v][2];
            }
        }
        if(panel.mode!=1 && jpeg.present(gfxGetFramebuffer(GFX_TOP,GFX_LEFT,nullptr,nullptr))) {
            newImage=true; ++completed;
        }
        audio.tick(panel.paused);
        if(ready && now-lastStats>=1000) {
            float elapsed=(now-lastStats)/1000.0f;
            panel.fps=(completed-oldCompleted)/elapsed;
            panel.kbps=(videoBytes-oldVideoBytes)/1024.0f/elapsed;
            panel.dropped=discarded; panel.dirty=true;
            oldCompleted=completed;
            oldVideoBytes=videoBytes;
            unsigned char stats[20]={'P','R','S','1'};
            put32(stats+4,frameSeq); put32(stats+8,completed);
            put32(stats+12,discarded); put32(stats+16,packets);
            send(fd,stats,sizeof(stats),0); lastStats=now;
            unsigned char ping[8]={'P','R','P','1'};
            put32(ping+4,u32(now)); send(fd,ping,sizeof(ping),0);
        }
        bool online=lastPong && now-lastPong<2000;
        if(panel.online!=online) { panel.online=online; panel.dirty=true; }
        bool redraw=panel.dirty;
        panel.draw(SERVER_IP);
        if(redraw || newImage) gfxFlushBuffers();
        if(newImage) gfxScreenSwapBuffers(GFX_TOP,false);
        if(redraw) gfxScreenSwapBuffers(GFX_BOTTOM,false);
        gspWaitForVBlank();
    }
    if(fd>=0) {
        unsigned char release[10]={'P','R','I','1'}; put32(release+4,++inputSeq);
        send(fd,release,sizeof(release),0); close(fd);
    }
    jpeg.stop(); audio.stop();
    if(socReady) socExit();
    free(socBuffer); gfxExit(); return 0;
}
