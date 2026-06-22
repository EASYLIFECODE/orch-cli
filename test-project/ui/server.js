console.log("UI dev server starting...");
console.log("Current Working Directory: " + process.cwd());

let counter = 0;
const interval = setInterval(() => {
    counter++;
    console.log(`[UI] Dev server watch update #${counter}`);
    if (counter >= 12) {
        console.log("UI loop complete, shutting down.");
        clearInterval(interval);
        process.exit(0);
    }
}, 1200);

process.on('SIGINT', () => {
    console.log("UI received SIGINT, stopping watchdog...");
    clearInterval(interval);
    process.exit(0);
});
