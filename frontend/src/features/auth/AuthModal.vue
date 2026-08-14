<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import {
  AlipayCircleOutlined,
  CheckOutlined,
  CloseOutlined,
  GoogleOutlined,
  LockOutlined,
  MobileOutlined,
  QqOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
  WechatOutlined,
} from '@ant-design/icons-vue'
import logoUrl from '../../assets/listingo-logo.png'
import WaterRippleImage from './WaterRippleImage.vue'
import { useAuthStore } from './auth-store'

type AuthMode = 'login' | 'register'
type LoginMethod = 'sms' | 'password'
type PhoneCountryOption = {
  code: string
  label: string
}

const phoneCountryOptions: PhoneCountryOption[] = [
  { code: '86', label: '+86 中国大陆' },
  { code: '852', label: '+852 香港' },
  { code: '853', label: '+853 澳门' },
  { code: '886', label: '+886 台湾' },
  { code: '65', label: '+65 新加坡' },
  { code: '60', label: '+60 马来西亚' },
  { code: '81', label: '+81 日本' },
  { code: '82', label: '+82 韩国' },
  { code: '1', label: '+1 美国/加拿大' },
  { code: '44', label: '+44 英国' },
  { code: '61', label: '+61 澳大利亚' },
]

const props = withDefaults(defineProps<{
  open: boolean
  initialMode?: AuthMode
}>(), {
  initialMode: 'login',
})

const emit = defineEmits<{
  'update:open': [value: boolean]
  authenticated: []
}>()

const authStore = useAuthStore()
const visible = computed({
  get: () => props.open,
  set: (value: boolean) => emit('update:open', value),
})
const mode = ref<AuthMode>(props.initialMode)
const method = ref<LoginMethod>('sms')
const agreed = ref(false)
const submitting = ref(false)
const smsCountryCode = ref('86')
const smsPhone = ref('')
const smsCode = ref('')
const passwordIdentifier = ref('')
const password = ref('')
const adminCode = ref('')
const registerCountryCode = ref('86')
const registerPhone = ref('')
const registerCode = ref('')
const firstPassword = ref('')
const passwordRegisterStep = ref<'credentials' | 'phone'>('credentials')
const errorText = ref('')
const smsCountdown = ref(0)
const adminCountdown = ref(0)
const registerCountdown = ref(0)
const sendingCode = ref<'sms' | 'admin' | 'register' | ''>('')
const countryDropdownOpen = ref<'sms' | 'register' | ''>('')
let smsTimer: ReturnType<typeof window.setInterval> | null = null
let adminTimer: ReturnType<typeof window.setInterval> | null = null
let registerTimer: ReturnType<typeof window.setInterval> | null = null

const modalTitle = computed(() => mode.value === 'register' ? '创建 Listingo 账号' : '欢迎登录 Listingo')
const passwordRegisterCredentialStep = computed(() => mode.value === 'register' && method.value === 'password' && passwordRegisterStep.value === 'credentials')
const submitLabel = computed(() => {
  if (passwordRegisterCredentialStep.value) return '注册'
  if (mode.value === 'register') return method.value === 'password' ? '完成注册' : '创建并登录'
  return '登录'
})
const passwordIsAdmin = computed(() => passwordIdentifier.value.trim().toLowerCase().includes('admin'))
const firstPasswordMode = computed(() => Boolean(authStore.user?.firstPasswordPending))
const smsValid = computed(() => Boolean(smsPhone.value.trim() && smsCode.value.trim()))
const passwordValid = computed(() => {
  const credentialsValid = Boolean(passwordIdentifier.value.trim() && password.value.trim())
  if (mode.value === 'register') {
    return passwordRegisterStep.value === 'credentials'
      ? credentialsValid
      : credentialsValid && Boolean(registerPhone.value.trim() && registerCode.value.trim())
  }
  return passwordIsAdmin.value ? credentialsValid && Boolean(adminCode.value.trim()) : credentialsValid
})
const canSubmit = computed(() => {
  if (firstPasswordMode.value) return firstPassword.value.trim().length >= 6
  if (passwordRegisterCredentialStep.value) return passwordValid.value
  return agreed.value && (method.value === 'sms' ? smsValid.value : passwordValid.value)
})

watch(() => props.initialMode, (nextMode) => {
  if (props.open) mode.value = nextMode
})

watch(() => props.open, (open) => {
  if (!open) return
  mode.value = props.initialMode
  method.value = 'sms'
  smsCountryCode.value = '86'
  registerCountryCode.value = '86'
  countryDropdownOpen.value = ''
  passwordRegisterStep.value = 'credentials'
  errorText.value = ''
})

