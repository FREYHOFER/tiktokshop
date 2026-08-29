import * as THREE from "three";

const canvas = document.querySelector("#book-canvas");
const stage = document.querySelector(".stage");

const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true,
  alpha: false,
  preserveDrawingBuffer: true,
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1;
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x202124);

function makeStudioEnvironment() {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = 1024;
  textureCanvas.height = 512;
  const context = textureCanvas.getContext("2d");
  const gradient = context.createLinearGradient(0, 0, 0, textureCanvas.height);
  gradient.addColorStop(0, "#8d9196");
  gradient.addColorStop(0.42, "#30343a");
  gradient.addColorStop(1, "#111317");
  context.fillStyle = gradient;
  context.fillRect(0, 0, textureCanvas.width, textureCanvas.height);
  context.fillStyle = "rgba(255,255,255,0.82)";
  context.fillRect(85, 72, 230, 112);
  context.fillStyle = "rgba(186,224,218,0.42)";
  context.fillRect(735, 116, 128, 230);
  context.fillStyle = "rgba(255,203,165,0.25)";
  context.fillRect(474, 352, 210, 46);
  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.mapping = THREE.EquirectangularReflectionMapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

scene.environment = makeStudioEnvironment();

const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
camera.position.set(0, 0.15, 10.5);

const bookRoot = new THREE.Group();
scene.add(bookRoot);

const bookModel = new THREE.Group();
bookRoot.add(bookModel);

const ground = new THREE.Mesh(
  new THREE.PlaneGeometry(30, 30),
  new THREE.ShadowMaterial({ color: 0x000000, opacity: 0.24 }),
);
ground.rotation.x = -Math.PI / 2;
ground.position.y = -2.08;
ground.receiveShadow = true;
scene.add(ground);

const ambient = new THREE.HemisphereLight(0xf4f0e8, 0x12151a, 1.15);
scene.add(ambient);

const keyLight = new THREE.DirectionalLight(0xffffff, 4.2);
keyLight.position.set(4.5, 7, 5);
keyLight.castShadow = true;
keyLight.shadow.mapSize.set(2048, 2048);
keyLight.shadow.camera.left = -7;
keyLight.shadow.camera.right = 7;
keyLight.shadow.camera.top = 7;
keyLight.shadow.camera.bottom = -7;
scene.add(keyLight);

const rimLight = new THREE.DirectionalLight(0x78c8b4, 2.3);
rimLight.position.set(-5, 2.5, -4);
scene.add(rimLight);

const fillLight = new THREE.DirectionalLight(0xf0aa76, 1.35);
fillLight.position.set(4, -1, -2);
scene.add(fillLight);

const state = {
  widthMm: 136,
  heightMm: 214,
  depthMm: 45,
  pages: 592,
  coverColor: "#080b0e",
  paperColor: "#eee9df",
  roughness: 0.48,
  lightStrength: 1,
  lightMode: "studio",
  coverTexture: null,
};

function makePaperBumpTexture() {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = 256;
  textureCanvas.height = 256;
  const context = textureCanvas.getContext("2d");
  context.fillStyle = "#808080";
  context.fillRect(0, 0, 256, 256);
  for (let i = 0; i < 6000; i += 1) {
    const value = 114 + Math.floor(Math.random() * 28);
    context.fillStyle = `rgba(${value},${value},${value},${0.12 + Math.random() * 0.16})`;
    const size = Math.random() > 0.97 ? 2 : 1;
    context.fillRect(Math.random() * 256, Math.random() * 256, size, size);
  }
  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(4, 6);
  return texture;
}

const paperBumpTexture = makePaperBumpTexture();

const materials = {
  cover: new THREE.MeshPhysicalMaterial({
    color: state.coverColor,
    roughness: state.roughness,
    metalness: 0,
    clearcoat: 0.18,
    clearcoatRoughness: 0.58,
    bumpMap: paperBumpTexture,
    bumpScale: 0.004,
  }),
  coverBack: new THREE.MeshPhysicalMaterial({
    color: state.coverColor,
    roughness: state.roughness,
    metalness: 0,
    clearcoat: 0.18,
    clearcoatRoughness: 0.58,
    bumpMap: paperBumpTexture,
    bumpScale: 0.004,
  }),
  spine: new THREE.MeshPhysicalMaterial({
    color: state.coverColor,
    roughness: state.roughness,
    metalness: 0,
    clearcoat: 0.16,
    clearcoatRoughness: 0.62,
    bumpMap: paperBumpTexture,
    bumpScale: 0.004,
  }),
  paper: new THREE.MeshPhysicalMaterial({
    color: state.paperColor,
    roughness: 0.94,
    sheen: 0.08,
    sheenColor: 0xffffff,
  }),
  pageEdge: new THREE.MeshStandardMaterial({
    color: state.paperColor,
    roughness: 0.9,
    bumpScale: 0.05,
  }),
  pageLine: new THREE.MeshBasicMaterial({
    color: 0x756e64,
    transparent: true,
    opacity: 0.16,
    depthWrite: false,
  }),
  coverEdge: new THREE.MeshPhysicalMaterial({
    color: 0x079bd0,
    roughness: 0.52,
    clearcoat: 0.12,
  }),
};

function makePageTexture() {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = 64;
  textureCanvas.height = 512;
  const context = textureCanvas.getContext("2d");
  context.fillStyle = state.paperColor;
  context.fillRect(0, 0, textureCanvas.width, textureCanvas.height);
  for (let y = 2; y < textureCanvas.height; y += 3) {
    const alpha = y % 12 === 2 ? 0.2 : 0.07 + Math.random() * 0.05;
    context.fillStyle = `rgba(58,50,42,${alpha})`;
    context.fillRect(0, y, textureCanvas.width, Math.random() > 0.83 ? 2 : 1);
  }
  for (let i = 0; i < 520; i += 1) {
    const shade = Math.random() > 0.5 ? 255 : 90;
    context.fillStyle = `rgba(${shade},${shade},${shade},0.035)`;
    context.fillRect(Math.random() * 64, Math.random() * 512, 1, 1);
  }
  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(1, Math.max(1, state.pages / 100));
  return texture;
}

let pageTexture = makePageTexture();
materials.pageEdge.map = pageTexture;
let originalFrontTexture = null;
let originalBackTexture = null;

function roundedBoxGeometry(width, height, depth, radius = 0.045) {
  const shape = new THREE.Shape();
  const x = -width / 2;
  const y = -height / 2;
  shape.moveTo(x + radius, y);
  shape.lineTo(x + width - radius, y);
  shape.quadraticCurveTo(x + width, y, x + width, y + radius);
  shape.lineTo(x + width, y + height - radius);
  shape.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
  shape.lineTo(x + radius, y + height);
  shape.quadraticCurveTo(x, y + height, x, y + height - radius);
  shape.lineTo(x, y + radius);
  shape.quadraticCurveTo(x, y, x + radius, y);
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth,
    bevelEnabled: true,
    bevelSegments: 3,
    steps: 1,
    bevelSize: Math.min(radius * 0.45, depth * 0.25),
    bevelThickness: Math.min(radius * 0.35, depth * 0.2),
    curveSegments: 5,
  });
  geometry.center();
  return geometry;
}

