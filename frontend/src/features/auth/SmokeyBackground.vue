<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = withDefaults(defineProps<{
  color?: string
  blur?: 'none' | 'sm' | 'md' | 'lg' | 'xl'
}>(), {
  color: '#6c5ce7',
  blur: 'sm',
})

const vertexSource = `
  attribute vec4 a_position;
  void main() {
    gl_Position = a_position;
  }
`

const fragmentSource = `
precision mediump float;

uniform vec2 iResolution;
uniform float iTime;
uniform vec2 iMouse;
uniform vec3 u_color;

void mainImage(out vec4 fragColor, in vec2 fragCoord){
  vec2 centeredUV = (2.0 * fragCoord - iResolution.xy) / min(iResolution.x, iResolution.y);
  float time = iTime * 0.5;
  vec2 mouse = iMouse / iResolution;
  vec2 rippleCenter = 2.0 * mouse - 1.0;
  vec2 distortion = centeredUV;

  for (float i = 1.0; i < 8.0; i++) {
    distortion.x += 0.5 / i * cos(i * 2.0 * distortion.y + time + rippleCenter.x * 3.1415);
    distortion.y += 0.5 / i * cos(i * 2.0 * distortion.x + time + rippleCenter.y * 3.1415);
  }

  float wave = abs(sin(distortion.x + distortion.y + time));
  float glow = smoothstep(0.9, 0.2, wave);
  fragColor = vec4(u_color * glow, glow * 0.72);
}

void main() {
  mainImage(gl_FragColor, gl_FragCoord.xy);
}
`

const canvasRef = ref<HTMLCanvasElement | null>(null)
const pointer = { x: 0, y: 0, hovering: false }
let animationId = 0
let cleanup: (() => void) | null = null

function hexToRgb(hex: string): [number, number, number] {
  const normalized = hex.replace('#', '')
  const r = parseInt(normalized.slice(0, 2), 16) / 255
  const g = parseInt(normalized.slice(2, 4), 16) / 255
  const b = parseInt(normalized.slice(4, 6), 16) / 255
  return [r, g, b]
}

function compileShader(gl: WebGLRenderingContext, type: number, source: string): WebGLShader | null {
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

onMounted(() => {
  const canvas = canvasRef.value
  const gl = canvas?.getContext('webgl', { alpha: true, premultipliedAlpha: false })
  if (!canvas || !gl) return

  const vertexShader = compileShader(gl, gl.VERTEX_SHADER, vertexSource)
  const fragmentShader = compileShader(gl, gl.FRAGMENT_SHADER, fragmentSource)
  if (!vertexShader || !fragmentShader) return

  const program = gl.createProgram()
  if (!program) return
  gl.attachShader(program, vertexShader)
  gl.attachShader(program, fragmentShader)
  gl.linkProgram(program)
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return

  gl.useProgram(program)
  const positionBuffer = gl.createBuffer()
  gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer)
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW)

  const positionLocation = gl.getAttribLocation(program, 'a_position')
  gl.enableVertexAttribArray(positionLocation)
  gl.vertexAttribPointer(positionLocation, 2, gl.FLOAT, false, 0, 0)

  const resolutionLocation = gl.getUniformLocation(program, 'iResolution')
  const timeLocation = gl.getUniformLocation(program, 'iTime')
  const mouseLocation = gl.getUniformLocation(program, 'iMouse')
  const colorLocation = gl.getUniformLocation(program, 'u_color')
  const [r, g, b] = hexToRgb(props.color)
  gl.uniform3f(colorLocation, r, g, b)
  gl.clearColor(0, 0, 0, 0)

  const startedAt = Date.now()
  const render = () => {
    const width = Math.max(1, canvas.clientWidth)
    const height = Math.max(1, canvas.clientHeight)
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width
      canvas.height = height
      gl.viewport(0, 0, width, height)
    }
    gl.clear(gl.COLOR_BUFFER_BIT)
    gl.uniform2f(resolutionLocation, width, height)
    gl.uniform1f(timeLocation, (Date.now() - startedAt) / 1000)
    gl.uniform2f(mouseLocation, pointer.hovering ? pointer.x : width / 2, pointer.hovering ? height - pointer.y : height / 2)
    gl.drawArrays(gl.TRIANGLES, 0, 6)
    animationId = window.requestAnimationFrame(render)
  }

  const handleMove = (event: MouseEvent) => {
    const rect = canvas.getBoundingClientRect()
    pointer.x = event.clientX - rect.left
    pointer.y = event.clientY - rect.top
  }
  const handleEnter = () => {
    pointer.hovering = true
  }
  const handleLeave = () => {
    pointer.hovering = false
  }

  canvas.addEventListener('mousemove', handleMove)
  canvas.addEventListener('mouseenter', handleEnter)
  canvas.addEventListener('mouseleave', handleLeave)
  render()

  cleanup = () => {
    window.cancelAnimationFrame(animationId)
    canvas.removeEventListener('mousemove', handleMove)
    canvas.removeEventListener('mouseenter', handleEnter)
    canvas.removeEventListener('mouseleave', handleLeave)
    gl.deleteProgram(program)
    gl.deleteShader(vertexShader)
    gl.deleteShader(fragmentShader)
  }
})

onBeforeUnmount(() => {
  cleanup?.()
})
</script>

<template>
  <div class="auth-smokey" :class="`auth-smokey-${blur}`">
    <canvas ref="canvasRef" />
  </div>
</template>
