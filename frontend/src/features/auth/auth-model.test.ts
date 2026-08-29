import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { userFacingApiErrorMessage } from '../../api/client'
import { fallbackPlans, maskPhone, planFromDto, quotaFromDto, resolvePasswordRole } from './auth-model'
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

  it('keeps the requested plan catalog and quota buckets', () => {
    expect(fallbackPlans.map((plan) => plan.key)).toEqual(['free', 'standard', 'advanced', 'enterprise'])
    const rows = [
      quotaFromDto({ id: '1', action_key: 'image_generation', action_label: '商品套图', unit: '张', monthly_limit: 330, used: 0, remaining: 330, period: '2026-08', cost_multiplier: 1, warning_threshold: 80, enabled: true }),
      quotaFromDto({ id: '2', action_key: 'aplus_generation', action_label: 'A+', unit: '张', monthly_limit: 60, used: 0, remaining: 60, period: '2026-08', cost_multiplier: 1, warning_threshold: 80, enabled: true }),
      quotaFromDto({ id: '3', action_key: 'video_generation', action_label: '视频', unit: '条', monthly_limit: 12, used: 0, remaining: 12, period: '2026-08', cost_multiplier: 1, warning_threshold: 80, enabled: true }),
      quotaFromDto({ id: '4', action_key: 'edit_generation', action_label: '二次编辑', unit: '次', monthly_limit: 160, used: 0, remaining: 160, period: '2026-08', cost_multiplier: 1, warning_threshold: 80, enabled: true }),
    ]
    expect(rows.map((row) => row.key)).toEqual([
      'image_generation',
      'aplus_generation',
      'video_generation',
      'edit_generation',
    ])
    expect(planFromDto({ id: 'internal', code: 'internal', name: 'Internal', description: '', badge: '', cta: '', enabled: true, visible: false, is_internal: true, is_enterprise: false, features: [], contact_text: '', contact_phone: '', prices: [], quota_rules: [{ id: 'q', action_key: 'image_generation', action_label: '商品套图', unit: '张', monthly_limit: null, cost_multiplier: 1, warning_threshold: 80, enabled: true }], sort_order: 99 }).quota.image_generation).toBe('unlimited')
  })

  it('keeps quota summary text aligned with account body copy size', () => {
    const planTitleRule = [...authCssSource.matchAll(/\.account-line-modal \.quota-plan-line div b\s*\{([^}]*)\}/g)].at(-1)?.[1]?.replace(/\s+/g, '') ?? ''
    const percentRule = [...authCssSource.matchAll(/\.account-line-modal \.quota-plan-line strong\s*\{([^}]*)\}/g)].at(-1)?.[1]?.replace(/\s+/g, '') ?? ''
    const remainingRule = [...authCssSource.matchAll(/\.account-line-modal \.quota-plan-line p\s*\{([^}]*)\}/g)].at(-1)?.[1]?.replace(/\s+/g, '') ?? ''
    const remainingValueRule = [...authCssSource.matchAll(/\.account-line-modal \.quota-plan-line p b\s*\{([^}]*)\}/g)].at(-1)?.[1]?.replace(/\s+/g, '') ?? ''

    expect(planTitleRule).toContain('font-size:14px')
    expect(percentRule).toContain('font-size:13px')
    expect(remainingRule).toContain('font-size:13px')
    expect(remainingValueRule).toContain('font-size:13px')
  })

  it('allows watermark-free export only for paid and internal plans', () => {
    expect(authStoreSource).toContain('canExportWithoutWatermark')
    expect(authStoreSource).toContain("['standard', 'advanced', 'enterprise', 'internal'].includes(user.value.plan)")
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