function disposeModel() {
  while (bookModel.children.length) {
    const child = bookModel.children.pop();
    child.traverse((object) => object.geometry?.dispose());
  }
}

function addPageLamination(pageWidth, pageHeight, pageDepth) {
  const layerCount = THREE.MathUtils.clamp(Math.round(state.pages / 12), 18, 42);
  const foreGeometry = new THREE.BoxGeometry(0.006, pageHeight - 0.11, 0.0035);
  const foreLayers = new THREE.InstancedMesh(foreGeometry, materials.pageLine, layerCount);
  const topGeometry = new THREE.BoxGeometry(pageWidth - 0.1, 0.006, 0.0035);
  const topLayers = new THREE.InstancedMesh(topGeometry, materials.pageLine, layerCount * 2);
  const matrix = new THREE.Matrix4();

  for (let i = 0; i < layerCount; i += 1) {
    const progress = (i + 1) / (layerCount + 1);
    const z = -pageDepth / 2 + progress * pageDepth;
    matrix.makeTranslation(pageWidth / 2 + 0.005, 0, z);
    foreLayers.setMatrixAt(i, matrix);
    matrix.makeTranslation(0, pageHeight / 2 + 0.004, z);
    topLayers.setMatrixAt(i * 2, matrix);
    matrix.makeTranslation(0, -pageHeight / 2 - 0.004, z);
    topLayers.setMatrixAt(i * 2 + 1, matrix);
  }
  foreLayers.instanceMatrix.needsUpdate = true;
  topLayers.instanceMatrix.needsUpdate = true;
  bookModel.add(foreLayers, topLayers);
}

