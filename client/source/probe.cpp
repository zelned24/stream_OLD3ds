// Diagnostic endpoint, UDP 5001. No browser or game required on the console.
#include <3ds.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <fcntl.h>
#include <unistd.h>
#include <malloc.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <algorithm>
#include <atomic>
#include "media.h"

static u32 read32(const u8* p) { return u32(p[0])<<24|u32(p[1])<<16|u32(p[2])<<8|p[3]; }
static unsigned read16(const u8* p) { return unsigned(p[0])<<8|p[1]; }
static void put32(u8* p,u32 v) { for(int i=3;i>=0;--i) { p[i]=v; v>>=8; } }
static double micros(u64 ticks) { return ticks/CPU_TICKS_PER_USEC; }

struct Timing {
    u32 values[2048]{}, count=0, maximum=0;
    double total=0;
    void add(u64 ticks) {
        u32 us=u32(micros(ticks)); values[count%2048]=us; ++count;
        total+=us; maximum=std::max(maximum,us);
    }
    // Percentiles cover the last 2048 samples; mean/max/count cover the stage.
    void json(char* out,size_t size) {
        unsigned n=std::min<u32>(count,2048);
        std::sort(values,values+n);
        snprintf(out,size,"[%lu,%.1f,%lu,%lu,%lu]",(unsigned long)count,
            count?total/count:0,(unsigned long)(n?values[(n-1)/2]:0),
            (unsigned long)(n?values[(n-1)*95/100]:0),(unsigned long)maximum);
    }
};

struct Decode {
    LightLock lock;
    Thread thread=nullptr;
    std::atomic<bool> running{false};
    bool pending=false,ready=false,continuous=false;
    unsigned size=0, replaced=0, skipped=0, errors=0;
    u8 input[96000], work[96000], pixels[288000], rotated[288000], output[288000];
    Timing decode,rotate;
    Decode() { LightLock_Init(&lock); }
    static void entry(void* ptr) {
        auto& s=*static_cast<Decode*>(ptr);
        tjhandle jpeg=tjInitDecompress();
        if(!jpeg) { ++s.errors; s.running=false; return; }
        unsigned bytes=0;
        while(s.running) {
            LightLock_Lock(&s.lock);
            if(s.pending) { bytes=s.size; memcpy(s.work,s.input,bytes); s.pending=false; }
            else if(!s.continuous) bytes=0;
            LightLock_Unlock(&s.lock);
            if(!bytes) { svcSleepThread(1000000); continue; }
            int w,h,sub,col;
            u64 start=svcGetSystemTick();
            if(tjDecompressHeader3(jpeg,s.work,bytes,&w,&h,&sub,&col) ||
               !((w==400&&h==240)||(w==320&&h==192)) ||
               tjDecompress2(jpeg,s.work,bytes,s.pixels,w,0,h,TJPF_BGR,0)) {
                ++s.errors; bytes=0; continue;
            }
            s.decode.add(svcGetSystemTick()-start);
            if(s.continuous) continue; // Isolate decoder from framebuffer work.
            start=svcGetSystemTick();
            unsigned rows[240],cols[400];
            for(unsigned y=0;y<240;++y) rows[y]=(y*unsigned(h)/240)*unsigned(w)*3;
            for(unsigned x=0;x<400;++x) cols[x]=(x*unsigned(w)/400)*3;
            for(unsigned x=0;x<400;++x) {
                u8* dst=s.rotated+x*720;
                for(unsigned y=0;y<240;++y) {
                    const u8* src=s.pixels+rows[239-y]+cols[x];
                    *dst++=src[0]; *dst++=src[1]; *dst++=src[2];
                }
            }
            s.rotate.add(svcGetSystemTick()-start);
            LightLock_Lock(&s.lock);
            if(s.ready) ++s.skipped;
            memcpy(s.output,s.rotated,sizeof(s.output)); s.ready=true;
            LightLock_Unlock(&s.lock);
        }
        tjDestroy(jpeg);
    }
    void stop() {
        running=false;
        if(thread) { threadJoin(thread,UINT64_MAX); threadFree(thread); thread=nullptr; }
    }
    void clear() { stop(); pending=ready=false; replaced=skipped=errors=0; decode={}; rotate={}; }
    void submit(const u8* data,unsigned length) {
        LightLock_Lock(&lock);
        if(pending) ++replaced;
        memcpy(input,data,length); size=length; pending=true;
        LightLock_Unlock(&lock);
    }
    bool start(bool local) {
        continuous=local; running=true;
        thread=threadCreate(entry,this,64*1024,0x31,-2,false);
        if(!thread) { running=false; ++errors; }
        return thread!=nullptr;
    }
};
static Decode decoder;
static AudioPlayer audio;
static u8 assembly[96000], seen[80], netSeen[32768], renderImage[288000];
static Timing copyTime,flushTime,frameTime,assemblyTime,loopTime,arrivalTime;
static char report[1400];

