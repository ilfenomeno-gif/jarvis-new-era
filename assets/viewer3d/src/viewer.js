import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/examples/jsm/loaders/DRACOLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { RGBELoader } from "three/examples/jsm/loaders/RGBELoader.js";
import * as RAPIER from "@dimforge/rapier3d-compat";

const state = {
  markers: [], target: null, spin: true, ready: false, flights: null,
  model: null, modelStatus: "none", modelError: "", shaderError: "", partInfo: {},
  style: "hologram", controlsOn: true,
};
const PHYSICS_STEP = 1 / 60;
const PHYSICS_MAX_SUBSTEPS = 4;
const PHYSICS_DROP_HEIGHT = 2;
const PHYSICS_IMPULSE = 4;
const physics = {
  status: "loading", mode: "idle", error: "", world: null,
  activeModel: null, accumulator: 0, disposed: false,
};
RAPIER.init().then(() => {
  if (physics.disposed) return;
  physics.world = new RAPIER.World({ x: 0, y: -9.81, z: 0 });
  physics.world.timestep = PHYSICS_STEP;
  const floor = physics.world.createRigidBody(
    RAPIER.RigidBodyDesc.fixed().setTranslation(0, -0.025, 0)
  );
  physics.world.createCollider(
    RAPIER.ColliderDesc.cuboid(100, 0.025, 100).setFriction(0.8),
    floor
  );
  physics.status = "ready";
}).catch((error) => {
  physics.status = "error";
  physics.error = String(error && error.message || error).slice(0, 240);
});

function resetExplodedParts(model) {
  model.parts.forEach(part => part.node.position.copy(part.origin));
  model.explode = 0;
  model.explodeTo = 0;
}

function stopModelPhysics(model, restorePose) {
  if (!model || !model.physicsBody) return;
  if (physics.world) physics.world.removeRigidBody(model.physicsBody);
  model.physicsBody = null;
  if (restorePose && model.physicsHome) {
    model.group.position.copy(model.physicsHome.position);
    model.group.quaternion.copy(model.physicsHome.rotation);
    model.group.updateMatrixWorld(true);
  }
  model.physicsHome = null;
  if (physics.activeModel === model) {
    physics.activeModel = null;
    physics.mode = "idle";
    physics.accumulator = 0;
  }
}

function disposePhysics() {
  physics.disposed = true;
  if (physics.activeModel) stopModelPhysics(physics.activeModel, false);
  if (physics.world) physics.world.free();
  physics.world = null;
  physics.status = "disposed";
}

window.addEventListener("pagehide", disposePhysics, { once: true });

function createPhysicsBody(model) {
  const world = physics.world;
  if (!world || physics.status !== "ready") {
    throw new Error(physics.error || "Rapier WebAssembly is not ready");
  }
  const rotation = model.group.quaternion.clone();
  const position = model.group.position.clone();
  model.physicsHome = { position: position.clone(), rotation: rotation.clone() };
  const body = world.createRigidBody(
    RAPIER.RigidBodyDesc.dynamic()
      .setTranslation(position.x, position.y + PHYSICS_DROP_HEIGHT, position.z)
      .setRotation({ x: rotation.x, y: rotation.y, z: rotation.z, w: rotation.w })
  );
  const [x, y, z] = model.physicsHalfExtents;
  world.createCollider(
    RAPIER.ColliderDesc.cuboid(x, y, z).setFriction(0.8).setRestitution(0.05),
    body
  );
  model.physicsBody = body;
  physics.activeModel = model;
  return body;
}

function stepPhysics(dt) {
  const model = physics.activeModel;
  if (!physics.world || !model || !model.physicsBody) return;
  physics.accumulator += Math.min(dt, 0.1);
  let steps = 0;
  while (physics.accumulator >= PHYSICS_STEP && steps < PHYSICS_MAX_SUBSTEPS) {
    physics.world.step();
    physics.accumulator -= PHYSICS_STEP;
    steps++;
  }
  if (steps === PHYSICS_MAX_SUBSTEPS) physics.accumulator = 0;
  const position = model.physicsBody.translation();
  const rotation = model.physicsBody.rotation();
  model.group.position.set(position.x, position.y, position.z);
  model.group.quaternion.set(rotation.x, rotation.y, rotation.z, rotation.w);
  model.group.updateMatrixWorld(true);
}
const canvas = document.getElementById("c");
// Senza WebGL (GPU in blocklist) il viewer resta controllabile ma non disegna.
let renderer = null;
try {
  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, stencil: true });
  renderer.setClearColor(0x000308, 1);
  renderer.localClippingEnabled = true;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.debug.onShaderError = () => { state.shaderError = "shader compile failed"; };
} catch (e) {
  console.error("WebGL non disponibile: " + e.message);
}
const scene = new THREE.Scene();
const clipStencilScene = new THREE.Scene();
const clipCapsScene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
camera.position.set(0, 0, 4.2);

// Drag = rotate, wheel = zoom, right button = pan. Only active while a model is shown
// (the globe is driven by flyTo/spin) and while setControls(true) is in effect.
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.12;
controls.minDistance = 1.2;
controls.maxDistance = 12;
controls.enabled = false;
controls.addEventListener("start", () => { state.spin = false; });
function syncControls() { controls.enabled = state.controlsOn && !!state.model; }
function resetCamera() {
  camera.position.set(0, 0, 4.2);
  controls.target.set(0, 0, 0);
  controls.update();
}

const globe = new THREE.Group();
scene.add(globe);
const cyan = 0x00d4ff;
const hudAnimation = {
  state: "idle", color: new THREE.Color(cyan), fromColor: new THREE.Color(cyan),
  targetColor: new THREE.Color(cyan), ringSpeed: 0.55, fromRingSpeed: 0.55,
  targetRingSpeed: 0.55, glow: 0.8, fromGlow: 0.8, targetGlow: 0.8,
  particles: 3, fromParticles: 3, targetParticles: 3, started: performance.now(),
  duration: 0.3,
};