function makeSpineTexture() {
  const textureCanvas = document.createElement("canvas");
  textureCanvas.width = 256;
  textureCanvas.height = 1536;
  const context = textureCanvas.getContext("2d");
  const gradient = context.createLinearGradient(0, 0, textureCanvas.width, 0);
  gradient.addColorStop(0, "#038dc0");
  gradient.addColorStop(0.48, "#10a8de");
  gradient.addColorStop(1, "#047ba9");
  context.fillStyle = gradient;
  context.fillRect(0, 0, textureCanvas.width, textureCanvas.height);

  context.save();
  context.translate(textureCanvas.width / 2, textureCanvas.height / 2);
  context.rotate(-Math.PI / 2);
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillStyle = "#080a0c";
  context.font = "600 52px Georgia, serif";
  context.fillText("NAVESSA ALLEN", 0, -34);
  context.font = "700 82px Georgia, serif";
  context.fillText("LIGHTS OUT", 0, 54);
  context.restore();

  const texture = new THREE.CanvasTexture(textureCanvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
  return texture;
}

const spineTexture = makeSpineTexture();
materials.spine.map = spineTexture;
materials.spine.color.set("#ffffff");

function loadProductTexture(url, material, onLoad) {
  new THREE.TextureLoader().load(url, (texture) => {
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
    material.map?.dispose();
    material.map = texture;
    material.color.set("#ffffff");
    material.needsUpdate = true;
    onLoad?.(texture);
  });
}

function rebuildBook() {
  disposeModel();

  const height = 3.55;
  const width = height * (state.widthMm / state.heightMm);
  const bookDepth = height * (state.depthMm / state.heightMm);
  const coverThickness = height * (0.75 / state.heightMm);
  const pageDepth = bookDepth - coverThickness * 2;
  const overhang = 0.012;
  const pageWidth = width - 0.028;
  const pageHeight = height - 0.026;

  const pageMaterials = [
    materials.pageEdge,
    materials.pageEdge,
    materials.pageEdge,
    materials.pageEdge,
    materials.paper,
    materials.paper,
  ];

  const pages = new THREE.Mesh(
    new THREE.BoxGeometry(pageWidth, pageHeight, pageDepth, 1, 1, 1),
    pageMaterials,
  );
  pages.castShadow = true;
  pages.receiveShadow = true;
  bookModel.add(pages);
  addPageLamination(pageWidth, pageHeight, pageDepth);

  const frontMaterials = [
    materials.coverEdge,
    materials.coverEdge,
    materials.coverEdge,
    materials.coverEdge,
    materials.cover,
    materials.coverEdge,
  ];
  const front = new THREE.Mesh(new THREE.BoxGeometry(width + overhang, height + overhang, coverThickness), frontMaterials);
  front.position.z = pageDepth / 2 + coverThickness / 2;
  front.castShadow = true;
  bookModel.add(front);

  const backMaterials = [
    materials.coverEdge,
    materials.coverEdge,
    materials.coverEdge,
    materials.coverEdge,
    materials.coverEdge,
    materials.coverBack,
  ];
  const back = new THREE.Mesh(new THREE.BoxGeometry(width + overhang, height + overhang, coverThickness), backMaterials);
  back.position.z = -pageDepth / 2 - coverThickness / 2;
  back.castShadow = true;
  bookModel.add(back);

  const spineMaterials = [
    materials.coverEdge,
    materials.spine,
    materials.coverEdge,
    materials.coverEdge,
    materials.coverEdge,
    materials.coverEdge,
  ];
  const spine = new THREE.Mesh(
    new THREE.BoxGeometry(coverThickness * 1.25, height + overhang, bookDepth),
    spineMaterials,
  );
  spine.position.x = -width / 2 - overhang / 2;
  spine.castShadow = true;
  bookModel.add(spine);

  bookModel.rotation.set(-0.08, 0.43, -0.015);
  updateReadout();
}

function updateReadout() {
  document.querySelector("#dimension-readout").textContent = `${state.widthMm} x ${state.heightMm} x ${state.depthMm} mm`;
  document.querySelector("#page-readout").textContent = `${state.pages} Seiten`;
}

function setCoverColor(value) {
  state.coverColor = value;
  for (const material of [materials.cover, materials.coverBack]) {
    material.color.set(value);
  }
  materials.coverEdge.color.set(value);
  document.querySelector("#cover-color").value = value;
}

function updatePaperTexture() {
  materials.paper.color.set(state.paperColor);
  materials.pageEdge.color.set(state.paperColor);
  pageTexture.dispose();
  pageTexture = makePageTexture();
  materials.pageEdge.map = pageTexture;
  materials.pageEdge.needsUpdate = true;
}

function setLightMode(mode) {
  state.lightMode = mode;
  const profiles = {
    studio: { ambient: 1.15, key: 4.2, rim: 2.3, fill: 1.35, exposure: 1.05 },
    soft: { ambient: 1.55, key: 2.7, rim: 1.1, fill: 1.55, exposure: 1.1 },
    dramatic: { ambient: 0.55, key: 5.7, rim: 3.7, fill: 0.45, exposure: 0.93 },
  };
  const profile = profiles[mode];
  ambient.intensity = profile.ambient * state.lightStrength;
  keyLight.intensity = profile.key * state.lightStrength;
  rimLight.intensity = profile.rim * state.lightStrength;
  fillLight.intensity = profile.fill * state.lightStrength;
  renderer.toneMappingExposure = profile.exposure;
}

function applyCoverTexture(imageUrl) {
  new THREE.TextureLoader().load(imageUrl, (texture) => {
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = renderer.capabilities.getMaxAnisotropy();
    texture.center.set(0.5, 0.5);
    texture.rotation = 0;
    state.coverTexture?.dispose();
    state.coverTexture = texture;
    materials.cover.map = texture;
    materials.cover.color.set("#ffffff");
    materials.cover.needsUpdate = true;
    document.querySelector("#clear-cover").disabled = false;
  });
}

function clearCoverTexture(restoreOriginal = true) {
  state.coverTexture?.dispose();
  state.coverTexture = null;
  materials.cover.map = restoreOriginal ? originalFrontTexture : null;
  materials.cover.color.set(restoreOriginal ? "#ffffff" : state.coverColor);
  materials.cover.needsUpdate = true;
  document.querySelector("#cover-upload").value = "";
  document.querySelector("#clear-cover").disabled = true;
}

const viewTargets = {
  front: { rotation: [-0.02, 0, 0], camera: [0, 0.15, 10.2] },
  perspective: { rotation: [-0.08, 0.43, -0.015], camera: [0, 0.15, 10.5] },
  spine: { rotation: [-0.02, Math.PI / 2, 0], camera: [0, 0.15, 9.6] },
  back: { rotation: [-0.02, Math.PI, 0], camera: [0, 0.15, 10.2] },
  top: { rotation: [0, 0.15, 0], camera: [0.2, 9.3, 0.3] },
};

let targetRotation = new THREE.Euler(-0.08, 0.43, -0.015);
let targetCamera = new THREE.Vector3(0, 0.15, 10.5);

function setView(name) {
  const target = viewTargets[name];
  targetRotation.set(...target.rotation);
  targetCamera.set(...target.camera);
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === name);
  });
}

