#!/usr/bin/env node

const fs = require("fs");
const http = require("http");
const path = require("path");
const { spawnSync } = require("child_process");

let chromium;
try {
  ({ chromium } = require("playwright-core"));
} catch (coreError) {
  try {
    ({ chromium } = require("playwright"));
  } catch (playwrightError) {
    throw new Error("Install Playwright with `npm install` before rendering.", { cause: playwrightError });
  }
}

const FPS = 30;
const WIDTH = 720;
const HEIGHT = 1280;
const SAMPLE_RATE = 48000;
const workspace = path.resolve(__dirname, "..");
const webRoot = path.resolve(workspace, "book-template");

function parseArgs(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 1) {
    const key = argv[index];
    if (!key.startsWith("--")) continue;
    result[key.slice(2)] = argv[index + 1];
    index += 1;
  }
  if (!result.project) throw new Error("Usage: render_book_video.cjs --project <project.json> [--output-dir <dir>]");
  return result;
}

function assertInsideWorkspace(target) {
  const relative = path.relative(workspace, target);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`Refusing to modify path outside workspace: ${target}`);
  }
}

function sendFile(response, target) {
  const mimeTypes = {
    ".css": "text/css",
    ".html": "text/html",
    ".js": "text/javascript",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".json": "application/json",
    ".png": "image/png",
  };
  response.writeHead(200, { "Content-Type": mimeTypes[path.extname(target).toLowerCase()] || "application/octet-stream" });
  fs.createReadStream(target).pipe(response);
}

function createServer(projectPath, coverPath, config) {
  return http.createServer((request, response) => {
    const requestPath = decodeURIComponent((request.url || "/").split("?")[0]);
    if (requestPath === "/project.json") {
      response.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store" });
      response.end(JSON.stringify({ ...config, cover_url: "/cover.jpg" }));
      return;
    }
    if (requestPath === "/cover.jpg") {
      sendFile(response, coverPath);
      return;
    }
    const relativePath = requestPath === "/" ? "generic-video.html" : requestPath.replace(/^\/+/, "");
    const target = path.resolve(webRoot, relativePath);
    const relative = path.relative(webRoot, target);
    if (relative.startsWith("..") || path.isAbsolute(relative) || !fs.existsSync(target) || fs.statSync(target).isDirectory()) {
      response.writeHead(404);
      response.end("Not found");
      return;
    }
    sendFile(response, target);
  });
}

function seededRandom(seedState) {
  let state = seedState >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0xffffffff;
  };
}

function makeSoundDesign(audioPath, duration) {
  const samples = new Float64Array(Math.round(SAMPLE_RATE * duration));
  const random = seededRandom(84631);

  for (let index = 0; index < samples.length; index += 1) {
    const time = index / SAMPLE_RATE;
    const fadeIn = Math.min(1, time / 1.2);
    const fadeOut = Math.min(1, (duration - time) / 1.0);
    samples[index] += (
      Math.sin(Math.PI * 2 * 44 * time) * 0.016
      + Math.sin(Math.PI * 2 * 66 * time) * 0.007
    ) * fadeIn * fadeOut;
  }

  function addImpact(start, gain = 0.38, impactDuration = 1.2) {
    const startSample = Math.floor(start * SAMPLE_RATE);
    const length = Math.floor(impactDuration * SAMPLE_RATE);
    let phase = 0;
    for (let index = 0; index < length && startSample + index < samples.length; index += 1) {
      const time = index / SAMPLE_RATE;
      const frequency = 78 - 38 * Math.min(1, time / impactDuration);
      phase += Math.PI * 2 * frequency / SAMPLE_RATE;
      samples[startSample + index] += Math.sin(phase) * Math.exp(-time * 3.1) * gain;
    }
  }

  function addWhoosh(start, whooshDuration = 0.75, gain = 0.04) {
    const startSample = Math.floor(start * SAMPLE_RATE);
    const length = Math.floor(whooshDuration * SAMPLE_RATE);
    for (let index = 0; index < length && startSample + index < samples.length; index += 1) {
      const progress = index / length;
      const envelope = Math.sin(Math.PI * progress);
      samples[startSample + index] += (random() * 2 - 1) * envelope * gain;
    }
  }

  addWhoosh(0.85, 0.9, 0.026);
  addImpact(1.58, 0.44);
  addWhoosh(5.85, 1.0, 0.022);
  addImpact(6.45, 0.22, 0.8);
  addWhoosh(9.8, 1.0, 0.024);
  addImpact(10.72, 0.34);
  addImpact(12.04, 0.18, 0.65);

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
  for (let index = 0; index < samples.length; index += 1) {
    const value = Math.max(-1, Math.min(1, samples[index] * normalization));
    buffer.writeInt16LE(Math.round(value * 32767), 44 + index * 2);
  }
  fs.writeFileSync(audioPath, buffer);
}