// Only the solid styles (blueprint, realistic) are lit; globe and hologram are unlit.
const hemiLight = new THREE.HemisphereLight(0xcfe8ff, 0x10203a, 1.6);
scene.add(hemiLight);
const keyLight = new THREE.DirectionalLight(0xffffff, 2.4);
keyLight.position.set(2, 3, 4);
// Shadows are only cast in the realistic style (see syncLook).
keyLight.shadow.mapSize.set(2048, 2048);
keyLight.shadow.camera.left = -2.2; keyLight.shadow.camera.right = 2.2;
keyLight.shadow.camera.top = 2.2; keyLight.shadow.camera.bottom = -2.2;
keyLight.shadow.camera.near = 0.5; keyLight.shadow.camera.far = 12;
keyLight.shadow.camera.updateProjectionMatrix();
keyLight.shadow.bias = -0.0005;
keyLight.shadow.normalBias = 0.02;
scene.add(keyLight);

const TEXTURE_SLOTS = ["map", "normalMap", "roughnessMap", "metalnessMap", "aoMap", "emissiveMap",
  "bumpMap", "displacementMap", "alphaMap", "lightMap", "envMap", "specularMap", "gradientMap",
  "clearcoatMap", "clearcoatNormalMap", "clearcoatRoughnessMap", "sheenColorMap", "sheenRoughnessMap",
  "transmissionMap", "thicknessMap", "specularIntensityMap", "specularColorMap", "iridescenceMap",
  "iridescenceThicknessMap", "anisotropyMap"];

function disposeMaterial(m) {
  if (!m) return;
  TEXTURE_SLOTS.forEach(k => { if (m[k] && m[k].isTexture) m[k].dispose(); });
  m.dispose();
}

// Frees geometries, materials and every texture map of a model (material.dispose() alone keeps textures on the GPU).
function disposeObject(root) {
  if (!root) return;
  root.traverse(o => {
    if (o.geometry) o.geometry.dispose();
    [].concat(o.material || [], (o.userData && o.userData.base) || [], (o.userData && o.userData.orig) || [])
      .forEach(disposeMaterial);
  });
}

// Models may only reference files inside models/ (or embedded data/blob URIs).
const loadingManager = new THREE.LoadingManager();
loadingManager.setURLModifier((url) => {
  if (/^(data|blob):/i.test(url)) return url;
  const safe = /^models\//.test(url) && !/^[a-z][a-z0-9+.-]*:/i.test(url) && !url.split(/[?#]/)[0].split("/").includes("..");
  if (!safe) {
    console.warn("blocked external resource: " + url);
    return "data:,";
  }
  return url;
});
const dracoLoader = new DRACOLoader().setDecoderPath("draco/");
const gltfLoader = new GLTFLoader(loadingManager);
gltfLoader.setDRACOLoader(dracoLoader);
gltfLoader.setMeshoptDecoder(MeshoptDecoder);
let loadToken = 0;

// Invisible floor that only shows the model's shadow.
const shadowFloor = new THREE.Mesh(
  new THREE.PlaneGeometry(8, 8),
  new THREE.ShadowMaterial({ opacity: 0.45 })
);
shadowFloor.rotation.x = -Math.PI / 2;
shadowFloor.receiveShadow = true;
shadowFloor.visible = false;
scene.add(shadowFloor);

// Studio HDRI (Poly Haven, CC0): loaded once, on first use of the realistic style.
let envMap = null;
let envLoading = false;
function loadEnvironment() {
  if (!renderer || envMap || envLoading) return;
  envLoading = true;
  new RGBELoader().load(
    "hdr/studio.hdr",
    (tex) => {
      const pmrem = new THREE.PMREMGenerator(renderer);
      envMap = pmrem.fromEquirectangular(tex).texture;
      tex.dispose();
      pmrem.dispose();
      envLoading = false;
      syncLook();
    },
    undefined,
    () => { envLoading = false; state.envError = "hdri not loaded"; }
  );
}

// Realistic = PBR look: environment reflections, tone mapping, shadows. The other styles
// keep their flat look (no environment, no tone mapping, no shadow pass).
function syncLook() {
  if (!renderer) return;
  const realistic = !!state.model && state.model.style === "realistic";
  if (realistic) loadEnvironment();
  // Only dim the stage lights once the HDRI is really there to replace them.
  const hdriLit = realistic && !!envMap;
  scene.environment = realistic ? envMap : null;
  // The HDRI already lights the model: lower the stage lights so metal does not blow out.
  hemiLight.intensity = hdriLit ? 0.15 : 1.6;
  keyLight.intensity = hdriLit ? 1.1 : 2.4;
  scene.environmentIntensity = 0.4;
  const tone = realistic ? THREE.ACESFilmicToneMapping : THREE.NoToneMapping;
  if (renderer.toneMapping !== tone) {
    renderer.toneMapping = tone;
    scene.traverse(o => { if (o.material) [].concat(o.material).forEach(m => { m.needsUpdate = true; }); });
  }
  keyLight.castShadow = realistic;
  shadowFloor.visible = realistic;
  if (state.model) {
    state.model.meshes.forEach(o => { o.castShadow = realistic; o.receiveShadow = realistic; });
    if (realistic) {
      state.model.group.updateMatrixWorld(true);
      shadowFloor.position.y = new THREE.Box3().setFromObject(state.model.group).min.y - 0.02;
    }
  }
}

const coreGlow = new THREE.Mesh(
  new THREE.SphereGeometry(1.16, 32, 24),
  new THREE.MeshBasicMaterial({
    color: cyan, transparent: true, opacity: 0.025,
    blending: THREE.AdditiveBlending, depthWrite: false,
  })
);
globe.add(coreGlow);
const sphereMaterial = new THREE.MeshBasicMaterial({
  color: cyan, wireframe: true, transparent: true, opacity: 0.18,
});
const sphere = new THREE.Mesh(new THREE.SphereGeometry(1, 48, 32), sphereMaterial);
globe.add(sphere);
const coreMaterial = new THREE.MeshBasicMaterial({
  color: 0x001018, transparent: true, opacity: 0.85,
});
globe.add(new THREE.Mesh(new THREE.SphereGeometry(0.985, 32, 24), coreMaterial));