function resetView() {
  setView("perspective");
}

let dragging = false;
let lastPointer = { x: 0, y: 0 };

canvas.addEventListener("pointerdown", (event) => {
  dragging = true;
  lastPointer = { x: event.clientX, y: event.clientY };
  canvas.setPointerCapture(event.pointerId);
});

canvas.addEventListener("pointermove", (event) => {
  if (!dragging) return;
  const dx = event.clientX - lastPointer.x;
  const dy = event.clientY - lastPointer.y;
  targetRotation.y += dx * 0.008;
  targetRotation.x = THREE.MathUtils.clamp(targetRotation.x + dy * 0.006, -1.35, 1.35);
  lastPointer = { x: event.clientX, y: event.clientY };
  document.querySelectorAll("[data-view]").forEach((button) => button.classList.remove("active"));
});

canvas.addEventListener("pointerup", () => {
  dragging = false;
});

canvas.addEventListener("pointercancel", () => {
  dragging = false;
});

canvas.addEventListener(
  "wheel",
  (event) => {
    event.preventDefault();
    const direction = targetCamera.clone().normalize();
    const distance = THREE.MathUtils.clamp(targetCamera.length() + event.deltaY * 0.008, 5.2, 11.5);
    targetCamera.copy(direction.multiplyScalar(distance));
  },
  { passive: false },
);

function bindRange(id, outputId, update, format = (value) => value) {
  const input = document.querySelector(`#${id}`);
  const output = document.querySelector(`#${outputId}`);
  input.addEventListener("input", () => {
    const value = Number(input.value);
    output.value = format(value);
    update(value);
  });
}

bindRange("book-width", "book-width-output", (value) => {
  state.widthMm = value;
  rebuildBook();
}, (value) => `${value} mm`);

bindRange("book-height", "book-height-output", (value) => {
  state.heightMm = value;
  rebuildBook();
}, (value) => `${value} mm`);

