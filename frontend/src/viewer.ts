/**
 * The scene. One object, lit like a product photograph, on paper.
 */

import {
  ACESFilmicToneMapping,
  BufferAttribute,
  AmbientLight,
  Box3,
  BufferGeometry,
  Color,
  DirectionalLight,
  Group,
  Mesh,
  MeshPhysicalMaterial,
  PCFSoftShadowMap,
  PerspectiveCamera,
  PlaneGeometry,
  PMREMGenerator,
  Scene,
  ShadowMaterial,
  Sphere,
  Vector3,
  WebGLRenderer,
} from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";

export interface Finish {
  mode: string;
  colour_a: string;
  colour_b: string;
  facet_scale: number;
}

const AUTO_ROTATE_SPEED = 0.55;
const REFRAME_TOLERANCE = 0.08;
const PANEL_WIDTH = 348;
const FRAME_MARGIN = 1.2;

export class Viewer {
  private renderer: WebGLRenderer;
  private scene = new Scene();
  private camera: PerspectiveCamera;
  private controls: OrbitControls;
  private holder = new Group();
  private loader = new GLTFLoader();
  private material: MeshPhysicalMaterial;
  private current: Mesh | null = null;
  private source: BufferGeometry | null = null;
  private finish: Finish = { mode: "flat", colour_a: "#17514c", colour_b: "#e3ddd0", facet_scale: 22 };
  private framedRadius = 0;
  private key: DirectionalLight;

  constructor(canvas: HTMLCanvasElement, accent: string) {
    this.renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    this.renderer.toneMapping = ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = PCFSoftShadowMap;

    const pmrem = new PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

    this.camera = new PerspectiveCamera(30, 1, 1, 5000);
    this.camera.position.set(430, 260, 620);

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.06;
    this.controls.enablePan = false;
    this.controls.minDistance = 180;
    this.controls.maxDistance = 1600;
    this.controls.autoRotateSpeed = AUTO_ROTATE_SPEED;
    this.controls.autoRotate = !matchMedia("(prefers-reduced-motion: reduce)").matches;
    // Touching the model is a request to steer it, so the drift stops for good.
    this.controls.addEventListener("start", () => {
      this.controls.autoRotate = false;
    });

    this.material = new MeshPhysicalMaterial({
      color: new Color(accent),
      roughness: 0.44,
      metalness: 0.0,
      clearcoat: 0.18,
      clearcoatRoughness: 0.42,
      envMapIntensity: 0.75,
      flatShading: false,
    });

    this.key = new DirectionalLight(0xfffaf2, 1.7);
    this.key.position.set(210, 980, 330);
    this.key.castShadow = true;
    this.key.shadow.mapSize.set(2048, 2048);
    this.key.shadow.bias = -0.0012;
    this.scene.add(this.key);

    const fill = new DirectionalLight(0xe8ecf2, 0.42);
    fill.position.set(-520, 260, -220);
    this.scene.add(fill);
    const rim = new DirectionalLight(0xffffff, 0.38);
    rim.position.set(-240, 360, 620);
    this.scene.add(rim);
    this.scene.add(new AmbientLight(0xffffff, 0.14));

    const ground = new Mesh(
      new PlaneGeometry(4000, 4000),
      new ShadowMaterial({ opacity: 0.13, color: 0x1a1c1b }),
    );
    ground.rotation.x = -Math.PI / 2;
    ground.receiveShadow = true;
    this.scene.add(ground);
    this.scene.add(this.holder);

    addEventListener("resize", () => this.resize());
    this.resize();
    this.renderer.setAnimationLoop(() => {
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
    });
  }

  setAccent(hex: string): void {
    this.material.color.set(hex);
  }

  /** Shading only. The mesh is never touched, so weight and file never move. */
  setFinish(finish: Finish): void {
    this.finish = finish;
    this.material.vertexColors = finish.mode === "gradient";
    this.material.color.set(finish.mode === "gradient" ? "#ffffff" : finish.colour_a);
    this.material.needsUpdate = true;
    this.dress();
  }

  private dress(): void {
    if (!this.source || !this.current) return;
    const geometry =
      this.finish.mode === "faceted"
        ? facet(this.source, this.finish.facet_scale)
        : this.source.clone();
    if (this.finish.mode === "gradient") {
      paint(geometry, new Color(this.finish.colour_a), new Color(this.finish.colour_b));
    }
    const old = this.current.geometry;
    this.current.geometry = geometry;
    if (old !== this.source) old.dispose();
  }

  async setModel(glb: ArrayBuffer): Promise<void> {
    const gltf = await this.loader.parseAsync(glb, "");
    let geometry: BufferGeometry | null = null;
    gltf.scene.traverse((node) => {
      if (!geometry && (node as Mesh).isMesh) geometry = (node as Mesh).geometry;
    });
    if (!geometry) return;
    // The transport mesh carries positions only. Vertices are already split
    // along the creases, so averaging here smooths the shell without rounding
    // off the edges of the holes.
    (geometry as BufferGeometry).computeVertexNormals();

    const mesh = new Mesh(geometry, this.material);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    // The generator works z-up in millimetres; the scene is y-up.
    mesh.rotation.x = -Math.PI / 2;

    const box = new Box3().setFromObject(mesh);
    const centre = box.getCenter(new Vector3());
    mesh.position.set(-centre.x, -box.min.y, -centre.z);

    if (this.current) {
      this.holder.remove(this.current);
      if (this.current.geometry !== this.source) this.current.geometry.dispose();
    }
    this.source?.dispose();
    this.source = geometry;
    this.current = mesh;
    this.holder.add(mesh);
    this.dress();
    this.frame(new Box3().setFromObject(mesh));
  }

