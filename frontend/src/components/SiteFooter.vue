<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api/client'
const info = ref({ icp_number: '', support_contact: '' })
const document = ref('')
onMounted(async () => { try { info.value = (await api.get('/site-info')).data } catch { /* Do not block workspace. */ } })
</script>

<template>
  <footer class="site-footer">
    <a v-if="info.icp_number" href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">{{ info.icp_number }}</a>
    <button @click="document = '服务协议'">服务协议</button>
    <button @click="document = '隐私政策'">隐私政策</button>
    <button @click="document = '退款说明'">退款说明</button>
    <span v-if="info.support_contact">客服：{{ info.support_contact }}</span>
  </footer>
  <a-modal :open="!!document" :title="document" :footer="null" @cancel="document = ''">
    <template v-if="document === '服务协议'">
      <p>Listingo 提供商品图片、详情页与视频生成服务。请仅上传您有权使用的素材，并在发布前核对生成内容。</p>
      <p>购买前请核对商品价格、豆子数量与有效期。套餐采用一次支付，不自动续费；有效套餐到期后可重新购买。补豆包补充额度，不解锁会员功能。</p>
      <p>生成任务按页面所示规则使用豆子。系统生成失败时释放预留额度；具体扣费以账户记录为准。</p>
    </template>
    <template v-else-if="document === '隐私政策'">
      <p>我们处理您提交的手机号、账户资料、商品素材、生成要求和订单信息，用于登录验证、内容生成、收款及服务支持。</p>
      <p>使用实际生成服务时，必要的素材与提示词会发送至配置的模型服务商；短信与支付分别由短信服务商和微信支付处理。请勿上传与任务无关的个人敏感信息。</p>
      <p>需要查询、更正或删除账户数据时，请通过页面客服渠道联系我们。支付交易记录和服务记录的具体处理方式由客服核实反馈。</p>
    </template>
    <template v-else>
      <p>如遇重复付款、付款未到账或需要退款，请联系客服，提供订单号及问题说明，请勿提供支付密码。</p>
      <p>退款由客服核对订单、已使用及剩余权益后人工处理。以商户平台实际退款结果为准，登记退款时将撤销相应剩余权益。</p>
    </template>
    <p v-if="info.support_contact">客服：{{ info.support_contact }}</p>
  </a-modal>
</template>

<style scoped>
.site-footer { display: flex; justify-content: center; align-items: center; flex-wrap: wrap; gap: 16px; padding: 10px 16px; font-size: 12px; color: #687384; background: #f7f8fa; }
.site-footer button { border: 0; padding: 0; background: transparent; color: inherit; cursor: pointer; }
.site-footer a { color: inherit; }
</style>