function runFfmpeg(ffmpegPath, args, label) {
  const result = spawnSync(ffmpegPath, args, { encoding: "utf8", maxBuffer: 16 * 1024 * 1024 });
  if (result.status !== 0) {
    throw new Error(`${label} failed (${result.status}):\n${result.stderr || result.stdout}`);
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const projectPath = path.resolve(args.project);
  if (!fs.existsSync(projectPath)) throw new Error(`Project file not found: ${projectPath}`);
  const config = JSON.parse(fs.readFileSync(projectPath, "utf8"));
  const coverPath = path.resolve(path.dirname(projectPath), config.cover_path || "cover.jpg");
  if (!fs.existsSync(coverPath)) throw new Error(`Cover file not found: ${coverPath}`);

  const outputDir = path.resolve(args["output-dir"] || path.join(path.dirname(projectPath), "rendered"));
  const framesDir = path.join(outputDir, "frames");
  const audioPath = path.join(outputDir, "sound-design.wav");
  const videoPath = path.join(outputDir, "book-video.mp4");
  const heroSourcePath = path.join(outputDir, "hero-source.jpg");
  const heroPath = path.join(outputDir, "hero.png");
  const duration = Number(config.duration_seconds) || 15;
  const totalFrames = Math.round(FPS * duration);

  assertInsideWorkspace(outputDir);
  assertInsideWorkspace(framesDir);
  fs.mkdirSync(outputDir, { recursive: true });
  fs.rmSync(framesDir, { recursive: true, force: true });
  fs.mkdirSync(framesDir, { recursive: true });
  makeSoundDesign(audioPath, duration);

  const server = createServer(projectPath, coverPath, config);
  let browser;
  try {
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const port = server.address().port;
    const chromePath = process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe";
    browser = await chromium.launch({ headless: true, executablePath: chromePath });
    const page = await browser.newPage({ viewport: { width: WIDTH, height: HEIGHT }, deviceScaleFactor: 1 });
    await page.goto(`http://127.0.0.1:${port}/generic-video.html?render=1`, { waitUntil: "networkidle" });
    await page.waitForFunction(() => window.__VIDEO_READY === true || window.__VIDEO_ERROR, null, { timeout: 30000 });
    const pageError = await page.evaluate(() => window.__VIDEO_ERROR || "");
    if (pageError) throw new Error(`Video template failed: ${pageError}`);

    const stillFrames = new Map([
      [Math.round(FPS * 1.8), "01-reveal.jpg"],
      [Math.round(FPS * 4.4), "02-front.jpg"],
      [Math.round(FPS * 7.4), "03-detail.jpg"],
      [Math.round(FPS * 13.0), "04-endcard.jpg"],
    ]);
    const heroFrame = Math.round(FPS * 4.4);
    for (let frame = 0; frame < totalFrames; frame += 1) {
      await page.evaluate((time) => window.renderVideoFrame(time), frame / FPS);
      const image = await page.screenshot({ type: "jpeg", quality: 94 });
      const framePath = path.join(framesDir, `frame-${String(frame).padStart(4, "0")}.jpg`);
      fs.writeFileSync(framePath, image);
      if (stillFrames.has(frame)) fs.copyFileSync(framePath, path.join(outputDir, stillFrames.get(frame)));
      if (frame === heroFrame) fs.copyFileSync(framePath, heroSourcePath);
      if (frame % 90 === 0) process.stdout.write(`Rendered ${frame}/${totalFrames} frames\n`);
    }
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }

  const ffmpegPath = process.env.FFMPEG_PATH;
  if (!ffmpegPath || !fs.existsSync(ffmpegPath)) throw new Error("Set FFMPEG_PATH to a valid ffmpeg executable.");
  runFfmpeg(ffmpegPath, [
    "-y", "-framerate", String(FPS), "-i", path.join(framesDir, "frame-%04d.jpg"), "-i", audioPath,
    "-vf", "scale=1080:1920:flags=lanczos", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", videoPath,
  ], "Video encoding");
  runFfmpeg(ffmpegPath, ["-y", "-i", heroSourcePath, "-vf", "scale=1080:1920:flags=lanczos", heroPath], "Hero export");
  fs.rmSync(framesDir, { recursive: true, force: true });
  fs.rmSync(heroSourcePath, { force: true });
  process.stdout.write(`Video: ${videoPath}\nHero: ${heroPath}\n`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