int main() {
    gfxInitDefault(); gfxSet3D(false); consoleInit(GFX_BOTTOM,nullptr);
    char ip[64]="";
    if(FILE* f=fopen("sdmc:/3ds/rogue_stream/server.txt","r")) {
        if(fgets(ip,sizeof(ip),f)) ip[strcspn(ip,"\r\n \t")]=0;
        fclose(f);
    }
    auto* memory=static_cast<u32*>(memalign(0x1000,0x100000));
    bool soc=memory&&R_SUCCEEDED(socInit(memory,0x100000));
    sockaddr_in remote{}; remote.sin_family=AF_INET; remote.sin_port=htons(5001);
    int fd=-1;
    if(soc&&inet_pton(AF_INET,ip,&remote.sin_addr)==1) {
        fd=socket(AF_INET,SOCK_DGRAM,IPPROTO_UDP);
        if(fd>=0) {
            int buffer=256*1024; setsockopt(fd,SOL_SOCKET,SO_RCVBUF,&buffer,sizeof(buffer));
            if(fcntl(fd,F_SETFL,O_NONBLOCK)<0||connect(fd,(sockaddr*)&remote,sizeof(remote))<0) {
                close(fd); fd=-1;
            }
        }
    }
    bool isNew=false; APT_CheckNew3DS(&isNew); audio.start();
    for(unsigned i=0;i<sizeof(renderImage);++i) renderImage[i]=u8(i/3);
    auto sendMessage=[&](const char* magic,u32 id,u32 value) {
        u8 msg[12]; memcpy(msg,magic,4); put32(msg+4,id); put32(msg+8,value);
        if(fd>=0) send(fd,msg,sizeof(msg),0);
    };
    u32 session=u32(svcGetSystemTick()),stage=0,kind=0,duration=0,flags=0;
    bool enabled=false,active=false,loaded=false,finished=false,aborted=false;
    u32 unique=0,bytes=0,duplicates=0,reordered=0,highest=0,invalid=0;
    u32 complete=0,shown=0,incomplete=0,audioPackets=0,underruns=0,inputSeq=0;
    u32 frame=0,total=0,received=0; bool haveFrame=false;
    u64 started=0,firstPacket=0,lastPacket=0,frameStart=0,lastShown=0;
    u64 heartbeat=0,lastReport=0,lastDraw=0,previousLoop=0,lastInput=0;
    size_t reportLength=0;
    auto finish=[&]() {
        if(!active) return;
        active=false;
        decoder.stop(); audio.reset();
        u64 elapsed=svcGetSystemTick()-started;
        unsigned maxGap=0,gap=0;
        if(kind==0&&unique) for(u32 seq=0;seq<=highest;++seq) {
            if(netSeen[seq/8]&(1<<(seq%8))) gap=0;
            else { ++gap; maxGap=std::max(maxGap,gap); }
        }
        if(haveFrame&&received!=(total+1199)/1200) ++incomplete;
        char d[100],r[100],c[100],f[100],v[100],a[100],l[100],j[100];
        decoder.decode.json(d,sizeof(d)); decoder.rotate.json(r,sizeof(r));
        copyTime.json(c,sizeof(c)); flushTime.json(f,sizeof(f)); frameTime.json(v,sizeof(v));
        assemblyTime.json(a,sizeof(a)); loopTime.json(l,sizeof(l)); arrivalTime.json(j,sizeof(j));
        memcpy(report,"RBR1",4); put32((u8*)report+4,stage);
        int length=snprintf(report+8,sizeof(report)-8,
            "{\"ms\":%.1f,\"unique\":%lu,\"bytes\":%lu,\"duplicate\":%lu,\"reorder\":%lu,"
            "\"invalid\":%lu,\"complete\":%lu,\"shown\":%lu,\"incomplete\":%lu,\"highest\":%lu,\"max_gap\":%u,"
            "\"replaced\":%u,\"skipped\":%u,\"decode_errors\":%u,\"audio_packets\":%lu,"
            "\"underruns\":%lu,\"dsp\":%s,\"aborted\":%s,"
            "\"decode_us\":%s,\"rotate_us\":%s,\"copy_us\":%s,\"flush_us\":%s,"
            "\"frame_interval_us\":%s,\"assembly_us\":%s,\"loop_us\":%s,\"arrival_us\":%s}",
            micros(elapsed)/1000,(unsigned long)unique,(unsigned long)bytes,(unsigned long)duplicates,
            (unsigned long)reordered,(unsigned long)invalid,(unsigned long)complete,(unsigned long)shown,
            (unsigned long)incomplete,(unsigned long)highest,maxGap,decoder.replaced,decoder.skipped,decoder.errors,
            (unsigned long)audioPackets,(unsigned long)underruns,audio.available?"true":"false",
            aborted?"true":"false",d,r,c,f,v,a,l,j);
        reportLength=length>0&&size_t(length)<sizeof(report)-8?size_t(length)+8:0;
        finished=true; lastReport=0;
    };
    printf("ROGUE PROBE v1\n\nPC: %s :5001\n%s\nDSP: %s\n\nA: conectar e iniciar pruebas\nB: cancelar bateria\nSTART: salir\n\nEjecuta diagnostics.py en la PC.\n",ip,
        fd>=0?"Red preparada":"ERROR: revisar server.txt / Wi-Fi",audio.available?"listo":"no disponible");
    while(aptMainLoop()) {
        hidScanInput(); u32 down=hidKeysDown(); u64 now=osGetTime();
        if(down&KEY_START) { aborted=true; finish(); if(reportLength) send(fd,report,reportLength,0); sendMessage("RBQ1",stage,0); break; }
        if(down&KEY_A&&!enabled&&fd>=0) { enabled=true; stage=0; finished=false; reportLength=0; heartbeat=0; }
        if(down&KEY_B) {
            aborted=true; finish(); sendMessage("RBQ1",stage,0); enabled=false;
            printf("\x1b[1;1HDiagnostico cancelado.               \nEtapas previas guardadas en la PC.   \nA: nueva sesion | START: salir       \n");
            gfxFlushBuffers();
        }
        if(enabled&&now-heartbeat>=500) { sendMessage("RBH1",session,isNew?2:1); heartbeat=now; }
        if(active) {
            u64 tick=svcGetSystemTick();
            if(previousLoop) loopTime.add(tick-previousLoop);
            previousLoop=tick;
            if(now-lastInput>=50 || down) {
                sendMessage("RBU1",stage,++inputSeq); lastInput=now;
            }
        }
        u8 packet[1500]; u64 budget=osGetTime();
        for(int nPackets=0;fd>=0&&nPackets<256&&osGetTime()-budget<6;++nPackets) {
            int n=recv(fd,packet,sizeof(packet),0); if(n<0) break;
            if(n==12&&!memcmp(packet,"RBP1",4)) { send(fd,packet,n,0); continue; }
            if(n==24&&!memcmp(packet,"RBG1",4)&&enabled) {
                u32 next=read32(packet+4),k=read32(packet+8),ms=read32(packet+12),fl=read32(packet+16);
                if(k>3||ms<1000||ms>60000||fl>1||read32(packet+20)!=1) continue;
                if(next==stage) { sendMessage("RBA1",stage,0); continue; }
                if(active||next<stage) continue;
                decoder.clear(); audio.reset();
                stage=next; kind=k; duration=ms; flags=fl;
                finished=loaded=aborted=haveFrame=false; reportLength=0;
                unique=bytes=duplicates=reordered=highest=invalid=complete=shown=incomplete=0;
                audioPackets=underruns=inputSeq=0; total=received=frame=0;
                firstPacket=lastPacket=lastShown=previousLoop=0;
                copyTime={}; flushTime={}; frameTime={}; assemblyTime={}; loopTime={}; arrivalTime={};
                memset(netSeen,0,sizeof(netSeen)); memset(seen,0,sizeof(seen));
                sendMessage("RBA1",stage,0); continue;
            }
            if(n<8||read32(packet+4)!=stage||!stage) continue;
            if(n==12&&!memcmp(packet,"RBF1",4)) {
                finish(); enabled=false;
                printf("\x1b[1;1HPruebas terminadas.                 \nInforme guardado en la PC.           \nA: nueva sesion | START: salir       \n");
                gfxFlushBuffers(); continue;
            }
            if(n==12&&!memcmp(packet,"RBA1",4)&&read32(packet+8)==3) { reportLength=0; continue; }
            if(n==12&&!memcmp(packet,"RBS1",4)) {
                if(finished) continue;
                if(!active) {
                    if(kind==1&&!loaded) continue;
                    if(kind==1||kind==2) decoder.start(kind==1);
                    active=true; started=svcGetSystemTick(); previousLoop=0;
                }
                sendMessage("RBA1",stage,1); continue;
            }
            if(n==12&&!memcmp(packet,"RBE1",4)) { finish(); continue; }
            if(active&&n==332&&!memcmp(packet,"RBO1",4)&&flags) {
                if(audioPackets&&!audio.priming&&audio.available) {
                    bool queued=false;
                    for(auto& b:audio.buffers) if(b.status==NDSP_WBUF_QUEUED||b.status==NDSP_WBUF_PLAYING) queued=true;
                    if(!queued) ++underruns;
                }
                audio.packet(read32(packet+8),packet+12); ++audioPackets; continue;
            }
            if(active&&kind==0&&n>=12&&n<=1212&&!memcmp(packet,"RBN1",4)) {
                u32 seq=read32(packet+8);
                if(seq>=sizeof(netSeen)*8) { ++invalid; continue; }
                if(netSeen[seq/8]&(1<<(seq%8))) { ++duplicates; continue; }
                netSeen[seq/8]|=1<<(seq%8); ++unique; bytes+=n;
                if(unique>1&&seq<highest) ++reordered;
                highest=std::max(highest,seq);
                u64 tick=svcGetSystemTick();
                if(lastPacket) arrivalTime.add(tick-lastPacket);
                if(!firstPacket) firstPacket=tick;
                lastPacket=tick; continue;
            }
            if(n>=21&&n<=1220&&!memcmp(packet,"RBD1",4)&&((kind==1&&!active)||(kind==2&&active))) {
                u32 seq=read32(packet+8),size=read32(packet+16);
                unsigned index=read16(packet+12),count=read16(packet+14);
                if(!size||size>96000||count!=(size+1199)/1200||index>=count) { ++invalid; continue; }
                unsigned length=std::min<u32>(1200,size-index*1200);
                if(unsigned(n)!=20+length) { ++invalid; continue; }
                if(kind==1&&loaded) { sendMessage("RBA1",stage,2); continue; }
                if(haveFrame&&seq!=frame&&u32(seq-frame)>=0x80000000u) { ++reordered; continue; }
                if(!haveFrame||seq!=frame) {
                    if(haveFrame&&received!=(total+1199)/1200) ++incomplete;
                    haveFrame=true; frame=seq; total=size; received=0; memset(seen,0,sizeof(seen));
                    frameStart=svcGetSystemTick();
                }
                if(total!=size) { ++invalid; continue; }
                if(seen[index]) { ++duplicates; continue; }
                seen[index]=1; ++received; ++unique; bytes+=n;
                memcpy(assembly+index*1200,packet+20,length);
                if(received==count) {
                    if(kind==2) { ++complete; assemblyTime.add(svcGetSystemTick()-frameStart); }
                    decoder.submit(assembly,size);
                    if(kind==1) { loaded=true; sendMessage("RBA1",stage,2); }
                }
                continue;
            }
        }
        bool draw=false;
        if(active&&kind==2&&LightLock_TryLock(&decoder.lock)==0) {
            if(decoder.ready) {
                u64 tick=svcGetSystemTick(); memcpy(gfxGetFramebuffer(GFX_TOP,GFX_LEFT,nullptr,nullptr),decoder.output,288000);
                copyTime.add(svcGetSystemTick()-tick); decoder.ready=false; draw=true;
            }
            LightLock_Unlock(&decoder.lock);
        } else if(active&&kind==3) {
            u64 tick=svcGetSystemTick(); memcpy(gfxGetFramebuffer(GFX_TOP,GFX_LEFT,nullptr,nullptr),renderImage,288000);
            copyTime.add(svcGetSystemTick()-tick); draw=true;
        }
        if(draw) {
            u64 tick=svcGetSystemTick(); gfxFlushBuffers(); gfxScreenSwapBuffers(GFX_TOP,false);
            flushTime.add(svcGetSystemTick()-tick); ++shown;
            if(lastShown) frameTime.add(tick-lastShown);
            lastShown=tick;
        }
        if(active&&micros(svcGetSystemTick()-started)/1000>duration+1500) { aborted=true; finish(); }
        audio.tick(!active);
        if(reportLength&&now-lastReport>=250) { send(fd,report,reportLength,0); lastReport=now; }
        if(enabled&&now-lastDraw>=1000) {
            printf("\x1b[1;1HROGUE PROBE v1   %s\nPC %s:5001\nEtapa %lu   modo %lu\n%s                      \nRX %lu paquetes             \nFrames %lu / mostrados %lu    \nB cancela | START sale\n",
                isNew?"New3DS":"Old3DS",ip,(unsigned long)stage,(unsigned long)kind,
                active?"Midiendo en consola":finished?"Etapa terminada":"Esperando servidor",
                (unsigned long)unique,(unsigned long)complete,(unsigned long)shown);
            lastDraw=now;
            gfxFlushBuffers();
        }
        if(active&&(kind==2||kind==3)) gspWaitForVBlank();
        else svcSleepThread(1000000);
    }
    decoder.stop(); audio.stop(); if(fd>=0) close(fd);
    if(soc) socExit();
    free(memory); gfxExit(); return 0;
}