const HUD_PARTICLE_MAX = 100;
const hudParticleGeometry = new THREE.BufferGeometry();
hudParticleGeometry.setAttribute(
  "position", new THREE.BufferAttribute(new Float32Array(HUD_PARTICLE_MAX * 3), 3)
);
const hudParticleMaterial = new THREE.PointsMaterial({
  color: cyan, size: 0.035, transparent: true, opacity: 0.85,
  blending: THREE.AdditiveBlending, depthWrite: false,
});
const hudParticles = new THREE.Points(hudParticleGeometry, hudParticleMaterial);
globe.add(hudParticles);

const rings = [];
for (let i = 0; i < 3; i++) {
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(1.25 + i * 0.12, 1.26 + i * 0.12, 128),
    new THREE.MeshBasicMaterial({ color: cyan, transparent: true, opacity: 0.35 - i * 0.08, side: THREE.DoubleSide })
  );
  ring.rotation.x = Math.PI / 2.3 + i * 0.25;
  scene.add(ring);
  rings.push(ring);
}

function toVec(lat, lon, r) {
  const phi = (90 - lat) * Math.PI / 180;
  const theta = (lon + 180) * Math.PI / 180;
  return new THREE.Vector3(
    -r * Math.sin(phi) * Math.cos(theta),
    r * Math.cos(phi),
    r * Math.sin(phi) * Math.sin(theta)
  );
}

function resize() {
  const w = canvas.clientWidth || 1, h = canvas.clientHeight || 1;
  if (renderer) renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);

// Rotation that brings (lat, lon) to face the camera (+z).
function rotationFor(lat, lon) {
  const target = toVec(lat, lon, 1).normalize();
  return new THREE.Quaternion().setFromUnitVectors(target, new THREE.Vector3(0, 0, 1));
}

const clip = { axis: "", position: 0.5 };
const CLIP_NORMALS = { x: [-1, 0, 0], y: [0, -1, 0], z: [0, 0, -1] };

function updateClipTransform(m) {
  m.group.updateMatrixWorld(true);
  m.clipWorldPlane.copy(m.clipPlane).applyMatrix4(m.group.matrixWorld);
}

function updateClipCap(m, coordinate) {
  const size = m.clipBounds.getSize(new THREE.Vector3());
  const dimensions = clip.axis === "x"
    ? [size.z, size.y]
    : clip.axis === "y" ? [size.x, size.z] : [size.x, size.y];
  if (m.clipCapAxis !== clip.axis) {
    m.clipCap.geometry.dispose();
    m.clipCap.geometry = new THREE.PlaneGeometry(
      Math.max(dimensions[0] * 1.02, dimensions[0] + 0.01),
      Math.max(dimensions[1] * 1.02, dimensions[1] + 0.01)
    );
    m.clipCap.rotation.set(0, 0, 0);
    if (clip.axis === "x") m.clipCap.rotation.y = Math.PI / 2;
    else if (clip.axis === "y") m.clipCap.rotation.x = Math.PI / 2;
    m.clipCapAxis = clip.axis;
  }
  m.clipCap.position.set(0, 0, 0);
  m.clipCap.position[clip.axis] = coordinate;
  m.clipCap.updateMatrix();
  m.clipCapLocalMatrix.copy(m.clipCap.matrix);
}

function updateClipPlane() {
  const m = state.model;
  if (!m || !clip.axis) return false;
  const normal = CLIP_NORMALS[clip.axis];
  const lo = m.clipBounds.min[clip.axis], hi = m.clipBounds.max[clip.axis];
  const coordinate = lo + (hi - lo) * clip.position;
  m.clipPlane.normal.set(normal[0], normal[1], normal[2]);
  m.clipPlane.constant = coordinate;
  updateClipCap(m, coordinate);
  updateClipTransform(m);
  return true;
}

function syncClip() {
  const m = state.model;
  if (!m) return;
  const on = !!clip.axis;
  if (on) updateClipPlane();
  m.group.traverse(o => {
    if (o === m.clipCap || !(o.isMesh || o.isLine)) return;
    [].concat(o.material).forEach(mat => {
      if (!mat) return;
      mat.clippingPlanes = on ? [m.clipWorldPlane] : null;
      if (mat.isShaderMaterial) mat.clipping = true;
      if (on && mat.userData.side0 === undefined) {
        mat.userData.side0 = mat.side;
        mat.side = THREE.DoubleSide;
      } else if (!on && mat.userData.side0 !== undefined) {
        mat.side = mat.userData.side0;
        delete mat.userData.side0;
      }
      mat.needsUpdate = true;
    });
  });
  m.clipCap.visible = on;
}