  /** Re-aim only when the object has actually changed size. */
  private frame(box: Box3): void {
    const sphere = box.getBoundingSphere(new Sphere());
    const changed =
      Math.abs(sphere.radius - this.framedRadius) > this.framedRadius * REFRAME_TOLERANCE;
    if (!changed && this.framedRadius > 0) return;
    this.framedRadius = sphere.radius;

    const target = sphere.center.clone();
    this.controls.target.copy(target);
    const distance =
      (sphere.radius / Math.sin((this.camera.fov * Math.PI) / 360)) * FRAME_MARGIN;
    const direction = new Vector3(0.42, 0.16, 1).normalize();
    this.camera.position.copy(target).addScaledVector(direction, distance);
    this.camera.near = distance / 60;
    this.camera.far = distance * 12;
    this.camera.updateProjectionMatrix();

    const shadow = this.key.shadow.camera;
    const extent = sphere.radius * 1.5;
    shadow.left = -extent;
    shadow.right = extent;
    shadow.top = extent;
    shadow.bottom = -extent;
    shadow.near = 1;
    shadow.far = extent * 10;
    shadow.updateProjectionMatrix();
    this.resize();
    this.controls.update();
  }

  private resize(): void {
    const canvas = this.renderer.domElement;
    const width = canvas.clientWidth || innerWidth;
    const height = canvas.clientHeight || innerHeight;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    // Nudge the frustum so the cover sits in the open half of the page rather
    // than behind the panel.
    if (width > 900) {
      this.camera.setViewOffset(width, height, PANEL_WIDTH / 2, 0, width, height);
    } else {
      this.camera.clearViewOffset();
    }
    this.camera.updateProjectionMatrix();
  }
}


/** Colour every vertex by how high up the cover it sits. */
function paint(geometry: BufferGeometry, a: Color, b: Color): void {
  const position = geometry.getAttribute("position");
  const colours = new Float32Array(position.count * 3);
  let lo = Infinity;
  let hi = -Infinity;
  for (let i = 0; i < position.count; i++) {
    const z = position.getZ(i);
    if (z < lo) lo = z;
    if (z > hi) hi = z;
  }
  const span = Math.max(hi - lo, 1e-6);
  const mix = new Color();
  for (let i = 0; i < position.count; i++) {
    mix.copy(a).lerp(b, (position.getZ(i) - lo) / span);
    colours[i * 3] = mix.r;
    colours[i * 3 + 1] = mix.g;
    colours[i * 3 + 2] = mix.b;
  }
  geometry.setAttribute("color", new BufferAttribute(colours, 3));
}

/**
 * Give every triangle in the same patch of space one shared normal.
 *
 * The mesh keeps all of its triangles; only the shading is coarsened, so a
 * low-poly look costs nothing in weight or in the print file.
 */
function facet(source: BufferGeometry, scale: number): BufferGeometry {
  const geometry = source.toNonIndexed();
  const position = geometry.getAttribute("position");
  const count = position.count / 3;
  const size = Math.max(scale, 2);

  const sums = new Map<number, [number, number, number]>();
  const keys = new Int32Array(count);
  const ax = new Vector3();
  const bx = new Vector3();
  const cx = new Vector3();
  const normal = new Vector3();

  // Bin in the cover's own surface coordinates rather than in world space:
  // arc length around the section, and height up it. Boxes cut in x, y and z
  // read as a chequerboard laid over the shape; this follows the shape.
  let radius = 0;
  for (let i = 0; i < position.count; i += 97) {
    radius = Math.max(radius, Math.hypot(position.getX(i), position.getY(i)));
  }
  radius = Math.max(radius, 1);

  for (let t = 0; t < count; t++) {
    ax.fromBufferAttribute(position, t * 3);
    bx.fromBufferAttribute(position, t * 3 + 1);
    cx.fromBufferAttribute(position, t * 3 + 2);
    normal.copy(bx).sub(ax).cross(cx.sub(ax));
    const mx = (ax.x + bx.x + cx.x) / 3;
    const my = (ax.y + bx.y + cx.y) / 3;
    const arc = Math.atan2(my, mx) * radius;
    const up = (ax.z + bx.z + cx.z) / 3;
    keys[t] = hexKey(arc, up, size);
    const sum = sums.get(keys[t]);
    if (sum) {
      sum[0] += normal.x;
      sum[1] += normal.y;
      sum[2] += normal.z;
    } else {
      sums.set(keys[t], [normal.x, normal.y, normal.z]);
    }
  }

  const normals = new Float32Array(position.count * 3);
  for (let t = 0; t < count; t++) {
    const sum = sums.get(keys[t])!;
    normal.set(sum[0], sum[1], sum[2]).normalize();
    for (let k = 0; k < 3; k++) {
      normals[(t * 3 + k) * 3] = normal.x;
      normals[(t * 3 + k) * 3 + 1] = normal.y;
      normals[(t * 3 + k) * 3 + 2] = normal.z;
    }
  }
  geometry.setAttribute("normal", new BufferAttribute(normals, 3));
  return geometry;
}

/** Index of the hexagon a point falls in, packed into one integer. */
function hexKey(x: number, y: number, size: number): number {
  const q = ((Math.sqrt(3) / 3) * x - y / 3) / size;
  const r = ((2 / 3) * y) / size;
  const s = -q - r;
  let rq = Math.round(q);
  let rr = Math.round(r);
  const rs = Math.round(s);
  const dq = Math.abs(rq - q);
  const dr = Math.abs(rr - r);
  const ds = Math.abs(rs - s);
  if (dq > dr && dq > ds) rq = -rr - rs;
  else if (dr > ds) rr = -rq - rs;
  return ((rq + 512) << 12) | (rr + 512);
}