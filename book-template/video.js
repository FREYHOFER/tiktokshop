import * as THREE from "three";

const WIDTH = 720;
const HEIGHT = 1280;
const DURATION = 15;

const stage = document.querySelector("#video-stage");
const canvas = document.querySelector("#video-canvas");
const hook = document.querySelector("#hook");
const question = document.querySelector("#question");
const genre = document.querySelector("#genre");
const endcard = document.querySelector("#endcard");
const cta = document.querySelector("#cta");
const ageNote = document.querySelector("#age-note");
const flash = document.querySelector("#switch-flash");

const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true,
  preserveDrawingBuffer: true,
});
renderer.setSize(WIDTH, HEIGHT, false);
renderer.setPixelRatio(1);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 0.92;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x030507);

const camera = new THREE.PerspectiveCamera(29, WIDTH / HEIGHT, 0.1, 100);
camera.position.set(-0.12, 0.08, 13.4);

const ambient = new THREE.HemisphereLight(0xdff9ff, 0x020307, 0.02);
scene.add(ambient);

const keyLight = new THREE.DirectionalLight(0xf5fbff, 0.02);
keyLight.position.set(4.2, 6.2, 5.4);
keyLight.castShadow = true;
keyLight.shadow.mapSize.set(2048, 2048);
keyLight.shadow.camera.left = -6;
keyLight.shadow.camera.right = 6;
keyLight.shadow.camera.top = 7;
keyLight.shadow.camera.bottom = -7;
scene.add(keyLight);

const cyanRim = new THREE.DirectionalLight(0x23dfff, 1.2);
cyanRim.position.set(-4.8, 2.4, -2.8);
scene.add(cyanRim);

const blueFill = new THREE.DirectionalLight(0x0b77a8, 0.12);
blueFill.position.set(4, -1.5, 1.8);
scene.add(blueFill);

const ground = new THREE.Mesh(
  new THREE.PlaneGeometry(24, 24),
  new THREE.ShadowMaterial({ color: 0x000000, opacity: 0.52 }),
);
ground.rotation.x = -Math.PI / 2;
ground.position.y = -2.34;
ground.receiveShadow = true;
scene.add(ground);

const bookRoot = new THREE.Group();
scene.add(bookRoot);

function makePaperEdgeTexture() {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = 96;
  textureCanvas.height = 1024;
  const context = textureCanvas.getContext("2d");
  context.fillStyle = "#ebe6dc";
  context.fillRect(0, 0, textureCanvas.width, textureCanvas.height);
  for (let y = 1; y < textureCanvas.height; y += 3) {
    context.fillStyle = y % 12 === 1 ? "rgba(53,48,42,0.19)" : "rgba(53,48,42,0.07)";
    context.fillRect(0, y, textureCanvas.width, y % 12 === 1 ? 2 : 1);
  }
  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  return texture;
}

function makeSpineTexture() {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = 320;
  textureCanvas.height = 1600;
  const context = textureCanvas.getContext("2d");
  const gradient = context.createLinearGradient(0, 0, textureCanvas.width, 0);
  gradient.addColorStop(0, "#007eaa");
  gradient.addColorStop(0.45, "#11b0e2");
  gradient.addColorStop(1, "#057ba7");
  context.fillStyle = gradient;
  context.fillRect(0, 0, textureCanvas.width, textureCanvas.height);

  context.save();
  context.translate(textureCanvas.width / 2, textureCanvas.height / 2);
  context.rotate(-Math.PI / 2);
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillStyle = "#050708";
  context.font = "600 60px Georgia, serif";
  context.fillText("NAVESSA ALLEN", 0, -44);
  context.font = "700 94px Georgia, serif";
  context.fillText("LIGHTS OUT", 0, 62);
  context.restore();

  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
  return texture;
}