function createClipResources(m, bounds) {
  m.clipBounds = bounds.clone();
  m.clipPlane = new THREE.Plane();
  m.clipWorldPlane = new THREE.Plane();
  const baseMaterial = new THREE.MeshBasicMaterial({
    depthWrite: false,
    depthTest: false,
    colorWrite: false,
    stencilWrite: true,
    stencilFunc: THREE.AlwaysStencilFunc,
  });
  m.clipBackMaterial = baseMaterial.clone();
  m.clipBackMaterial.side = THREE.BackSide;
  m.clipBackMaterial.stencilFail = THREE.IncrementWrapStencilOp;
  m.clipBackMaterial.stencilZFail = THREE.IncrementWrapStencilOp;
  m.clipBackMaterial.stencilZPass = THREE.IncrementWrapStencilOp;
  m.clipBackMaterial.clippingPlanes = [m.clipWorldPlane];
  m.clipFrontMaterial = baseMaterial.clone();
  m.clipFrontMaterial.side = THREE.FrontSide;
  m.clipFrontMaterial.stencilFail = THREE.DecrementWrapStencilOp;
  m.clipFrontMaterial.stencilZFail = THREE.DecrementWrapStencilOp;
  m.clipFrontMaterial.stencilZPass = THREE.DecrementWrapStencilOp;
  m.clipFrontMaterial.clippingPlanes = [m.clipWorldPlane];
  baseMaterial.dispose();

  m.clipCapMaterial = new THREE.MeshStandardMaterial({
    color: 0x536b78,
    metalness: 0.12,
    roughness: 0.78,
    side: THREE.DoubleSide,
    stencilWrite: true,
    stencilRef: 0,
    stencilFunc: THREE.NotEqualStencilFunc,
    stencilFail: THREE.ReplaceStencilOp,
    stencilZFail: THREE.ReplaceStencilOp,
    stencilZPass: THREE.ReplaceStencilOp,
  });
  m.clipCap = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), m.clipCapMaterial);
  m.clipCap.matrixAutoUpdate = false;
  m.clipCap.onAfterRender = activeRenderer => activeRenderer.clearStencil();
  m.clipCapLocalMatrix = new THREE.Matrix4();
  clipCapsScene.add(m.clipCap);
}

function renderClippedScene() {
  if (!clip.axis) {
    renderer.render(scene, camera);
    return;
  }
  const autoClear = renderer.autoClear;
  renderer.autoClear = false;
  try {
    updateClipTransform(state.model);
    renderer.clear(true, true, true);
    renderer.render(scene, camera);
    const m = state.model;
    if (m && m.clipCap.visible && m.group.visible) {
      renderer.clearStencil();
      const originalMaterials = m.meshes.map(mesh => mesh.material);
      scene.remove(m.group);
      clipStencilScene.add(m.group);
      try {
        m.meshes.forEach(mesh => { mesh.material = m.clipBackMaterial; });
        renderer.render(clipStencilScene, camera);
        m.meshes.forEach(mesh => { mesh.material = m.clipFrontMaterial; });
        renderer.render(clipStencilScene, camera);
      } finally {
        m.meshes.forEach((mesh, index) => { mesh.material = originalMaterials[index]; });
        clipStencilScene.remove(m.group);
        scene.add(m.group);
      }
      updateClipTransform(m);
      m.clipCap.matrix.copy(m.group.matrixWorld).multiply(m.clipCapLocalMatrix);
      m.clipCap.matrixWorldNeedsUpdate = true;
      renderer.render(clipCapsScene, camera);
    }
  } finally {
    renderer.autoClear = autoClear;
  }
}

let last = performance.now();
function frame(now) {
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  updateHudAnimation(now);
  if (state.target) {
    globe.quaternion.slerp(state.target, Math.min(1, dt * 3));
    if (globe.quaternion.angleTo(state.target) < 0.005) {
      globe.quaternion.copy(state.target);
    }
  } else if (state.spin) {
    globe.rotation.y += dt * 0.25;
  }
  rings.forEach((r, i) => { r.rotation.z += dt * (0.2 + i * 0.1) * hudAnimation.ringSpeed; });
  updateHudParticles(now);
  if (state.model && state.model.holo.length) {
    state.model.holo.forEach(m => { m.uniforms.uTime.value = now / 1000; });
  }
  if (state.model && state.spin) state.model.group.rotation.y += dt * 0.4;
  if (state.model && state.model.parts.length) {
    const m = state.model;
    m.explode += (m.explodeTo - m.explode) * Math.min(1, dt * 4);
    if (Math.abs(m.explodeTo - m.explode) < 0.002) m.explode = m.explodeTo;
    m.parts.forEach(p => p.node.position.copy(p.origin).addScaledVector(p.dir, p.dist * m.explode));
  }
  stepPhysics(dt);
  pickPart(now);
  if (controls.enabled) controls.update();
  if (renderer) renderClippedScene();
  requestAnimationFrame(frame);
}

function updateHudAnimation(now) {
  const progress = hudAnimation.duration <= 0
    ? 1 : Math.min(1, Math.max(0, (now - hudAnimation.started) / (hudAnimation.duration * 1000)));
  const eased = progress * progress * (3 - 2 * progress);
  hudAnimation.color.copy(hudAnimation.fromColor).lerp(hudAnimation.targetColor, eased);
  hudAnimation.ringSpeed = THREE.MathUtils.lerp(hudAnimation.fromRingSpeed, hudAnimation.targetRingSpeed, eased);
  hudAnimation.glow = THREE.MathUtils.lerp(hudAnimation.fromGlow, hudAnimation.targetGlow, eased);
  hudAnimation.particles = THREE.MathUtils.lerp(hudAnimation.fromParticles, hudAnimation.targetParticles, eased);
  sphereMaterial.color.copy(hudAnimation.color);
  coreMaterial.color.copy(hudAnimation.color).multiplyScalar(0.06);
  coreGlow.material.color.copy(hudAnimation.color);
  coreGlow.material.opacity = Math.min(0.12, 0.025 * hudAnimation.glow);
  hudParticleMaterial.color.copy(hudAnimation.color);
  hudParticleMaterial.opacity = Math.min(1, 0.55 + hudAnimation.glow * 0.2);
}

function updateHudParticles(now) {
  const count = Math.min(HUD_PARTICLE_MAX, Math.max(0, Math.round(hudAnimation.particles)));
  const positions = hudParticleGeometry.attributes.position;
  const time = now / 1000;
  for (let i = 0; i < count; i++) {
    const phase = i * 2.399963;
    const orbit = time * (0.25 + hudAnimation.ringSpeed * 0.12) + phase;
    const latitude = Math.sin(phase * 1.7 + time * 0.18) * 0.82;
    const radius = 1.12 + 0.16 * Math.sin(phase + time * 0.8);
    const planar = Math.sqrt(1 - latitude * latitude);
    positions.setXYZ(i, Math.cos(orbit) * planar * radius, latitude * radius, Math.sin(orbit) * planar * radius);
  }
  positions.needsUpdate = count > 0;
  hudParticleGeometry.setDrawRange(0, count);
}

