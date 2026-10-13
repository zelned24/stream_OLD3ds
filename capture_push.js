// One producer, one in-flight binding, latest-frame mailbox on the PC.
// The game continues rendering while Python sends the previous frame.
({selector, initial}) => {
    window.__rogueStreaming = true;
    (async () => {
        let settings = initial;
        while (window.__rogueStreaming) {
            const start = performance.now();
            try {
                const source = document.querySelector(selector);
                if (source && settings.active) {
                    const half = settings.half;
                    const frame = await window.__rogueCapture(source, half);
                    settings = await window.__rogueFrame(frame, half, performance.now()-start);
                } else {
                    settings = await window.__rogueFrame(null, false, 0);
                }
            } catch (error) {
                console.warn('Stream capture:', error.message);
                await new Promise(resolve => setTimeout(resolve, 250));
            }
            const delay = settings.active ? 1000/settings.fps : 100;
            await new Promise(resolve => setTimeout(resolve, Math.max(0, delay-(performance.now()-start))));
        }
    })();
}