bindRange("book-depth", "book-depth-output", (value) => {
  state.depthMm = value;
  rebuildBook();
}, (value) => `${value} mm`);

bindRange("page-count", "page-count-output", (value) => {
  state.pages = value;
  updatePaperTexture();
  rebuildBook();
});

bindRange("roughness", "roughness-output", (value) => {
  state.roughness = value;
  for (const material of [materials.cover, materials.coverBack, materials.spine]) {
    material.roughness = value;
  }
}, (value) => (value > 0.62 ? "Matt" : value > 0.36 ? "Seidenmatt" : "Glanz"));

bindRange("light-strength", "light-strength-output", (value) => {
  state.lightStrength = value;
  setLightMode(state.lightMode);
}, (value) => `${Math.round(value * 100)}%`);

document.querySelector("#trim-preset").addEventListener("change", (event) => {
  const [width, height, depth = state.depthMm, pages = state.pages] = event.target.value.split(",").map(Number);
  state.widthMm = width;
  state.heightMm = height;
  state.depthMm = depth;
  state.pages = pages;
  document.querySelector("#book-width").value = width;
  document.querySelector("#book-height").value = height;
  document.querySelector("#book-depth").value = depth;
  document.querySelector("#page-count").value = pages;
  document.querySelector("#book-width-output").value = `${width} mm`;
  document.querySelector("#book-height-output").value = `${height} mm`;
  document.querySelector("#book-depth-output").value = `${depth} mm`;
  document.querySelector("#page-count-output").value = pages;
  updatePaperTexture();
  rebuildBook();
});

document.querySelectorAll(".swatch").forEach((swatch) => {
  swatch.addEventListener("click", () => {
    clearCoverTexture(false);
    setCoverColor(swatch.dataset.color);
    document.querySelectorAll(".swatch").forEach((button) => button.classList.toggle("active", button === swatch));
  });
});

document.querySelector("#cover-color").addEventListener("input", (event) => {
  clearCoverTexture(false);
  setCoverColor(event.target.value);
  document.querySelectorAll(".swatch").forEach((button) => button.classList.remove("active"));
});

document.querySelector("#paper-color").addEventListener("input", (event) => {
  state.paperColor = event.target.value;
  updatePaperTexture();
});

document.querySelectorAll("[data-light]").forEach((button) => {
  button.addEventListener("click", () => {
    setLightMode(button.dataset.light);
    document.querySelectorAll("[data-light]").forEach((item) => item.classList.toggle("active", item === button));
  });
});

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.view));
});

document.querySelector("#reset-view").addEventListener("click", resetView);

document.querySelector("#cover-upload").addEventListener("change", (event) => {
  const [file] = event.target.files;
  if (!file) return;
  const reader = new FileReader();
  reader.addEventListener("load", () => applyCoverTexture(reader.result));
  reader.readAsDataURL(file);
});

document.querySelector("#clear-cover").addEventListener("click", clearCoverTexture);

document.querySelector("#export-image").addEventListener("click", () => {
  renderer.render(scene, camera);
  const link = document.createElement("a");
  link.download = "lights-out-render.png";
  link.href = renderer.domElement.toDataURL("image/png");
  link.click();
});

function resize() {
  const width = stage.clientWidth;
  const height = stage.clientHeight;
  renderer.setSize(width, height, false);
  camera.aspect = width / Math.max(height, 1);
  camera.updateProjectionMatrix();
}

function animate() {
  bookModel.rotation.x = THREE.MathUtils.lerp(bookModel.rotation.x, targetRotation.x, 0.085);
  bookModel.rotation.y = THREE.MathUtils.lerp(bookModel.rotation.y, targetRotation.y, 0.085);
  bookModel.rotation.z = THREE.MathUtils.lerp(bookModel.rotation.z, targetRotation.z, 0.085);
  camera.position.lerp(targetCamera, 0.075);
  camera.lookAt(0, 0, 0);
  renderer.render(scene, camera);
  requestAnimationFrame(animate);
}

new ResizeObserver(resize).observe(stage);
rebuildBook();
loadProductTexture("./assets/lights-out-front.jpg", materials.cover, (texture) => {
  originalFrontTexture = texture;
  document.querySelector("#clear-cover").disabled = true;
});
loadProductTexture("./assets/lights-out-back.jpg", materials.coverBack, (texture) => {
  originalBackTexture = texture;
});
setLightMode("studio");
const requestedView = new URLSearchParams(window.location.search).get("view");
setView(viewTargets[requestedView] ? requestedView : "perspective");
resize();
animate();
