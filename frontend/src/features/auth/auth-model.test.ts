import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { userFacingApiErrorMessage } from '../../api/client'
import { fallbackPlans, hasEntitlement, maskPhone, planFromDto, resolvePasswordRole } from './auth-model'
import authModalSource from './AuthModal.vue?raw'
import authStoreSource from './auth-store.ts?raw'
import userMenuSource from './UserMenu.vue?raw'

const authCssSource = readFileSync(fileURLToPath(new URL('./auth.css', import.meta.url)), 'utf8')

describe('auth model', () => {
  it('masks bound phone numbers for account surfaces', () => {
    expect(maskPhone('13800138000')).toBe('138****8000')
    expect(maskPhone('+86 13800138000')).toBe('138****8000')
    expect(maskPhone('+852 6123 4567')).toBe('+852 61****4567')
  })

  it('keeps the commercial V1 plan catalog and bean entitlements', () => {
    expect(fallbackPlans.map((plan) => plan.key)).toEqual([
      'free',
      'monthly_basic',
      'monthly_standard',
      'monthly_pro',
      'yearly_basic',
      'yearly_standard',
      'yearly_flagship',
      'enterprise_custom',
    ])
    expect(fallbackPlans.find((plan) => plan.key === 'monthly_standard')?.beans).toBe(1560)
    expect(hasEntitlement(fallbackPlans.find((plan) => plan.key === 'monthly_standard'), 'batch_generation')).toBe(true)
    expect(hasEntitlement(fallbackPlans.find((plan) => plan.key === 'monthly_basic'), 'batch_generation')).toBe(false)

    const internal = planFromDto({
      id: 'internal-id',
      code: 'internal',
      name: 'Internal',
      description: '',
      badge: '',
      cta: '',
      enabled: true,
      visible: false,
      is_internal: true,
      is_enterprise: false,
      billing_cycle: 'internal',
      beans: null,
      recommended: false,
      contact_sales: false,
      features: [],
      entitlements: { image_generation: true },
      contact_text: '',
      contact_phone: '',
      prices: [],
      quota_rules: [],
      sort_order: 99,
    })
    expect(internal.adminOnly).toBe(true)
    expect(internal.beans).toBeNull()
    expect(hasEntitlement(internal, 'batch_generation')).toBe(true)
  })

  it('keeps bean summary styles readable in the account modal', () => {
    const summaryRule = authCssSource.match(/\.account-line-modal \.bean-summary-grid article\s*\{([^}]*)\}/)?.[1]?.replace(/\s+/g, '') ?? ''
    const expiryRule = authCssSource.match(/\.account-line-modal \.bean-expiry-list article\s*\{([^}]*)\}/)?.[1]?.replace(/\s+/g, '') ?? ''
    const ruleText = authCssSource.match(/\.account-line-modal \.bean-rule-line p\s*\{([^}]*)\}/)?.[1]?.replace(/\s+/g, '') ?? ''

    expect(summaryRule).toContain('min-height:96px')
    expect(expiryRule).toContain('grid-template-columns:minmax(0,1fr)autoauto')
    expect(ruleText).toContain('font-size:12px')
  })

  it('matches backend watermark-free plan codes', () => {
    expect(authStoreSource).toContain('canExportWithoutWatermark')
    expect(authStoreSource).toContain('paidExportPlans.has(user.value.plan)')
    expect(authStoreSource).not.toContain("user.value.plan !== 'free'")
  })

  it('marks admin password identities for the two-step login flow', () => {
    expect(resolvePasswordRole('admin@listingo.local')).toBe('admin')
    expect(resolvePasswordRole('operator')).toBe('user')
  })

  it('closes the avatar dropdown from outside pointer interactions', () => {
    expect(userMenuSource).toContain('const menuRoot = ref<HTMLElement | null>(null)')
    expect(userMenuSource).toContain("document.addEventListener('pointerdown', handleDocumentPointerDown, true)")
    expect(userMenuSource).toContain("document.removeEventListener('pointerdown', handleDocumentPointerDown, true)")
    expect(userMenuSource).toContain('if (!menuRoot.value?.contains(target)) closeMenu()')
    expect(userMenuSource).toContain('ref="menuRoot"')
    expect(userMenuSource).toContain('@click="toggleMenu"')
  })

  it('keeps auth phone inputs country-selectable and visually stable', () => {
    expect(authModalSource).toContain('const phoneCountryOptions')
    expect(authModalSource).toContain('+852 香港')
    expect(authModalSource).toContain('buildPhoneNumber')
    expect(authModalSource).toContain('phoneCountryPrefix')
    expect(authModalSource).toContain('auth-country-menu')
    expect(authModalSource).toContain('/auth/water-ripple-landscape-subjects.png')
    expect(authCssSource).toContain('height: min(680px, calc(100vh - 48px))')
    expect(authCssSource).toContain('max-width: 460px')
    expect(authCssSource).toContain('padding: 5px')
    expect(authCssSource).toContain('overflow: visible')
    expect(authCssSource).toContain('.auth-country-trigger')
    expect(authCssSource).toContain('input:-webkit-autofill')
  })

  it('uses one SMS login flow for existing and first-time phones', () => {
    expect(authModalSource).toContain('短信登录 / 注册')
    expect(authModalSource).toContain("const purpose = kind === 'admin' ? 'admin' : 'login'")
    expect(authModalSource).toContain('await authStore.loginWithSms({ phone: buildPhoneNumber(smsCountryCode.value, smsPhone.value), code: smsCode.value })')
    expect(authModalSource).not.toContain('type AuthMode')
    expect(authModalSource).not.toContain('initialMode')
    expect(authModalSource).not.toContain('switchMode')
    expect(authModalSource).not.toContain('registerWithPassword')
    expect(authModalSource).not.toContain("purpose === 'register'")
    expect(authStoreSource).toContain('async function loginWithSms(payload: { phone: string; code: string })')
    expect(authStoreSource).not.toContain('payload.mode === \'register\'')
  })

  it('turns API failures into user-facing Chinese copy', () => {
    expect(userFacingApiErrorMessage({
      config: { url: '/auth/password/login' },
      response: { status: 401, data: { detail: '账号或密码不正确' } },
    })).toBe('账号或密码不正确')
    expect(userFacingApiErrorMessage({
      config: { url: '/auth/password/login' },
      response: { status: 401, data: {} },
    })).toBe('账号或密码不正确')
    expect(userFacingApiErrorMessage({
      response: { status: 422, data: { detail: [{ msg: '请输入有效的手机号' }] } },
    })).toBe('请输入有效的手机号')
    expect(userFacingApiErrorMessage({ code: 'ECONNABORTED' })).toBe('请求超时，请稍后重试')
    expect(userFacingApiErrorMessage({ isAxiosError: true, message: 'Network Error' })).toBe('网络连接异常，请检查网络后重试')
    expect(userFacingApiErrorMessage(new Error('Request failed with status code 500'))).toBe('操作失败，请稍后重试')
  })
})
