<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  src: string
  blueish?: number
  scale?: number
  illumination?: number
  surfaceDistortion?: number
  waterDistortion?: number
}>(), {
  blueish: 0,
  scale: 7,
  illumination: 0.2,
  surfaceDistortion: 0.03,
  waterDistortion: 0.02,
})

const vertexSource = `
precision mediump float;
varying vec2 vUv;
attribute vec2 a_position;

void main() {
  vUv = .5 * (a_position + 1.);
  gl_Position = vec4(a_position, 0.0, 1.0);
}
`

const fragmentSource = `
precision mediump float;

varying vec2 vUv;
uniform sampler2D u_image_texture;
uniform float u_time;
uniform float u_ratio;
uniform float u_img_ratio;
uniform float u_blueish;
uniform float u_scale;
uniform float u_illumination;
uniform float u_surface_distortion;
uniform float u_water_distortion;

vec3 mod289(vec3 x) { return x - floor(x * (1. / 289.)) * 289.; }
vec2 mod289(vec2 x) { return x - floor(x * (1. / 289.)) * 289.; }
vec3 permute(vec3 x) { return mod289(((x * 34.) + 1.) * x); }

float snoise(vec2 v) {
  const vec4 C = vec4(0.211324865405187, 0.366025403784439, -0.577350269189626, 0.024390243902439);
  vec2 i = floor(v + dot(v, C.yy));
  vec2 x0 = v - i + dot(i, C.xx);
  vec2 i1 = (x0.x > x0.y) ? vec2(1., 0.) : vec2(0., 1.);
  vec4 x12 = x0.xyxy + C.xxzz;
  x12.xy -= i1;
  i = mod289(i);
  vec3 p = permute(permute(i.y + vec3(0., i1.y, 1.)) + i.x + vec3(0., i1.x, 1.));
  vec3 m = max(0.5 - vec3(dot(x0, x0), dot(x12.xy, x12.xy), dot(x12.zw, x12.zw)), 0.);
  m = m * m;
  m = m * m;
  vec3 x = 2. * fract(p * C.www) - 1.;
  vec3 h = abs(x) - 0.5;
  vec3 ox = floor(x + 0.5);
  vec3 a0 = x - ox;
  m *= 1.79284291400159 - 0.85373472095314 * (a0 * a0 + h * h);
  vec3 g;
  g.x = a0.x * x0.x + h.x * x0.y;
  g.yz = a0.yz * x12.xz + h.yz * x12.yw;
  return 130. * dot(m, g);
}

mat2 rotate2D(float r) {
  return mat2(cos(r), sin(r), -sin(r), cos(r));
}

float surface_noise(vec2 uv, float t, float scale) {
  vec2 n = vec2(.1);
  vec2 N = vec2(.1);
  mat2 m = rotate2D(.5);
  for (int j = 0; j < 10; j++) {
    uv *= m;
    n *= m;
    vec2 q = uv * scale + float(j) + n + (.5 + .5 * float(j)) * (mod(float(j), 2.) - 1.) * t;
    n += sin(q);
    N += cos(q) / scale;
    scale *= 1.2;
  }
  return (N.x + N.y + .1);
}

void main() {
  vec2 uv = vUv;
  uv.y = 1. - uv.y;
  uv.x *= u_ratio;

  float t = .002 * u_time;
  float outer_noise = snoise((.3 + .1 * sin(t)) * uv + vec2(0., .2 * t));
  vec2 surface_noise_uv = 2. * uv + (outer_noise * .2);

  float surf = surface_noise(surface_noise_uv, t, u_scale);
  surf *= pow(uv.y, .3);
  surf = pow(surf, 2.);

  vec2 img_uv = vUv;
  img_uv -= .5;
  if (u_ratio > u_img_ratio) {
    img_uv.x = img_uv.x * u_ratio / u_img_ratio;
  } else {
    img_uv.y = img_uv.y * u_img_ratio / u_ratio;
  }
  img_uv *= 1.02;
  img_uv += .5;
  img_uv.y = 1. - img_uv.y;

  img_uv += (u_water_distortion * outer_noise);
  img_uv += (u_surface_distortion * surf);

  vec4 img = texture2D(u_image_texture, img_uv);
  img.rgb *= (1. + u_illumination * surf);

  vec3 light = vec3(1.0);
  vec3 coolWhite = vec3(1.0 - (u_blueish * .12), 1.0, 1.0);
  vec3 color = img.rgb + u_illumination * mix(light, coolWhite, .18) * surf;
  float opacity = img.a;

  float edge_alpha = step(0., img_uv.x) * step(img_uv.x, 1.);
  edge_alpha *= step(0., img_uv.y) * step(img_uv.y, 1.);
  opacity *= edge_alpha;

  gl_FragColor = vec4(color, opacity);
}
`