function num(v, lo, hi, name) {
  const n = Number(v);
  if (!Number.isFinite(n) || n < lo || n > hi) throw new Error(name + " out of range");
  return n;
}

// Parts are the first level of nodes that actually splits the model.
function collectParts(root, size) {
  let level = [root];
  for (let i = 0; i < 6; i++) {
    const next = level.flatMap(o => o.children);
    if (next.length === 0) return [];
    if (next.length > 1) { level = next; break; }
    level = next;
  }
  if (level.length < 2) return [];
  // A split into just two chunks is a poor explosion: open up to three more levels.
  for (let k = 0; k < 3 && level.length < 3; k++) {
    const deeper = level.flatMap(o => (o.children.length ? o.children : [o]));
    if (deeper.length === level.length) break;
    level = deeper;
  }
  const all = new THREE.Box3().setFromObject(root).getCenter(new THREE.Vector3());
  return level.map((node, i) => {
    const c = new THREE.Box3().setFromObject(node).getCenter(new THREE.Vector3());
    const dir = node.parent.worldToLocal(c).sub(node.parent.worldToLocal(all.clone()));
    if (dir.lengthSq() < 1e-8) dir.set(Math.cos(i * 2.4), Math.sin(i * 2.4), 0.3);
    return { node, origin: node.position.clone(), dir: dir.normalize(), dist: size * 0.6, saved: null };
  });
}

function findNode(root, name) {
  let hit = null;
  root.traverse(o => { if (!hit && o.name === name) hit = o; });
  return hit;
}

const HOLO_COLOR = 0x00d4ff;
const HOLO_VERT = `
varying vec3 vNormal; varying vec3 vView; varying float vY;
void main() {
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  vNormal = normalize(normalMatrix * normal);
  vView = normalize(-mv.xyz);
  vY = (modelMatrix * vec4(position, 1.0)).y;
  gl_Position = projectionMatrix * mv;
}`;
const HOLO_FRAG = `
uniform vec3 uColor; uniform float uTime;
varying vec3 vNormal; varying vec3 vView; varying float vY;
void main() {
  float fres = pow(1.0 - abs(dot(normalize(vNormal), normalize(vView))), 2.0);
  float scan = 0.55 + 0.45 * sin(vY * 90.0 - uTime * 3.0);
  float glitch = step(0.985, fract(sin(floor(uTime * 8.0) + floor(vY * 20.0)) * 43758.5453));
  float a = (0.22 + fres * 0.75) * scan + glitch * 0.3;
  gl_FragColor = vec4(uColor * (0.7 + fres), a);
}`;

function holoMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: { uColor: { value: new THREE.Color(HOLO_COLOR) }, uTime: { value: 0 } },
    vertexShader: HOLO_VERT,
    fragmentShader: HOLO_FRAG,
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending,
  });
}

const BLUEPRINT_COLOR = 0x0055ff;
const EDGE_COLOR = 0x00f0ff;
const STYLES = ["hologram", "blueprint", "realistic", "flat", "toon"];

function meshesOf(root) {
  const list = [];
  root.traverse(o => { if (o.isMesh) list.push(o); });
  return list;
}

function blueprintMaterial() {
  return new THREE.MeshStandardMaterial({
    color: BLUEPRINT_COLOR, roughness: 0.8, metalness: 0.2, side: THREE.DoubleSide,
    // Pushes the faces back so the edge lines do not z-fight with them.
    polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
  });
}

// Three flat tone bands for the toon look; NearestFilter keeps the steps hard.
let toonRamp = null;
function toonGradient() {
  if (!toonRamp) {
    toonRamp = new THREE.DataTexture(new Uint8Array([90, 170, 255]), 3, 1, THREE.RedFormat);
    toonRamp.minFilter = toonRamp.magFilter = THREE.NearestFilter;
    toonRamp.needsUpdate = true;
  }
  return toonRamp;
}

// 2D artwork: keep the original colours/texture but drop the PBR lighting that dirties them.
// flat = unlit; toon = cartoon shading. Both keep the model's own map or vertex colours.
function drawnMaterial(base, style) {
  const src = [].concat(base)[0];
  const opts = { color: src.color ? src.color.clone() : new THREE.Color(0xffffff), side: THREE.DoubleSide };
  if (src.map) opts.map = src.map;
  if (src.vertexColors) opts.vertexColors = true;
  if (src.transparent || src.alphaTest) { opts.transparent = src.transparent; opts.alphaTest = src.alphaTest; }
  if (style === "toon") return new THREE.MeshToonMaterial({ ...opts, gradientMap: toonGradient() });
  return new THREE.MeshBasicMaterial(opts);
}

// Callers clear any glow first: this swaps the materials the glow clones from.
function applyStyle(model, style) {
  model.holo = [];
  model.meshes.forEach(o => {
    if (o.userData.base) {
      o.material.dispose();
      o.material = o.userData.base;
      delete o.userData.base;
      delete o.userData.holo;
      delete o.userData.glow;
    }
    if (o.userData.edgeLines) {
      const lines = o.userData.edgeLines;
      o.remove(lines);
      lines.geometry.dispose();
      lines.material.dispose();
      delete o.userData.edgeLines;
    }
    if (style === "hologram") {
      if (!o.geometry.attributes.normal) o.geometry.computeVertexNormals();
      o.userData.base = o.material;
      o.material = holoMaterial();
      o.userData.holo = true;
      model.holo.push(o.material);
    } else if (style === "blueprint") {
      o.userData.base = o.material;
      o.material = blueprintMaterial();
      const lines = new THREE.LineSegments(
        new THREE.EdgesGeometry(o.geometry, 45),
        new THREE.LineBasicMaterial({ color: EDGE_COLOR })
      );
      o.add(lines);
      o.userData.edgeLines = lines;
    } else if (style === "flat" || style === "toon") {
      o.userData.base = o.material;
      o.material = drawnMaterial(o.material, style);
    }
  });
  model.style = style;
  model.hologram = style === "hologram";
}