function makeGlyphTexture(type) {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = 512;
  textureCanvas.height = 512;
  const context = textureCanvas.getContext("2d");
  context.translate(256, 256);
  context.shadowColor = "#38efff";
  context.shadowBlur = 74;
  context.fillStyle = "#8cf8ff";
  context.strokeStyle = "#8cf8ff";
  context.lineCap = "round";
  context.lineJoin = "round";

  if (type === "x") {
    context.lineWidth = 62;
    context.beginPath();
    context.moveTo(-82, -82);
    context.lineTo(82, 82);
    context.moveTo(82, -82);
    context.lineTo(-82, 82);
    context.stroke();
  } else {
    context.beginPath();
    context.moveTo(0, 112);
    context.bezierCurveTo(-28, 78, -132, 20, -132, -64);
    context.bezierCurveTo(-132, -150, -28, -176, 0, -100);
    context.bezierCurveTo(28, -176, 132, -150, 132, -64);
    context.bezierCurveTo(132, 20, 28, 78, 0, 112);
    context.fill();
  }

  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function materialSet(frontTexture, backTexture) {
  const edge = new THREE.MeshPhysicalMaterial({
    color: 0x079ccf,
    roughness: 0.5,
    clearcoat: 0.15,
  });
  const front = new THREE.MeshPhysicalMaterial({
    map: frontTexture,
    color: 0xffffff,
    roughness: 0.48,
    clearcoat: 0.18,
    clearcoatRoughness: 0.58,
  });
  const back = new THREE.MeshPhysicalMaterial({
    map: backTexture,
    color: 0xffffff,
    roughness: 0.48,
    clearcoat: 0.18,
    clearcoatRoughness: 0.58,
  });
  const spine = new THREE.MeshPhysicalMaterial({
    map: makeSpineTexture(),
    color: 0xffffff,
    roughness: 0.5,
    clearcoat: 0.15,
  });
  const paper = new THREE.MeshStandardMaterial({ color: 0xeee9df, roughness: 0.94 });
  const pageEdge = new THREE.MeshStandardMaterial({
    map: makePaperEdgeTexture(),
    color: 0xffffff,
    roughness: 0.92,
  });
  return { edge, front, back, spine, paper, pageEdge };
}

function buildBook(frontTexture, backTexture) {
  const height = 4.2;
  const width = height * (136 / 214);
  const bookDepth = height * (45 / 214);
  const coverThickness = height * (0.75 / 214);
  const pageDepth = bookDepth - coverThickness * 2;
  const pageWidth = width - 0.034;
  const pageHeight = height - 0.032;
  const overhang = 0.014;
  const materials = materialSet(frontTexture, backTexture);

  const pages = new THREE.Mesh(
    new THREE.BoxGeometry(pageWidth, pageHeight, pageDepth),
    [materials.pageEdge, materials.pageEdge, materials.pageEdge, materials.pageEdge, materials.paper, materials.paper],
  );
  pages.castShadow = true;
  pages.receiveShadow = true;
  bookRoot.add(pages);

  const front = new THREE.Mesh(
    new THREE.BoxGeometry(width + overhang, height + overhang, coverThickness),
    [materials.edge, materials.edge, materials.edge, materials.edge, materials.front, materials.edge],
  );
  front.position.z = pageDepth / 2 + coverThickness / 2;
  front.castShadow = true;
  bookRoot.add(front);

  const back = new THREE.Mesh(
    new THREE.BoxGeometry(width + overhang, height + overhang, coverThickness),
    [materials.edge, materials.edge, materials.edge, materials.edge, materials.edge, materials.back],
  );
  back.position.z = -pageDepth / 2 - coverThickness / 2;
  back.castShadow = true;
  bookRoot.add(back);

  const spine = new THREE.Mesh(
    new THREE.BoxGeometry(
      coverThickness * 1.15,
      height - coverThickness * 1.6,
      pageDepth + coverThickness * 0.35,
    ),
    [materials.edge, materials.spine, materials.edge, materials.edge, materials.edge, materials.edge],
  );
  spine.position.x = -width / 2 - overhang / 2 - coverThickness * 0.3;
  spine.castShadow = true;
  bookRoot.add(spine);

  const glyphMaterialX = new THREE.MeshBasicMaterial({
    map: makeGlyphTexture("x"),
    transparent: true,
    opacity: 0,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    toneMapped: false,
  });
  const glyphMaterialHeart = glyphMaterialX.clone();
  glyphMaterialHeart.map = makeGlyphTexture("heart");

  const glyphZ = bookDepth / 2 + coverThickness + 0.008;
  const glyphSize = 0.46;
  const xGlyph = new THREE.Mesh(new THREE.PlaneGeometry(glyphSize, glyphSize), glyphMaterialX);
  xGlyph.position.set(-0.42, 0.55, glyphZ);
  xGlyph.renderOrder = 10;
  const heartGlyph = new THREE.Mesh(new THREE.PlaneGeometry(glyphSize, glyphSize), glyphMaterialHeart);
  heartGlyph.position.set(0.42, 0.55, glyphZ);
  heartGlyph.renderOrder = 10;
  bookRoot.add(xGlyph, heartGlyph);

  const eyeLight = new THREE.PointLight(0x29e7ff, 0, 3.8, 2.2);
  eyeLight.position.set(0, 0.5, glyphZ + 0.7);
  bookRoot.add(eyeLight);

  return { glyphMaterialX, glyphMaterialHeart, eyeLight };
}

function clamp01(value) {
  return Math.min(1, Math.max(0, value));
}

function smooth(start, end, time) {
  const value = clamp01((time - start) / Math.max(end - start, 0.0001));
  return value * value * (3 - 2 * value);
}

function windowOpacity(time, inStart, inEnd, outStart, outEnd) {
  return smooth(inStart, inEnd, time) * (1 - smooth(outStart, outEnd, time));
}

function mix(from, to, amount) {
  return from + (to - from) * amount;
}

function setOverlay(element, opacity, distance = 18) {
  element.style.opacity = opacity.toFixed(4);
  element.style.transform = `translateY(${((1 - opacity) * distance).toFixed(2)}px)`;
}

let glowParts = null;

function renderAt(rawTime) {
  if (!glowParts) return;
  const time = Math.min(DURATION, Math.max(0, rawTime));
  const lightsOn = smooth(3.72, 4.18, time);
  const earlyReveal = smooth(1.18, 1.58, time) * (1 - smooth(3.82, 4.2, time));
  const eyeBase = windowOpacity(time, 1.3, 1.62, 3.84, 4.32);
  const eyePulse = 0.84 + Math.sin(time * 8.5) * 0.08 + Math.sin(time * 3.1) * 0.05;
  const eyeOpacity = eyeBase * eyePulse;
  const revealMove = smooth(3.7, 7.6, time);
  const detailMove = smooth(7.6, 10.2, time);
  const endMove = smooth(10.35, 12.15, time);

  ambient.intensity = 0.012 + earlyReveal * 0.08 + lightsOn * 0.82;
  keyLight.intensity = 0.015 + lightsOn * 4.8;
  cyanRim.intensity = 0.95 + earlyReveal * 2.6 + lightsOn * 0.72;
  blueFill.intensity = 0.02 + lightsOn * 0.85;
  renderer.toneMappingExposure = 0.54 + lightsOn * 0.46;

  glowParts.glyphMaterialX.opacity = eyeOpacity;
  glowParts.glyphMaterialHeart.opacity = eyeOpacity;
  glowParts.eyeLight.intensity = eyeOpacity * 5.4;

  let rotationY = mix(0.9, 0.55, smooth(1.2, 3.7, time));
  rotationY = mix(rotationY, 0.26, revealMove);
  rotationY = mix(rotationY, -0.06, detailMove);
  rotationY = mix(rotationY, 0.2, endMove);
  bookRoot.rotation.set(-0.075 + Math.sin(time * 0.45) * 0.012, rotationY, -0.018);

  const hover = Math.sin(time * 0.72) * 0.035;
  bookRoot.position.set(-0.18, 0.05 + hover + endMove * 0.25, 0);
  const scale = mix(0.78, 0.86, smooth(3.7, 6.4, time));
  bookRoot.scale.setScalar(mix(scale, 0.76, endMove));

  let cameraZ = mix(13.4, 12.4, revealMove);
  cameraZ = mix(cameraZ, 11.7, detailMove);
  cameraZ = mix(cameraZ, 13.7, endMove);
  camera.position.set(-0.12, 0.08, cameraZ);
  camera.lookAt(-0.16, 0.08, 0);

  setOverlay(hook, windowOpacity(time, 0.15, 0.48, 1.05, 1.34));
  setOverlay(question, windowOpacity(time, 1.55, 1.92, 3.18, 3.62));
  setOverlay(genre, windowOpacity(time, 5.05, 5.5, 7.55, 8.05), -14);
  setOverlay(endcard, smooth(10.75, 11.45, time), -16);
  setOverlay(cta, smooth(12.0, 12.72, time), 20);
  setOverlay(ageNote, smooth(12.4, 13.0, time), 8);

  const flashUp = smooth(3.76, 3.88, time);
  const flashDown = 1 - smooth(3.88, 4.1, time);
  flash.style.opacity = (flashUp * flashDown * 0.42).toFixed(4);

  renderer.render(scene, camera);
}

function fitStage() {
  const scale = Math.min(window.innerWidth / WIDTH, window.innerHeight / HEIGHT);
  stage.style.transform = `scale(${scale})`;
}

window.__VIDEO_READY = false;
window.renderVideoFrame = renderAt;

async function init() {
  const loader = new THREE.TextureLoader();
  const [frontTexture, backTexture] = await Promise.all([
    loader.loadAsync("./assets/lights-out-front.jpg"),
    loader.loadAsync("./assets/lights-out-back.jpg"),
  ]);
  for (const texture of [frontTexture, backTexture]) {
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
  }
  glowParts = buildBook(frontTexture, backTexture);
  const parameters = new URLSearchParams(window.location.search);
  const initialTime = Number(parameters.get("time") || 0);
  renderAt(Number.isFinite(initialTime) ? initialTime : 0);
  window.__VIDEO_READY = true;

  const renderOnly = parameters.get("render") === "1";
  if (!renderOnly) {
    const startedAt = performance.now();
    const loop = (now) => {
      renderAt(((now - startedAt) / 1000) % DURATION);
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }
}

window.addEventListener("resize", fitStage);
fitStage();
init();
