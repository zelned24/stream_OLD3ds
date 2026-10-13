#pragma once
#include <3ds.h>
#include <turbojpeg.h>
#include <atomic>
#include <cstring>

// JPEG runs off the HID/network thread; single pending frame replaces stale work.
struct JpegWorker {
    LightLock lock;
    Thread thread=nullptr;
    std::atomic<bool> running{false};
    bool pending=false, ready=false;
    unsigned size=0, width=0, height=0;
    u8 input[96000], work[96000], decoded[400*240*3], output[400*240*3];
    JpegWorker() { LightLock_Init(&lock); }
    static void entry(void* argument) {
        auto& self=*static_cast<JpegWorker*>(argument);
        tjhandle decoder=tjInitDecompress();
        if(!decoder) return;
        while(self.running) {
            unsigned bytes=0;
            LightLock_Lock(&self.lock);
            if(self.pending) { bytes=self.size; memcpy(self.work,self.input,bytes); self.pending=false; }
            LightLock_Unlock(&self.lock);
            if(!bytes) { svcSleepThread(1000000); continue; }
            int w,h,sub,color;
            if(tjDecompressHeader3(decoder,self.work,bytes,&w,&h,&sub,&color)!=0) continue;
            if(!((w==400 && h==240)||(w==320 && h==192))) continue;
            if(tjDecompress2(decoder,self.work,bytes,self.decoded,w,0,h,TJPF_BGR,0)!=0) continue;
            LightLock_Lock(&self.lock);
            memcpy(self.output,self.decoded,w*h*3); self.width=w; self.height=h; self.ready=true;
            LightLock_Unlock(&self.lock);
        }
        tjDestroy(decoder);
    }
    void start() { running=true; thread=threadCreate(entry,this,64*1024,0x31,-2,false); if(!thread) running=false; }
    void submit(const u8* bytes,unsigned count) {
        if(!running || count>sizeof(input)) return;
        LightLock_Lock(&lock); memcpy(input,bytes,count); size=count; pending=true; LightLock_Unlock(&lock);
    }
    bool present(u8* fb) {
        if(LightLock_TryLock(&lock)!=0) return false;
        if(!ready) { LightLock_Unlock(&lock); return false; }
        if(width==400 && height==240) {
            const u8* src=output;
            for(unsigned y=0;y<240;++y) {
                u8* dst=fb+(239-y)*3;
                for(unsigned x=0;x<400;++x) {
                    dst[0]=src[0]; dst[1]=src[1]; dst[2]=src[2];
                    src+=3; dst+=240*3;
                }
            }
        } else {
            for(unsigned x=0;x<400;++x) for(unsigned y=0;y<240;++y) {
                unsigned src=((y*height/240)*width+x*width/400)*3, dst=(x*240+239-y)*3;
                memcpy(fb+dst,output+src,3);
            }
        }
        ready=false; LightLock_Unlock(&lock); return true;
    }
    void stop() { running=false; if(thread) { threadJoin(thread,UINT64_MAX); threadFree(thread); thread=nullptr; } }
};

struct AudioPlayer {
    static constexpr int BUFFER_COUNT = 8;
    ndspWaveBuf buffers[BUFFER_COUNT]{};
    s16* samples=nullptr;
    bool available=false, haveSequence=false, priming=true;
    u32 sequence=0;
    u64 last=0;
    static s16 decode(u8 value) {
        value=~value;
        int sample=(((value&15)<<3)+132)<<((value>>4)&7);
        return (value&128)?132-sample:sample-132;
    }
    void start() {
        if(R_FAILED(ndspInit())) return;
        samples=static_cast<s16*>(linearAlloc(BUFFER_COUNT*320*sizeof(s16)));
        if(!samples) { ndspExit(); return; }
        available=true; ndspChnReset(0); ndspChnSetRate(0,16000);
        ndspChnSetFormat(0,NDSP_FORMAT_MONO_PCM16); ndspChnSetInterp(0,NDSP_INTERP_LINEAR);
        float mix[12]{}; mix[0]=mix[1]=1; ndspChnSetMix(0,mix);
        for(int i=0;i<BUFFER_COUNT;++i) { buffers[i].data_pcm16=samples+i*320; buffers[i].nsamples=320; }
        ndspChnSetPaused(0,true);
    }
    void reset() {
        if(!available) return;
        ndspChnWaveBufClear(0); ndspChnSetPaused(0,true);
        for(auto& b:buffers) b.status=NDSP_WBUF_FREE;
        haveSequence=false; priming=true;
    }
    void packet(u32 seq,const u8* data) {
        if(!available) return;
        u64 now=osGetTime(); if(last && now-last>350) reset();
        if(haveSequence && (seq==sequence || seq-sequence>=0x80000000u)) return;
        sequence=seq; haveSequence=true; last=now;
        int queued=0; ndspWaveBuf* free=nullptr;
        for(auto& b:buffers) {
            if(b.status==NDSP_WBUF_FREE || b.status==NDSP_WBUF_DONE) { if(!free) free=&b; }
            else ++queued;
        }
        if(!free) return; // Bounded to 160 ms (8x20ms); drops if queue is totally full.
        if(!queued) { priming=true; ndspChnSetPaused(0,true); }
        for(int i=0;i<320;++i) free->data_pcm16[i]=decode(data[i]);
        DSP_FlushDataCache(free->data_pcm16,640); ndspChnWaveBufAdd(0,free);
        ++queued;
        if(priming && queued>=3) { ndspChnSetPaused(0,false); priming=false; }
    }
    void tick(bool paused) { if(available && (paused || (last && osGetTime()-last>350))) { reset(); last=0; } }
    void stop() { if(available) { ndspChnWaveBufClear(0); ndspExit(); linearFree(samples); available=false; } }
};
