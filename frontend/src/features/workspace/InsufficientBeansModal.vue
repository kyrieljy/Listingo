<script setup lang="ts">
import { FrownOutlined } from '@ant-design/icons-vue'

const props = defineProps<{
  open: boolean
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  'open-plans': []
  'open-packs': []
}>()

function close() {
  emit('update:open', false)
}
function openPlans() {
  emit('open-plans')
}
function openPacks() {
  emit('open-packs')
}
</script>

<template>
  <a-modal
    :open="props.open"
    title="生成额度不足"
    :footer="null"
    width="420"
    @update:open="(value: boolean) => emit('update:open', value)"
  >
    <div class="insufficient-beans-modal">
      <div class="ibm-icon"><FrownOutlined /></div>
      <p class="ibm-desc">
        你的豆子余额不足以完成本次生成。<br />
        订阅方案或购买豆子包后即可继续创作。
      </p>
      <div class="ibm-actions">
        <button type="button" class="ibm-btn ibm-btn-ghost" @click="close">稍后再说</button>
        <button type="button" class="ibm-btn ibm-btn-secondary" @click="openPacks">购买豆子包</button>
        <button type="button" class="ibm-btn ibm-btn-primary" @click="openPlans">查看订阅方案</button>
      </div>
    </div>
  </a-modal>
</template>

<style scoped>
.insufficient-beans-modal {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 8px 4px 4px;
}
.ibm-icon {
  font-size: 40px;
  color: #faad14;
  line-height: 1;
  margin-bottom: 14px;
}
.ibm-desc {
  margin: 0 0 22px;
  color: rgba(0, 0, 0, 0.65);
  font-size: 14px;
  line-height: 1.7;
}
.ibm-actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
}
.ibm-btn {
  height: 40px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
  transition: opacity 0.2s ease, background 0.2s ease;
}
.ibm-btn:hover {
  opacity: 0.88;
}
.ibm-btn-primary {
  background: #1677ff;
  color: #fff;
}
.ibm-btn-secondary {
  background: #fff;
  color: #1677ff;
  border-color: #1677ff;
}
.ibm-btn-ghost {
  background: transparent;
  color: rgba(0, 0, 0, 0.45);
  border-color: #d9d9d9;
}
</style>