// Hover tooltip: raycasting is throttled and only runs when the mouse moved.
const tip = document.getElementById("tip");
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const hover = { x: 0, y: 0, pending: false, last: 0, rays: 0, name: "", text: "" };
const RAY_INTERVAL_MS = 50;

// Hover events reach Python through QWebChannel (see ViewerBridge in ui.py).
let bridge = null;
if (window.qt && window.qt.webChannelTransport && typeof QWebChannel !== "undefined") {
  new QWebChannel(window.qt.webChannelTransport, (channel) => { bridge = channel.objects.bridge || null; });
}
function emitHover(name, text) {
  if (bridge) bridge.onHover(String(name), String(text));
}

function hideTip() {
  if (hover.name) emitHover("", "");
  hover.name = ""; hover.text = "";
  if (tip) tip.style.display = "none";
}

function placeTip() {
  if (!tip) return;
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.max(0, Math.min(hover.x + 14, window.innerWidth - w - 4)) + "px";
  tip.style.top = Math.max(0, Math.min(hover.y + 16, window.innerHeight - h - 4)) + "px";
}

function showTip(name, text) {
  hover.name = name; hover.text = text;
  emitHover(name, text);
  if (!tip) return;
  tip.textContent = "";
  const title = document.createElement("b");
  title.textContent = name;
  tip.appendChild(title);
  if (text) {
    const body = document.createElement("div");
    body.textContent = text;
    tip.appendChild(body);
  }
  tip.style.display = "block";
  placeTip();
}

// TripoSR names its single mesh "geometry_0": show the model's own name instead.
const GENERIC_NAME = /^geometry(_?\d+)?$/i;
function modelLabel() {
  const file = state.model ? state.model.name : "";
  let base = file.split("/").pop().replace(/\.(glb|gltf)$/i, "");
  base = base.replace(/-[0-9a-f]{6}$/i, "").replace(/^image-/i, "").replace(/[-_]+/g, " ").trim();
  return base ? base.charAt(0).toUpperCase() + base.slice(1) : "Modello";
}

// Nearest named ancestor (the model root itself is not a part); a described one wins.
function partAt(obj, root) {
  let first = "";
  for (let o = obj; o && o !== root; o = o.parent) {
    if (!o.name) continue;
    const shown = GENERIC_NAME.test(o.name) ? modelLabel() : o.name;
    if (!first) first = shown;
    if (Object.prototype.hasOwnProperty.call(state.partInfo, shown)) {
      return { name: shown, text: state.partInfo[shown] };
    }
  }
  if (first) return { name: first, text: "" };
  // Unnamed nodes (e.g. Khronos engine models): label by top-level part.
  const m = state.model;
  const idx = m ? m.parts.findIndex(p => { for (let o = obj; o; o = o.parent) if (o === p.node) return true; return false; }) : -1;
  if (idx >= 0) {
    const key = "Parte " + (idx + 1);
    return { name: key, text: Object.prototype.hasOwnProperty.call(state.partInfo, key) ? state.partInfo[key] : "" };
  }
  return { name: "", text: "" };
}

function pickPart(now) {
  if (!hover.pending || now - hover.last < RAY_INTERVAL_MS) return;
  hover.last = now;
  const m = state.model;
  if (!m || !m.group.visible) { hover.pending = false; hideTip(); return; }
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  pointer.set(((hover.x - rect.left) / rect.width) * 2 - 1, -((hover.y - rect.top) / rect.height) * 2 + 1);
  scene.updateMatrixWorld();
  camera.updateMatrixWorld();
  raycaster.setFromCamera(pointer, camera);
  hover.rays++;
  const hit = raycaster.intersectObjects(m.meshes, false)[0];
  const part = hit ? partAt(hit.object, m.root) : { name: "", text: "" };
  if (!part.name) { hover.pending = false; hideTip(); return; }
  // While the tooltip is up keep re-testing (a spinning model moves under the cursor).
  if (part.name !== hover.name || part.text !== hover.text) showTip(part.name, part.text);
  else placeTip();
}

canvas.addEventListener("mousemove", (e) => {
  hover.x = e.clientX; hover.y = e.clientY; hover.pending = true;
  if (tip && tip.style.display === "block") placeTip();
});
canvas.addEventListener("mouseleave", () => { hover.pending = false; hideTip(); });

function setGlow(node, on) {
  node.traverse(o => {
    if (!o.isMesh) return;
    if (o.userData.holo) {
      o.userData.glow = on;
      o.material.uniforms.uColor.value.setHex(on ? 0xffd400 : HOLO_COLOR);
      return;
    }
    if (on && !o.userData.orig) {
      o.userData.orig = o.material;
      o.material = [].concat(o.material).map(m => {
        const c = m.clone();
        if (c.emissive) { c.emissive.setHex(0x00d4ff); c.emissiveIntensity = 1.2; }
        else if (c.color) c.color.setHex(0x00d4ff);
        return c;
      });
      if (o.material.length === 1) o.material = o.material[0];
    } else if (!on && o.userData.orig) {
      [].concat(o.material).forEach(m => m.dispose());
      o.material = o.userData.orig;
      delete o.userData.orig;
    }
  });
}

function nodeNames(root) {
  const out = [];
  root.traverse(o => { if (o !== root && o.name) out.push(o.name); });
  return out;
}

