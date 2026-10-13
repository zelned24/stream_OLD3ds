// Called in a requestAnimationFrame callback, after the game's render callback,
// so WebGL's transient drawing buffer is read before presentation clears it.
async (source, half = 0) => new Promise(resolve => requestAnimationFrame(() => {
    const width = half == 1 ? 200 : half == 2 ? 320 : 400, height = half == 1 ? 120 : half == 2 ? 192 : 240;
    let capture = source.__rogueStreamCapture;
    if (!capture || capture.packed.length !== width*height) {
        const target = document.createElement('canvas');
        target.width = width; target.height = height;
        const ctx = target.getContext('2d', {willReadFrequently: true});
        capture = source.__rogueStreamCapture = {
            target, ctx,
            packed: new Uint8Array(width*height),
            outImg: ctx.createImageData(width, height)
        };
    }
    const {ctx, target, packed, outImg} = capture;
    const sharp = !!window.__rogueSharp && half != 1;
    const scale = Math.min(width/source.width, height/source.height);
    const w = Math.round(source.width*scale), h = Math.round(source.height*scale);
    ctx.fillStyle = 'black'; ctx.fillRect(0,0,width,height);
    ctx.imageSmoothingEnabled = !sharp;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(source, (width-w)>>1, (height-h)>>1, w,h);

    // Transfer uncompressed pixels only across local Playwright, never over Wi-Fi.
    // Pillow controls JPEG chroma subsampling; canvas.toDataURL cannot specify it.
    if (sharp && half != 1) {
        const rgba = ctx.getImageData(0,0,width,height).data;
        let binary = '';
        for(let i=0;i<rgba.length;i+=8192)
            binary += String.fromCharCode(...rgba.subarray(i,i+8192));
        resolve(btoa(binary)); return;
    }

    // Fast 3x3 unsharp mask restores crisp pixel-art edges lost during 1080p downsampling
    const src = ctx.getImageData(0,0,width,height).data;
    const dst = outImg.data;
    dst.set(src);
    const stride = width * 4;
    for (let y = 1; !sharp && y < height - 1; ++y) {
        let idx = y * stride + 4;
        for (let x = 1; x < width - 1; ++x) {
            for (let c = 0; c < 3; ++c) {
                const val = 3.0 * src[idx + c] - 0.5 * (src[idx + c - 4] + src[idx + c + 4] + src[idx + c - stride] + src[idx + c + stride]);
                dst[idx + c] = val < 0 ? 0 : (val > 255 ? 255 : val);
            }
            idx += 4;
        }
    }
    ctx.putImageData(outImg, 0, 0);

    if (half != 1) { resolve(target.toDataURL('image/jpeg', 0.75).split(',')[1]); return; }
    for(let i=0,j=0;i<dst.length;i+=4,++j)
        packed[j] = (dst[i]&224)|((dst[i+1]&224)>>3)|(dst[i+2]>>6);
    let binary = '';
    for(let i=0;i<packed.length;i+=8192)
        binary += String.fromCharCode(...packed.subarray(i,i+8192));
    resolve(btoa(binary));
}))
