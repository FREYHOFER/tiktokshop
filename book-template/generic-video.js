import * as THREE from "three";

const WIDTH = 720;
const HEIGHT = 1280;

const stage = document.querySelector("#video-stage");
const stageShell = document.querySelector("#stage-shell");
const canvas = document.querySelector("#video-canvas");
const hook = document.querySelector("#hook");
const feature = document.querySelector("#feature");
const endcard = document.querySelector("#endcard");
const endAuthor = document.querySelector("#end-author");
const endTitle = document.querySelector("#end-title");
const endLabel = document.querySelector("#end-label");
const cta = document.querySelector("#cta");
const ctaPrefix = document.querySelector("#cta-prefix");
const ctaMain = document.querySelector("#cta-main");
const flash = document.querySelector("#light-flash");

const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true,
  preserveDrawingBuffer: true,
});
renderer.setSize(WIDTH, HEIGHT, false);
renderer.setPixelRatio(1);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.9;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x030507);

const camera = new THREE.PerspectiveCamera(29, WIDTH / HEIGHT, 0.1, 100);
camera.position.set(-0.12, 0.08, 13.4);

const ambient = new THREE.HemisphereLight(0xf0f7f8, 0x020307, 0.03);
scene.add(ambient);

const keyLight = new THREE.DirectionalLight(0xffffff, 0.02);
keyLight.position.set(4.2, 6.2, 5.4);
keyLight.castShadow = true;
keyLight.shadow.mapSize.set(2048, 2048);
keyLight.shadow.camera.left = -6;
keyLight.shadow.camera.right = 6;
keyLight.shadow.camera.top = 7;
keyLight.shadow.camera.bottom = -7;
scene.add(keyLight);

const rimLight = new THREE.DirectionalLight(0x58dff2, 1.1);
rimLight.position.set(-4.8, 2.4, -2.8);
scene.add(rimLight);

const fillLight = new THREE.DirectionalLight(0x58dff2, 0.08);
fillLight.position.set(4, -1.5, 1.8);
scene.add(fillLight);

const ground = new THREE.Mesh(
  new THREE.PlaneGeometry(24, 24),
  new THREE.ShadowMaterial({ color: 0x000000, opacity: 0.5 }),
);
ground.rotation.x = -Math.PI / 2;
ground.position.y = -2.34;
ground.receiveShadow = true;
scene.add(ground);

const bookRoot = new THREE.Group();
scene.add(bookRoot);

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function rgbToHex(red, green, blue) {
  return `#${[red, green, blue].map((value) => Math.round(value).toString(16).padStart(2, "0")).join("")}`;
}

function extractPalette(image) {
  const sampleCanvas = document.createElement("canvas");
  sampleCanvas.width = 64;
  sampleCanvas.height = 64;
  const context = sampleCanvas.getContext("2d", { willReadFrequently: true });
  context.drawImage(image, 0, 0, 64, 64);
  const pixels = context.getImageData(0, 0, 64, 64).data;
  let best = { score: -1, red: 88, green: 223, blue: 242 };
  let average = [0, 0, 0];
  let count = 0;

  for (let index = 0; index < pixels.length; index += 16) {
    const red = pixels[index];
    const green = pixels[index + 1];
    const blue = pixels[index + 2];
    const maximum = Math.max(red, green, blue);
    const minimum = Math.min(red, green, blue);
    const saturation = maximum ? (maximum - minimum) / maximum : 0;
    const luminance = (red * 0.2126 + green * 0.7152 + blue * 0.0722) / 255;
    average[0] += red;
    average[1] += green;
    average[2] += blue;
    count += 1;
    if (luminance < 0.2 || luminance > 0.88) continue;
    const score = saturation * 1.25 + luminance * 0.35;
    if (score > best.score) best = { score, red, green, blue };
  }

  average = average.map((value) => value / Math.max(count, 1));
  if (best.score < 0.18) {
    best = { score: 0, red: 86, green: 190, blue: 208 };
  }
  const accent = [best.red, best.green, best.blue].map((value) => clamp(value * 1.08 + 12, 34, 246));
  const dark = average.map((value) => clamp(value * 0.27, 6, 52));
  return { accent, dark };
}

function makePaperEdgeTexture(pageColor, pages) {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = 96;
  textureCanvas.height = 1024;
  const context = textureCanvas.getContext("2d");
  context.fillStyle = pageColor;
  context.fillRect(0, 0, textureCanvas.width, textureCanvas.height);
  const spacing = clamp(Math.round(920 / Math.max(pages, 100)), 2, 5);
  for (let y = 1; y < textureCanvas.height; y += spacing) {
    context.fillStyle = y % (spacing * 4) === 1 ? "rgba(53,48,42,0.18)" : "rgba(53,48,42,0.065)";
    context.fillRect(0, y, textureCanvas.width, 1);
  }
  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  return texture;
}