window.jarvisViewer = {
  flyTo(lat, lon) {
    state.target = rotationFor(num(lat, -90, 90, "lat"), num(lon, -180, 180, "lon"));
    state.spin = false;
  },
  addMarker(lat, lon, label) {
    lat = num(lat, -90, 90, "lat"); lon = num(lon, -180, 180, "lon");
    const dot = new THREE.Mesh(
      new THREE.SphereGeometry(0.025, 12, 12),
      new THREE.MeshBasicMaterial({ color: 0xffd400 })
    );
    dot.position.copy(toVec(lat, lon, 1.01));
    globe.add(dot);
    state.markers.push({ lat, lon, label: String(label || "").slice(0, 60), obj: dot });
  },
  clearMarkers() {
    state.markers.forEach(m => globe.remove(m.obj));
    state.markers = [];
  },
  setFlights(list) {
    this.clearFlights();
    const pos = new Float32Array(list.length * 3);
    list.forEach((f, i) => toVec(f[0], f[1], 1.02).toArray(pos, i * 3));
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    const pts = new THREE.Points(geo, new THREE.PointsMaterial({
      color: 0xffd400, size: 0.028, sizeAttenuation: true, depthTest: true,
    }));
    globe.add(pts);
    state.flights = { obj: pts, list: list.map(f => ({ lat: f[0], lon: f[1], callsign: f[2] })) };
  },
  clearFlights() {
    if (state.flights) { globe.remove(state.flights.obj); state.flights.obj.geometry.dispose(); }
    state.flights = null;
  },
  setHudState(name, color, ringSpeed, glow, particles, transitionSeconds) {
    name = String(name);
    color = String(color);
    if (!["idle", "listening", "thinking", "speaking", "error", "generating_3d"].includes(name)) {
      throw new Error("unsupported HUD state");
    }
    if (!/^#[0-9a-fA-F]{6}$/.test(color)) throw new Error("invalid HUD color");
    updateHudAnimation(performance.now());
    hudAnimation.state = name;
    hudAnimation.fromColor.copy(hudAnimation.color);
    hudAnimation.targetColor.set(color);
    hudAnimation.fromRingSpeed = hudAnimation.ringSpeed;
    hudAnimation.targetRingSpeed = num(ringSpeed, 0, 5, "ring speed");
    hudAnimation.fromGlow = hudAnimation.glow;
    hudAnimation.targetGlow = num(glow, 0, 3, "glow intensity");
    hudAnimation.fromParticles = hudAnimation.particles;
    hudAnimation.targetParticles = num(particles, 0, HUD_PARTICLE_MAX, "particle count");
    hudAnimation.started = performance.now();
    hudAnimation.duration = num(transitionSeconds, 0, 5, "transition");
  },
  loadModel(name) {
    this.removeModel();
    const token = ++loadToken;
    state.modelStatus = "loading";
    gltfLoader.load(
      "models/" + name.split("/").map(encodeURIComponent).join("/"),
      (gltf) => {
        if (token !== loadToken) { disposeObject(gltf.scene); return; }
        const root = gltf.scene;
        const box = new THREE.Box3().setFromObject(root);
        const size = box.getSize(new THREE.Vector3());
        const scale = 1.6 / (Math.max(size.x, size.y, size.z) || 1);
        const group = new THREE.Group();
        const center = box.getCenter(new THREE.Vector3());
        root.position.sub(center);
        group.add(root);
        group.scale.setScalar(scale);
        scene.add(group);
        group.updateMatrixWorld(true);
        state.model = {
          group, root, name, meshes: meshesOf(root),
          parts: collectParts(root, Math.max(size.x, size.y, size.z) || 1),
          physicsHalfExtents: [
            Math.max(size.x * scale / 2, 0.02),
            Math.max(size.y * scale / 2, 0.02),
            Math.max(size.z * scale / 2, 0.02),
          ],
          physicsBody: null, physicsHome: null,
          explode: 0, explodeTo: 0, highlight: "", holo: [], hologram: false, style: "hologram",
        };
        createClipResources(state.model, box.clone().translate(center.clone().negate()));
        applyStyle(state.model, state.style);
        syncClip();
        syncLook();
        state.modelStatus = "ready";
        syncControls();
        globe.visible = false;
        rings.forEach(r => { r.visible = false; });
      },
      undefined,
      (err) => {
        if (token !== loadToken) return;
        state.modelStatus = "error"; state.modelError = String(err && err.message || err);
      }
    );
  },
  setClipping(axis, position) {
    axis = String(axis).toLowerCase();
    if (axis === "off" || axis === "none" || axis === "") {
      clip.axis = "";
    } else {
      if (!CLIP_NORMALS[axis]) throw new Error("axis must be x, y, z or off");
      if (!state.model) throw new Error("no model loaded to cut");
      clip.axis = axis;
      clip.position = num(position === undefined ? 0.5 : position, 0, 1, "position");
      state.spin = false;
      updateClipPlane();
    }
    syncClip();
  },
  explodeModel(on) {
    const model = state.model;
    if (!model) return;
    if (on) {
      stopModelPhysics(model, true);
      resetExplodedParts(model);
    }
    model.explodeTo = on ? 1 : 0;
  },
  applyPhysics(mode) {
    mode = String(mode || "").toLowerCase();
    if (mode !== "drop" && mode !== "impulse") {
      throw new Error("physics mode must be drop or impulse");
    }
    if (physics.status !== "ready") {
      throw new Error(physics.error || "Rapier WebAssembly is not ready");
    }
    const model = state.model;
    if (!model) throw new Error("no model loaded");
    resetExplodedParts(model);
    state.spin = false;
    const body = model.physicsBody || createPhysicsBody(model);
    if (mode === "drop") {
      const home = model.physicsHome;
      body.setTranslation({
        x: home.position.x,
        y: home.position.y + PHYSICS_DROP_HEIGHT,
        z: home.position.z,
      }, true);
      body.setRotation({
        x: home.rotation.x, y: home.rotation.y,
        z: home.rotation.z, w: home.rotation.w,
      }, true);
      body.setLinvel({ x: 0, y: 0, z: 0 }, true);
      body.setAngvel({ x: 0, y: 0, z: 0 }, true);
    } else {
      body.applyImpulse({ x: 0, y: PHYSICS_IMPULSE, z: 0 }, true);
    }
    physics.activeModel = model;
    physics.mode = mode;
  },
  highlightPart(name) {
    const m = state.model;
    if (!m) return;
    if (m.highlight) { const old = findNode(m.root, m.highlight); if (old) setGlow(old, false); }
    m.highlight = "";
    const node = name ? findNode(m.root, name) : null;
    if (node) { setGlow(node, true); m.highlight = name; }
  },
  setHologram(on) {
    this.setMaterialStyle(on ? "hologram" : "realistic");
  },
  setMaterialStyle(style) {
    style = String(style);
    if (!STYLES.includes(style)) throw new Error("style must be one of " + STYLES.join(", "));
    state.style = style;
    const m = state.model;
    if (!m) return;
    const keep = m.highlight;
    if (keep) this.highlightPart("");
    applyStyle(m, style);
    syncClip();
    syncLook();
    if (keep) this.highlightPart(keep);
  },
  setPartInfo(info) {
    const out = {};
    if (info && typeof info === "object" && !Array.isArray(info)) {
      Object.entries(info).slice(0, 200).forEach(([k, v]) => { out[String(k).slice(0, 60)] = String(v).slice(0, 300); });
    }
    state.partInfo = out;
    hover.pending = true;
  },
  clearModel() {
    this.removeModel();
    state.partInfo = {};
  },
  removeModel() {
    loadToken++;
    if (state.model) {
      stopModelPhysics(state.model, false);
      scene.remove(state.model.group);
      clipCapsScene.remove(state.model.clipCap);
      state.model.clipBackMaterial.dispose();
      state.model.clipFrontMaterial.dispose();
      state.model.clipCap.geometry.dispose();
      state.model.clipCapMaterial.dispose();
      disposeObject(state.model.root);
    }
    state.model = null;
    state.modelStatus = "none";
    state.modelError = "";
    syncLook();
    syncControls();
    resetCamera();
    hideTip();
    globe.visible = true;
    rings.forEach(r => { r.visible = true; });
  },
  spin(on) { state.spin = !!on && !clip.axis; if (on && !clip.axis) state.target = null; },
  setControls(active) {
    state.controlsOn = !!active;
    syncControls();
  },
  getState() {
    return {
      ready: state.ready,
      webgl: !!renderer,
      hud: {
        state: hudAnimation.state,
        color: "#" + hudAnimation.color.getHexString(),
        targetColor: "#" + hudAnimation.targetColor.getHexString(),
        ringSpeed: hudAnimation.ringSpeed,
        glow: hudAnimation.glow,
        particles: Math.round(hudAnimation.particles),
        targetParticles: Math.round(hudAnimation.targetParticles),
      },
      controls: { enabled: controls.enabled, wanted: state.controlsOn, distance: Number(camera.position.distanceTo(controls.target).toFixed(3)), azimuth: Number(controls.getAzimuthalAngle().toFixed(3)) },
      flights: state.flights ? state.flights.list.length : 0,
      clipping: {
        axis: clip.axis,
        position: clip.position,
        clipped: state.model ? state.model.meshes.filter(mesh => [].concat(mesh.material)[0].clippingPlanes).length : 0,
        caps: clip.axis && state.model && state.model.clipCap.visible ? 1 : 0,
        planes: state.model ? [{
          normal: state.model.clipWorldPlane.normal.toArray().map(value => Number(value.toFixed(3))),
          constant: Number(state.model.clipWorldPlane.constant.toFixed(3)),
        }] : [],
      },
      physics: {
        status: physics.status,
        mode: physics.mode,
        error: physics.error,
        active: !!(physics.activeModel && physics.activeModel.physicsBody),
        position: physics.activeModel && physics.activeModel.physicsBody
          ? (() => {
            const value = physics.activeModel.physicsBody.translation();
            return { x: value.x, y: value.y, z: value.z };
          })() : null,
        velocityY: physics.activeModel && physics.activeModel.physicsBody
          ? physics.activeModel.physicsBody.linvel().y : 0,
        bottom: physics.activeModel && physics.activeModel.physicsBody
          ? physics.activeModel.physicsBody.translation().y - physics.activeModel.physicsHalfExtents[1]
          : null,
      },
      look: { environment: !!scene.environment, envLoaded: !!envMap, envError: state.envError || "", shadows: keyLight.castShadow, shadowFloor: shadowFloor.visible, toneMapping: renderer ? renderer.toneMapping : 0, shadowCasters: state.model ? state.model.meshes.filter(o => o.castShadow).length : 0 },
      model: {
        status: state.modelStatus,
        name: state.model ? state.model.name : "",
        label: state.model ? modelLabel() : "",
        error: state.modelError,
        nodes: state.model ? nodeNames(state.model.root) : [],
        parts: state.model ? state.model.parts.length : 0,
        explode: state.model ? Number(state.model.explode.toFixed(3)) : 0,
        moved: state.model ? state.model.parts.map(p => Number(p.node.position.distanceTo(p.origin).toFixed(3))) : [],
        highlight: state.model ? state.model.highlight : "",
        glowing: state.model ? (() => { let n = 0; state.model.root.traverse(o => { if (o.userData.orig || o.userData.glow) n++; }); return n; })() : 0,
        hologram: state.model ? state.model.hologram : false,
        style: state.model ? state.model.style : "",
        edges: state.model ? state.model.meshes.filter(o => o.userData.edgeLines).length : 0,
        materials: state.model ? state.model.meshes.map(o => [].concat(o.material)[0].type) : [],
        meshColors: state.model ? state.model.meshes.map(o => [].concat(o.material)[0].color ? [].concat(o.material)[0].color.getHexString() : "") : [],
        partInfo: Object.keys(state.partInfo).length,
        pendingStyle: state.style,
        hover: { name: hover.name, text: hover.text, rays: hover.rays, visible: !!tip && tip.style.display === "block" },
        shaderError: state.shaderError,
      },
      spin: state.spin,
      flying: !!state.target,
      markers: state.markers.map(m => ({ lat: m.lat, lon: m.lon, label: m.label })),
    };
  },
};

resize();
state.ready = true;
const boot = document.getElementById("boot");
if (boot) {
  if (renderer) boot.remove();
  else boot.textContent = "WebGL non disponibile";
}
requestAnimationFrame(frame);
