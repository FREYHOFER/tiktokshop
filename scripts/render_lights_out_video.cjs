#!/usr/bin/env node

const fs = require("fs");
const http = require("http");
const path = require("path");
const { spawnSync } = require("child_process");
const { chromium } = require("playwright");

const FPS = 30;
const DURATION = 15;
const WIDTH = 720;
const HEIGHT = 1280;
const SAMPLE_RATE = 48000;

const workspace = path.resolve(__dirname, "..");
const webRoot = path.resolve(workspace, "book-template");
const outputDir = path.resolve(workspace, "outputs", "marketing", "lights-out-video");
const framesDir = path.resolve(outputDir, "frames");
const videoPath = path.resolve(outputDir, "lights-out-tiktok.mp4");
const audioPath = path.resolve(outputDir, "lights-out-sounddesign.wav");

function assertInsideWorkspace(target) {
  if (!target.startsWith(`${workspace}${path.sep}`)) {
    throw new Error(`Refusing to modify path outside workspace: ${target}`);
  }
}

function createServer() {
  const mimeTypes = {
    ".css": "text/css",
    ".html": "text/html",
    ".js": "text/javascript",
    ".jpg": "image/jpeg",
    ".png": "image/png",
  };
  return http.createServer((request, response) => {
    const requestPath = decodeURIComponent((request.url || "/").split("?")[0]);
    const relativePath = requestPath === "/" ? "video.html" : requestPath.replace(/^\/+/, "");
    const target = path.resolve(webRoot, relativePath);
    if (!target.startsWith(`${webRoot}${path.sep}`) || !fs.existsSync(target) || fs.statSync(target).isDirectory()) {
      response.writeHead(404);
      response.end("Not found");
      return;
    }
    response.writeHead(200, { "Content-Type": mimeTypes[path.extname(target)] || "application/octet-stream" });
    fs.createReadStream(target).pipe(response);
  });
}

function seededRandom(seedState) {
  let state = seedState >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0xffffffff;
  };
}