function phoneDigits(value: string): string {
  return value.replace(/\D/g, '')
}

function buildPhoneNumber(countryCode: string, phone: string): string {
  const digits = phoneDigits(phone)
  if (!digits) return ''
  if (digits.startsWith(countryCode) && digits.length > countryCode.length + 4) return `+${digits}`
  return `+${countryCode} ${digits}`
}

function phoneCountryPrefix(countryCode: string): string {
  return `+${countryCode}`
}

function toggleCountryDropdown(kind: 'sms' | 'register'): void {
  countryDropdownOpen.value = countryDropdownOpen.value === kind ? '' : kind
}

function selectPhoneCountry(kind: 'sms' | 'register', countryCode: string): void {
  if (kind === 'sms') smsCountryCode.value = countryCode
  else registerCountryCode.value = countryCode
  countryDropdownOpen.value = ''
}

function clearTimer(kind: 'sms' | 'admin' | 'register'): void {
  const timer = kind === 'sms' ? smsTimer : kind === 'admin' ? adminTimer : registerTimer
  if (timer) window.clearInterval(timer)
  if (kind === 'sms') smsTimer = null
  else if (kind === 'admin') adminTimer = null
  else registerTimer = null
}

function startCountdown(kind: 'sms' | 'admin' | 'register'): void {
  clearTimer(kind)
  const countdown = kind === 'sms' ? smsCountdown : kind === 'admin' ? adminCountdown : registerCountdown
  countdown.value = 60
  const timer = window.setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) clearTimer(kind)
  }, 1000)
  if (kind === 'sms') smsTimer = timer
  else if (kind === 'admin') adminTimer = timer
  else registerTimer = timer
}

async function requestCode(kind: 'sms' | 'admin' | 'register'): Promise<void> {
  if (sendingCode.value) return
  const phone = kind === 'sms'
    ? buildPhoneNumber(smsCountryCode.value, smsPhone.value)
    : kind === 'register'
      ? buildPhoneNumber(registerCountryCode.value, registerPhone.value)
      : '18928268686'
  if (kind !== 'admin' && !phone.trim()) {
    message.warning('请先输入手机号')
    return
  }
  const purpose = kind === 'admin' ? 'admin' : mode.value === 'register' ? 'register' : 'login'
  sendingCode.value = kind
  errorText.value = ''
  try {
    const code = await authStore.sendSmsCode(phone, purpose)
    if (code) {
      if (kind === 'sms') smsCode.value = code
      else if (kind === 'register') registerCode.value = code
      else adminCode.value = code
    }
    startCountdown(kind)
  } catch (error) {
    const text = error instanceof Error ? error.message : '验证码发送失败，请稍后再试'
    errorText.value = text
    message.error(text)
  } finally {
    sendingCode.value = ''
  }
}

function switchMode(nextMode: AuthMode): void {
  mode.value = nextMode
  method.value = 'sms'
  countryDropdownOpen.value = ''
  passwordRegisterStep.value = 'credentials'
  errorText.value = ''
}

async function submit(): Promise<void> {
  if (!canSubmit.value || submitting.value) return
  if (firstPasswordMode.value) {
    submitting.value = true
    try {
      await authStore.setFirstPassword(firstPassword.value)
      emit('authenticated')
      visible.value = false
    } catch (error) {
      errorText.value = error instanceof Error ? error.message : '密码设置失败，请稍后再试'
    } finally {
      submitting.value = false
    }
    return
  }
  if (passwordRegisterCredentialStep.value) {
    passwordRegisterStep.value = 'phone'
    errorText.value = ''
    return
  }
  errorText.value = ''
  submitting.value = true
  try {
    if (method.value === 'sms') {
      await authStore.loginWithSms({ phone: buildPhoneNumber(smsCountryCode.value, smsPhone.value), code: smsCode.value, mode: mode.value })
    } else if (mode.value === 'register') {
      await authStore.registerWithPassword({
        identifier: passwordIdentifier.value,
        password: password.value,
        phone: buildPhoneNumber(registerCountryCode.value, registerPhone.value),
        code: registerCode.value,
      })
    } else {
      await authStore.loginWithPassword({
        identifier: passwordIdentifier.value,
        password: password.value,
        adminCode: adminCode.value,
      })
    }
    if (authStore.user?.firstPasswordPending) {
      message.info('请先设置管理员登录密码')
      firstPassword.value = ''
      return
    }
    emit('authenticated')
    visible.value = false
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : '登录失败，请稍后再试'
  } finally {
    submitting.value = false
  }
}

onBeforeUnmount(() => {
  clearTimer('sms')
  clearTimer('admin')
  clearTimer('register')
})
</script>