function makeSpineTexture(config, palette) {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = 320;
  textureCanvas.height = 1600;
  const context = textureCanvas.getContext("2d");
  const accentHex = rgbToHex(...palette.accent);
  const darkHex = rgbToHex(...palette.dark);
  const gradient = context.createLinearGradient(0, 0, textureCanvas.width, 0);
  gradient.addColorStop(0, darkHex);
  gradient.addColorStop(0.45, accentHex);
  gradient.addColorStop(1, darkHex);
  context.fillStyle = gradient;
  context.fillRect(0, 0, textureCanvas.width, textureCanvas.height);

  context.save();
  context.translate(textureCanvas.width / 2, textureCanvas.height / 2);
  context.rotate(-Math.PI / 2);
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillStyle = "rgba(4, 6, 8, 0.9)";
  context.font = "600 58px Georgia, serif";
  context.fillText((config.author || "").slice(0, 42).toUpperCase(), 0, -43);
  context.font = "700 86px Georgia, serif";
  context.fillText((config.title || "BUCH").slice(0, 34).toUpperCase(), 0, 58);
  context.restore();

  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
  return texture;
}

function buildBook(config, frontTexture, palette) {
  const height = 4.2;
  const width = height * clamp(Number(config.cover_ratio) || 0.64, 0.5, 0.82);
  const depthRatio = clamp(Number(config.depth_ratio) || 0.15, 0.07, 0.25);
  const bookDepth = height * depthRatio;
  const coverThickness = 0.016;
  const pageDepth = bookDepth - coverThickness * 2;
  const pageWidth = width - 0.034;
  const pageHeight = height - 0.032;
  const overhang = 0.014;
  const accentColor = new THREE.Color(rgbToHex(...palette.accent));
  const darkColor = new THREE.Color(rgbToHex(...palette.dark));

  const edge = new THREE.MeshPhysicalMaterial({
    color: accentColor,
    roughness: 0.54,
    clearcoat: 0.12,
  });
  const front = new THREE.MeshPhysicalMaterial({
    map: frontTexture,
    color: 0xffffff,
    roughness: 0.5,
    clearcoat: 0.16,
    clearcoatRoughness: 0.62,
  });
  const back = new THREE.MeshPhysicalMaterial({
    color: darkColor,
    roughness: 0.62,
    clearcoat: 0.08,
  });
  const spine = new THREE.MeshPhysicalMaterial({
    map: makeSpineTexture(config, palette),
    color: 0xffffff,
    roughness: 0.54,
    clearcoat: 0.12,
  });
  const paper = new THREE.MeshStandardMaterial({ color: 0xeee9df, roughness: 0.94 });
  const pageEdge = new THREE.MeshStandardMaterial({
    map: makePaperEdgeTexture("#eee9df", Number(config.pages) || 320),
    color: 0xffffff,
    roughness: 0.92,
  });

  const pages = new THREE.Mesh(
    new THREE.BoxGeometry(pageWidth, pageHeight, pageDepth),
    [pageEdge, pageEdge, pageEdge, pageEdge, paper, paper],
  );
  pages.castShadow = true;
  pages.receiveShadow = true;
  bookRoot.add(pages);

  const frontCover = new THREE.Mesh(
    new THREE.BoxGeometry(width + overhang, height + overhang, coverThickness),
    [edge, edge, edge, edge, front, edge],
  );
  frontCover.position.z = pageDepth / 2 + coverThickness / 2;
  frontCover.castShadow = true;
  bookRoot.add(frontCover);

  const backCover = new THREE.Mesh(
    new THREE.BoxGeometry(width + overhang, height + overhang, coverThickness),
    [edge, edge, edge, edge, edge, back],
  );
  backCover.position.z = -pageDepth / 2 - coverThickness / 2;
  backCover.castShadow = true;
  bookRoot.add(backCover);

  const spineCover = new THREE.Mesh(
    new THREE.BoxGeometry(
      coverThickness * 1.15,
      height - coverThickness * 1.6,
      pageDepth + coverThickness * 0.35,
    ),
    [edge, spine, edge, edge, edge, edge],
  );
  spineCover.position.x = -width / 2 - overhang / 2 - coverThickness * 0.3;
  spineCover.castShadow = true;
  bookRoot.add(spineCover);
}

function smooth(start, end, time) {
  const value = clamp((time - start) / Math.max(end - start, 0.0001), 0, 1);
  return value * value * (3 - 2 * value);
}

function mix(from, to, amount) {
  return from + (to - from) * amount;
}

function windowOpacity(time, inStart, inEnd, outStart, outEnd) {
  return smooth(inStart, inEnd, time) * (1 - smooth(outStart, outEnd, time));
}

function setOverlay(element, opacity, distance = 18) {
  element.style.opacity = opacity.toFixed(4);
  element.style.transform = `translateY(${((1 - opacity) * distance).toFixed(2)}px)`;
}