function makeSoundDesign() {
  const samples = new Float64Array(SAMPLE_RATE * DURATION);
  const random = seededRandom(73491);

  for (let i = 0; i < samples.length; i += 1) {
    const time = i / SAMPLE_RATE;
    const fadeIn = Math.min(1, time / 1.4);
    const fadeOut = Math.min(1, (DURATION - time) / 1.2);
    samples[i] += (Math.sin(Math.PI * 2 * 43 * time) * 0.018 + Math.sin(Math.PI * 2 * 64.5 * time) * 0.008) * fadeIn * fadeOut;
  }

  function addThump(start, gain = 0.32, duration = 0.24) {
    const startSample = Math.floor(start * SAMPLE_RATE);
    const length = Math.floor(duration * SAMPLE_RATE);
    for (let i = 0; i < length && startSample + i < samples.length; i += 1) {
      const time = i / SAMPLE_RATE;
      const envelope = Math.exp(-time * 18);
      samples[startSample + i] += Math.sin(Math.PI * 2 * 58 * time) * envelope * gain;
    }
  }

  function addClick(start) {
    const startSample = Math.floor(start * SAMPLE_RATE);
    const length = Math.floor(0.075 * SAMPLE_RATE);
    for (let i = 0; i < length; i += 1) {
      const time = i / SAMPLE_RATE;
      const envelope = Math.exp(-time * 65);
      const noise = random() * 2 - 1;
      samples[startSample + i] += (noise * 0.48 + Math.sin(Math.PI * 2 * 2100 * time) * 0.22) * envelope;
    }
  }

  function addImpact(start) {
    const startSample = Math.floor(start * SAMPLE_RATE);
    const length = Math.floor(1.45 * SAMPLE_RATE);
    let phase = 0;
    for (let i = 0; i < length && startSample + i < samples.length; i += 1) {
      const time = i / SAMPLE_RATE;
      const frequency = 82 - 46 * Math.min(1, time / 1.2);
      phase += Math.PI * 2 * frequency / SAMPLE_RATE;
      const envelope = Math.exp(-time * 2.9);
      samples[startSample + i] += Math.sin(phase) * envelope * 0.46;
    }
  }

  function addRiser(start, duration) {
    const startSample = Math.floor(start * SAMPLE_RATE);
    const length = Math.floor(duration * SAMPLE_RATE);
    for (let i = 0; i < length; i += 1) {
      const progress = i / length;
      const noise = random() * 2 - 1;
      samples[startSample + i] += noise * progress * progress * 0.028;
    }
  }

  addClick(1.26);
  addThump(1.68, 0.29);
  addThump(2.02, 0.25);
  addThump(2.72, 0.28);
  addThump(3.06, 0.23);
  addRiser(3.05, 0.85);
  addImpact(3.9);
  addThump(7.5, 0.18);
  addThump(7.82, 0.15);
  addImpact(11.05);

  let peak = 0;
  for (const sample of samples) peak = Math.max(peak, Math.abs(sample));
  const normalization = peak > 0 ? 0.88 / peak : 1;
  const dataSize = samples.length * 2;
  const buffer = Buffer.alloc(44 + dataSize);
  buffer.write("RIFF", 0);
  buffer.writeUInt32LE(36 + dataSize, 4);
  buffer.write("WAVE", 8);
  buffer.write("fmt ", 12);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(SAMPLE_RATE, 24);
  buffer.writeUInt32LE(SAMPLE_RATE * 2, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write("data", 36);
  buffer.writeUInt32LE(dataSize, 40);
  for (let i = 0; i < samples.length; i += 1) {
    const value = Math.max(-1, Math.min(1, samples[i] * normalization));
    buffer.writeInt16LE(Math.round(value * 32767), 44 + i * 2);
  }
  fs.writeFileSync(audioPath, buffer);
}

async function main() {
  assertInsideWorkspace(outputDir);
  assertInsideWorkspace(framesDir);
  fs.mkdirSync(outputDir, { recursive: true });
  fs.rmSync(framesDir, { recursive: true, force: true });
  fs.mkdirSync(framesDir, { recursive: true });
  makeSoundDesign();

  const server = createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  const chromePath = process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe";
  const browser = await chromium.launch({ headless: true, executablePath: chromePath });
  const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT }, deviceScaleFactor: 1 });
  await page.goto(`http://127.0.0.1:${port}/video.html?render=1`, { waitUntil: "networkidle" });
  await page.waitForFunction(() => window.__VIDEO_READY === true);

  const stillFrames = new Map([
    [54, "01-eyes.jpg"],
    [132, "02-reveal.jpg"],
    [255, "03-detail.jpg"],
    [390, "04-endcard.jpg"],
  ]);
  const totalFrames = FPS * DURATION;
  for (let frame = 0; frame < totalFrames; frame += 1) {
    await page.evaluate((time) => window.renderVideoFrame(time), frame / FPS);
    const framePath = path.join(framesDir, `frame-${String(frame).padStart(4, "0")}.jpg`);
    const image = await page.screenshot({ type: "jpeg", quality: 94 });
    fs.writeFileSync(framePath, image);
    if (stillFrames.has(frame)) fs.copyFileSync(framePath, path.join(outputDir, stillFrames.get(frame)));
    if (frame % 60 === 0) process.stdout.write(`Rendered ${frame}/${totalFrames} frames\n`);
  }

  await browser.close();
  server.close();

  const ffmpegPath = process.env.FFMPEG_PATH;
  if (!ffmpegPath || !fs.existsSync(ffmpegPath)) {
    throw new Error("Set FFMPEG_PATH to a valid ffmpeg executable.");
  }
  const ffmpeg = spawnSync(ffmpegPath, [
    "-y",
    "-framerate", String(FPS),
    "-i", path.join(framesDir, "frame-%04d.jpg"),
    "-i", audioPath,
    "-vf", "scale=1080:1920:flags=lanczos",
    "-c:v", "libx264",
    "-preset", "medium",
    "-crf", "18",
    "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-b:a", "192k",
    "-shortest",
    "-movflags", "+faststart",
    videoPath,
  ], { stdio: "inherit" });
  if (ffmpeg.status !== 0) throw new Error(`ffmpeg exited with status ${ffmpeg.status}`);

  fs.rmSync(framesDir, { recursive: true, force: true });
  process.stdout.write(`Video: ${videoPath}\n`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
