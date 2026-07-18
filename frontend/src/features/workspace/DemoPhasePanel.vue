<script setup lang="ts">
import { computed, ref } from 'vue'
import { CheckCircleFilled, PlayCircleOutlined } from '@ant-design/icons-vue'
import type { PhaseKey } from './workspace-model'

const props = defineProps<{ phase: Exclude<PhaseKey, 'suite'> }>()
const progress = ref(0)
const running = ref(false)
const completed = ref(false)
const titles = { aplus: 'A+ 详情页生成', video: '视频与爆款复刻', agent: 'Agent 与画布编辑' }
const steps = computed(() => props.phase === 'aplus'
  ? ['解析商品信息', '规划 A+ 模块', '生成长图详情', '模块化编辑']
  : props.phase === 'video'
    ? ['解析参考视频', '提取爆款结构', '生成分镜与口播', '合成预览视频']
    : ['理解运营目标', '规划素材节点', '生成并连接画布', '局部指令修改'])

function runDemo() {
  running.value = true; completed.value = false; progress.value = 0
  const timer = window.setInterval(() => {
    progress.value += 20
    if (progress.value >= 100) { window.clearInterval(timer); running.value = false; completed.value = true }
  }, 320)
}
</script>

<template>
  <section class="demo-phase">
    <div class="demo-hero">
      <span class="demo-tag">功能演示</span>
      <h2>{{ titles[phase] }}</h2>
      <p>本期入口已完成产品形态与交互演示，不会触发任何外部模型调用。</p>
      <button class="primary-action" :disabled="running" @click="runDemo"><PlayCircleOutlined /> {{ running ? '模拟执行中' : '运行演示任务' }}</button>
    </div>
    <div class="demo-workflow">
      <div v-for="(step, index) in steps" :key="step" class="demo-step" :class="{ active: progress >= index * 25, done: progress >= (index + 1) * 25 }">
        <span><CheckCircleFilled v-if="progress >= (index + 1) * 25" />{{ index + 1 }}</span>
        <div><strong>{{ step }}</strong><small>{{ progress >= (index + 1) * 25 ? '已完成' : progress >= index * 25 ? '处理中' : '等待中' }}</small></div>
      </div>
    </div>
    <div v-if="completed" class="demo-result">
      <img :src="phase === 'aplus' ? '/demo/tumbler-lifestyle.png' : phase === 'video' ? '/demo/tumbler-commute.png' : '/demo/tumbler-feature.png'" alt="演示结果" />
      <div><span class="demo-tag">演示结果</span><h3>{{ phase === 'aplus' ? '品牌故事 + 核心卖点长图' : phase === 'video' ? '15 秒竖版通勤短视频分镜' : '可编辑商品视觉画布' }}</h3><p>所有节点、弹窗、状态与编辑入口均为本地交互模拟。</p><button class="secondary-action">进入编辑器</button></div>
    </div>
  </section>
</template>