<template>
  <a-modal
    v-model:open="visible"
    :footer="null"
    :closable="false"
    :width="1000"
    centered
    class="auth-shell-modal"
    wrap-class-name="auth-modal-wrap"
  >
    <div class="auth-modal-card">
      <section class="auth-visual-panel">
        <div class="auth-visual-materials" aria-hidden="true">
          <span class="auth-visual-silk auth-visual-silk-a" />
          <span class="auth-visual-silk auth-visual-silk-b" />
          <span class="auth-visual-current" />
        </div>
        <div class="auth-visual-content">
          <img class="auth-side-logo" :src="logoUrl" alt="Listingo" />
          <div class="auth-logo-accent" aria-hidden="true">
            <span />
            <i />
            <i />
            <b />
          </div>
          <div class="auth-visual-stage" aria-hidden="true">
            <div class="auth-visual-art">
              <WaterRippleImage
                src="/auth/water-ripple-landscape-subjects.png"
                :blueish="0.22"
                :scale="7.4"
                :illumination="0.24"
                :surface-distortion="0.026"
                :water-distortion="0.018"
              />
            </div>
          </div>
          <div class="auth-atmosphere-bar" aria-hidden="true">
            <span />
            <b>AI commerce visual studio</b>
            <i />
          </div>
        </div>
      </section>

      <section class="auth-form-panel">
        <button class="auth-close-button" type="button" aria-label="关闭登录弹窗" @click="visible = false">
          <CloseOutlined />
        </button>
        <header class="auth-form-head">
          <h2>{{ modalTitle }}</h2>
        </header>

        <div v-if="!firstPasswordMode" class="auth-method-switch" role="tablist" aria-label="登录方式">
          <button type="button" :class="{ active: method === 'sms' }" role="tab" @click="method = 'sms'; passwordRegisterStep = 'credentials'; countryDropdownOpen = ''">
            <MobileOutlined />短信登录
          </button>
          <button type="button" :class="{ active: method === 'password' }" role="tab" @click="method = 'password'; passwordRegisterStep = 'credentials'; countryDropdownOpen = ''">
            <LockOutlined />密码登录
          </button>
        </div>

        <form class="auth-form" @submit.prevent="submit">
          <template v-if="firstPasswordMode">
            <label class="auth-input-row">
              <span>设置登录密码</span>
              <div class="auth-icon-input">
                <LockOutlined />
                <input v-model="firstPassword" autocomplete="new-password" type="password" placeholder="请设置管理员登录密码" />
              </div>
            </label>
          </template>

          <template v-else-if="method === 'sms'">
            <div class="auth-input-row">
              <span>手机号</span>
              <div class="auth-phone-input">
                <div class="auth-country-picker" :class="{ open: countryDropdownOpen === 'sms' }">
                  <button
                    class="auth-country-trigger"
                    type="button"
                    aria-haspopup="listbox"
                    :aria-expanded="countryDropdownOpen === 'sms'"
                    @click="toggleCountryDropdown('sms')"
                  >
                    <span>{{ phoneCountryPrefix(smsCountryCode) }}</span>
                    <i aria-hidden="true" />
                  </button>
                  <div v-if="countryDropdownOpen === 'sms'" class="auth-country-menu" role="listbox">
                    <button
                      v-for="country in phoneCountryOptions"
                      :key="country.code"
                      type="button"
                      role="option"
                      :aria-selected="smsCountryCode === country.code"
                      :class="{ selected: smsCountryCode === country.code }"
                      @click="selectPhoneCountry('sms', country.code)"
                    >
                      {{ country.label }}
                    </button>
                  </div>
                </div>
                <input v-model="smsPhone" autocomplete="tel" inputmode="tel" placeholder="请输入手机号" />
              </div>
            </div>
            <label class="auth-input-row">
              <span>验证码</span>
              <div class="auth-code-input">
                <input v-model="smsCode" autocomplete="one-time-code" inputmode="numeric" placeholder="请输入验证码" />
                <button type="button" :disabled="smsCountdown > 0 || sendingCode === 'sms'" @click="requestCode('sms')">
                  {{ sendingCode === 'sms' ? '发送中...' : smsCountdown > 0 ? `${smsCountdown}s` : '获取验证码' }}
                </button>
              </div>
            </label>
          </template>

          <template v-else-if="mode === 'login'">
            <label class="auth-input-row">
              <span>账号</span>
              <div class="auth-icon-input">
                <UserOutlined />
                <input v-model="passwordIdentifier" autocomplete="username" placeholder="手机号 / 用户名 / 邮箱" />
              </div>
            </label>
            <label class="auth-input-row">
              <span>密码</span>
              <div class="auth-icon-input">
                <LockOutlined />
                <input v-model="password" autocomplete="current-password" type="password" placeholder="请输入密码" />
              </div>
            </label>
            <label v-if="passwordIsAdmin" class="auth-input-row">
              <span>管理员二次验证</span>
              <div class="auth-code-input">
                <input v-model="adminCode" autocomplete="one-time-code" inputmode="numeric" placeholder="请输入管理员短信验证码" />
                <button type="button" :disabled="adminCountdown > 0 || sendingCode === 'admin'" @click="requestCode('admin')">
                  {{ sendingCode === 'admin' ? '发送中...' : adminCountdown > 0 ? `${adminCountdown}s` : '发送验证码' }}
                </button>
              </div>
            </label>
          </template>

          <template v-else>
            <template v-if="passwordRegisterStep === 'credentials'">
              <label class="auth-input-row">
                <span>账号</span>
                <div class="auth-icon-input">
                  <UserOutlined />
                  <input v-model="passwordIdentifier" autocomplete="username" placeholder="设置用户名 / 邮箱" />
                </div>
              </label>
              <label class="auth-input-row">
                <span>密码</span>
                <div class="auth-icon-input">
                  <LockOutlined />
                  <input v-model="password" autocomplete="new-password" type="password" placeholder="设置登录密码" />
                </div>
              </label>
            </template>
            <template v-else>
              <div class="auth-input-row">
                <span>绑定手机号</span>
                <div class="auth-phone-input">
                  <div class="auth-country-picker" :class="{ open: countryDropdownOpen === 'register' }">
                    <button
                      class="auth-country-trigger"
                      type="button"
                      aria-haspopup="listbox"
                      :aria-expanded="countryDropdownOpen === 'register'"
                      @click="toggleCountryDropdown('register')"
                    >
                      <span>{{ phoneCountryPrefix(registerCountryCode) }}</span>
                      <i aria-hidden="true" />
                    </button>
                    <div v-if="countryDropdownOpen === 'register'" class="auth-country-menu" role="listbox">
                      <button
                        v-for="country in phoneCountryOptions"
                        :key="country.code"
                        type="button"
                        role="option"
                        :aria-selected="registerCountryCode === country.code"
                        :class="{ selected: registerCountryCode === country.code }"
                        @click="selectPhoneCountry('register', country.code)"
                      >
                        {{ country.label }}
                      </button>
                    </div>
                  </div>
                  <input v-model="registerPhone" autocomplete="tel" inputmode="tel" placeholder="请输入手机号" />
                </div>
              </div>
              <label class="auth-input-row">
                <span>验证码</span>
                <div class="auth-code-input">
                  <input v-model="registerCode" autocomplete="one-time-code" inputmode="numeric" placeholder="请输入验证码" />
                  <button type="button" :disabled="registerCountdown > 0 || sendingCode === 'register'" @click="requestCode('register')">
                    {{ sendingCode === 'register' ? '发送中...' : registerCountdown > 0 ? `${registerCountdown}s` : '获取验证码' }}
                  </button>
                </div>
              </label>
            </template>
          </template>

          <p v-if="errorText" class="auth-error">{{ errorText }}</p>

          <label v-if="!passwordRegisterCredentialStep && !firstPasswordMode" class="auth-agreement">
            <input v-model="agreed" type="checkbox" />
            <span>我已阅读并同意<a>用户协议</a>、<a>个人信息保护政策</a>和<a>账号规则</a></span>
          </label>

          <button class="auth-submit" type="submit" :disabled="!canSubmit || submitting">
            <span>{{ submitting ? '处理中...' : submitLabel }}</span>
            <CheckOutlined v-if="!submitting" />
          </button>
        </form>

        <button v-if="mode === 'login'" class="auth-secondary-link" type="button" @click="switchMode('register')">
          没有账号？立即注册
        </button>
        <button v-else class="auth-secondary-link" type="button" @click="switchMode('login')">
          已有账号？返回登录
        </button>

        <div class="auth-social-divider"><span />更多登录方式<span /></div>
        <div class="auth-social-row" aria-label="第三方登录占位">
          <button type="button" disabled title="后续接入微信登录"><WechatOutlined /></button>
          <button type="button" disabled title="后续接入支付宝登录"><AlipayCircleOutlined /></button>
          <button type="button" disabled title="后续接入 QQ 登录"><QqOutlined /></button>
          <button type="button" disabled title="后续接入 Gmail 登录"><GoogleOutlined /></button>
          <small><SafetyCertificateOutlined />手机号统一绑定</small>
        </div>
      </section>
    </div>
  </a-modal>
</template>