function fitTitle(text) {
  const length = text.trim().length;
  endTitle.style.fontSize = `${length > 36 ? 38 : length > 26 ? 44 : length > 18 ? 50 : 56}px`;
}

let config = null;
let duration = 15;

function renderAt(rawTime) {
  if (!config || !bookRoot.children.length) return;
  const time = clamp(rawTime, 0, duration);
  const lightOn = smooth(1.45, 2.15, time);
  const revealMove = smooth(1.6, 5.7, time);
  const detailMove = smooth(5.7, 9.3, time);
  const endMove = smooth(10.2, 12.0, time);

  ambient.intensity = 0.018 + lightOn * 0.84;
  keyLight.intensity = 0.015 + lightOn * 4.6;
  rimLight.intensity = 1.0 + lightOn * 0.75;
  fillLight.intensity = 0.02 + lightOn * 0.74;
  renderer.toneMappingExposure = 0.54 + lightOn * 0.46;

  let rotationY = mix(1.03, 0.52, revealMove);
  rotationY = mix(rotationY, -0.05, detailMove);
  rotationY = mix(rotationY, 0.2, endMove);
  bookRoot.rotation.set(-0.07 + Math.sin(time * 0.44) * 0.012, rotationY, -0.016);

  const hover = Math.sin(time * 0.7) * 0.035;
  bookRoot.position.set(-0.18, 0.05 + hover + endMove * 0.25, 0);
  const scale = mix(0.76, 0.86, smooth(1.5, 4.8, time));
  bookRoot.scale.setScalar(mix(scale, 0.76, endMove));

  let cameraZ = mix(13.6, 12.4, revealMove);
  cameraZ = mix(cameraZ, 11.75, detailMove);
  cameraZ = mix(cameraZ, 13.7, endMove);
  camera.position.set(-0.12, 0.08, cameraZ);
  camera.lookAt(-0.16, 0.08, 0);

  setOverlay(hook, windowOpacity(time, 0.15, 0.48, 1.18, 1.5));
  setOverlay(feature, windowOpacity(time, 6.4, 6.9, 9.2, 9.75), -14);
  setOverlay(endcard, smooth(10.6, 11.4, time), -16);
  setOverlay(cta, smooth(12.0, 12.75, time), 20);

  const flashUp = smooth(1.5, 1.62, time);
  const flashDown = 1 - smooth(1.62, 1.9, time);
  flash.style.opacity = (flashUp * flashDown * 0.25).toFixed(4);

  renderer.render(scene, camera);
}

function fitStage() {
  const scale = Math.min(window.innerWidth / WIDTH, window.innerHeight / HEIGHT);
  stageShell.style.width = `${WIDTH * scale}px`;
  stageShell.style.height = `${HEIGHT * scale}px`;
  stage.style.transform = `scale(${scale})`;
}

window.__VIDEO_READY = false;
window.renderVideoFrame = renderAt;

async function init() {
  const parameters = new URLSearchParams(window.location.search);
  const projectUrl = parameters.get("project") || "/project.json";
  config = await fetch(projectUrl, { cache: "no-store" }).then((response) => {
    if (!response.ok) throw new Error(`Project configuration failed: ${response.status}`);
    return response.json();
  });
  duration = Number(config.duration_seconds) || 15;
  hook.textContent = config.hook || "NEU FÜR DEINE LESELISTE";
  feature.textContent = config.feature || config.label || "JETZT ENTDECKEN";
  endAuthor.textContent = (config.author || "").toUpperCase();
  endTitle.textContent = (config.title || "BUCH").toUpperCase();
  endLabel.textContent = (config.label || "BUCHEMPFEHLUNG").toUpperCase();
  ctaPrefix.textContent = config.cta_prefix || "JETZT IM";
  ctaMain.textContent = config.cta || "TIKTOK SHOP";
  fitTitle(endTitle.textContent);
  document.title = `${config.title || "Book"} - Video`;

  const loader = new THREE.TextureLoader();
  const frontTexture = await loader.loadAsync(config.cover_url || "/cover.jpg");
  frontTexture.colorSpace = THREE.SRGBColorSpace;
  frontTexture.anisotropy = renderer.capabilities.getMaxAnisotropy();
  const palette = extractPalette(frontTexture.image);
  const accentHex = rgbToHex(...palette.accent);
  document.documentElement.style.setProperty("--accent", accentHex);
  rimLight.color.set(accentHex);
  fillLight.color.set(accentHex);
  buildBook(config, frontTexture, palette);

  const initialTime = Number(parameters.get("time") || 0);
  renderAt(Number.isFinite(initialTime) ? initialTime : 0);
  window.__VIDEO_READY = true;

  if (parameters.get("render") !== "1") {
    const startedAt = performance.now();
    const loop = (now) => {
      renderAt(((now - startedAt) / 1000) % duration);
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }
}

window.addEventListener("resize", fitStage);
fitStage();
init().catch((error) => {
  console.error(error);
  window.__VIDEO_ERROR = String(error);
});