const canvasRef = ref<HTMLCanvasElement | null>(null)
let gl: WebGLRenderingContext | null = null
let program: WebGLProgram | null = null
let texture: WebGLTexture | null = null
let animationId = 0
let imageRatio = 16 / 10
const uniforms: Record<string, WebGLUniformLocation | null> = {}

function compileShader(type: number, source: string): WebGLShader | null {
  if (!gl) return null
  const shader = gl.createShader(type)
  if (!shader) return null
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    gl.deleteShader(shader)
    return null
  }
  return shader
}

function updateParams(): void {
  if (!gl || !program) return
  gl.useProgram(program)
  gl.uniform1f(uniforms.u_blueish, props.blueish)
  gl.uniform1f(uniforms.u_scale, props.scale)
  gl.uniform1f(uniforms.u_illumination, props.illumination)
  gl.uniform1f(uniforms.u_surface_distortion, props.surfaceDistortion)
  gl.uniform1f(uniforms.u_water_distortion, props.waterDistortion)
}

function resizeCanvas(): void {
  const canvas = canvasRef.value
  if (!gl || !canvas) return
  const ratio = Math.min(window.devicePixelRatio || 1, 2)
  const width = Math.max(1, Math.floor(canvas.clientWidth * ratio))
  const height = Math.max(1, Math.floor(canvas.clientHeight * ratio))
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width
    canvas.height = height
  }
  gl.viewport(0, 0, width, height)
  gl.uniform1f(uniforms.u_ratio, width / height)
  gl.uniform1f(uniforms.u_img_ratio, imageRatio)
}

async function loadImage(src: string): Promise<void> {
  if (!gl) return
  const image = new Image()
  image.crossOrigin = 'anonymous'
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve()
    image.onerror = () => reject(new Error(`Unable to load ripple image: ${src}`))
    image.src = src
  })
  imageRatio = image.naturalWidth / image.naturalHeight
  if (texture) gl.deleteTexture(texture)
  texture = gl.createTexture()
  gl.activeTexture(gl.TEXTURE0)
  gl.bindTexture(gl.TEXTURE_2D, texture)
  gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, 0)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE)
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE)
  gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image)
  gl.uniform1i(uniforms.u_image_texture, 0)
  resizeCanvas()
}

function render(startedAt: number): void {
  if (!gl) return
  resizeCanvas()
  gl.clear(gl.COLOR_BUFFER_BIT)
  gl.uniform1f(uniforms.u_time, performance.now() - startedAt)
  gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
  animationId = window.requestAnimationFrame(() => render(startedAt))
}

onMounted(async () => {
  const canvas = canvasRef.value
  gl = canvas?.getContext('webgl', { alpha: true, antialias: true, premultipliedAlpha: false }) ?? null
  if (!canvas || !gl) return

  const vertexShader = compileShader(gl.VERTEX_SHADER, vertexSource)
  const fragmentShader = compileShader(gl.FRAGMENT_SHADER, fragmentSource)
  if (!vertexShader || !fragmentShader) return

  program = gl.createProgram()
  if (!program) return
  gl.attachShader(program, vertexShader)
  gl.attachShader(program, fragmentShader)
  gl.linkProgram(program)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return
  gl.useProgram(program)

  const uniformCount = gl.getProgramParameter(program, gl.ACTIVE_UNIFORMS)
  for (let index = 0; index < uniformCount; index += 1) {
    const info = gl.getActiveUniform(program, index)
    if (info) uniforms[info.name] = gl.getUniformLocation(program, info.name)
  }

  const buffer = gl.createBuffer()
  gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW)
  const positionLocation = gl.getAttribLocation(program, 'a_position')
  gl.enableVertexAttribArray(positionLocation)
  gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0)
  gl.clearColor(0, 0, 0, 0)
  updateParams()
  await loadImage(props.src)
  render(performance.now())
})

watch(() => [props.blueish, props.scale, props.illumination, props.surfaceDistortion, props.waterDistortion], updateParams)
watch(() => props.src, (nextSrc) => {
  void loadImage(nextSrc)
})

onBeforeUnmount(() => {
  window.cancelAnimationFrame(animationId)
  if (gl && texture) gl.deleteTexture(texture)
  if (gl && program) gl.deleteProgram(program)
})
</script>

<template>
  <canvas ref="canvasRef" class="water-ripple-image" />
</template>
