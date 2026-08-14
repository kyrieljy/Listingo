<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import {
  ArrowRightOutlined,
  BellOutlined,
  CreditCardOutlined,
  CrownOutlined,
  LogoutOutlined,
  QuestionCircleOutlined,
  SettingOutlined,
  UserOutlined,
} from '@ant-design/icons-vue'
import { maskPhone } from './auth-model'
import { useAuthStore } from './auth-store'

type AccountMenuTab = 'profile' | 'messages' | 'privacy'

const emit = defineEmits<{
  login: []
  register: []
  profile: [tab?: AccountMenuTab]
  billing: []
  admin: []
}>()

const authStore = useAuthStore()
const menuOpen = ref(false)
const menuRoot = ref<HTMLElement | null>(null)

function closeMenu(): void {
  menuOpen.value = false
}

function toggleMenu(): void {
  menuOpen.value = !menuOpen.value
}

function handleDocumentPointerDown(event: PointerEvent): void {
  if (!menuOpen.value) return

  const target = event.target
  if (!(target instanceof Node)) {
    closeMenu()
    return
  }

  if (!menuRoot.value?.contains(target)) closeMenu()
}

onMounted(() => {
  document.addEventListener('pointerdown', handleDocumentPointerDown, true)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleDocumentPointerDown, true)
})

function openAccount(tab: AccountMenuTab = 'profile'): void {
  closeMenu()
  emit('profile', tab)
}

function openBilling(): void {
  closeMenu()
  emit('billing')
}

function openAdmin(): void {
  closeMenu()
  emit('admin')
}

function logout(): void {
  closeMenu()
  authStore.logout()
}
</script>

<template>
  <div class="topbar-user-slot">
    <div v-if="!authStore.isAuthenticated" class="login-entry-group">
      <button class="login-entry-button" type="button" @click="emit('login')">
        <span><ArrowRightOutlined /></span>
        <b>登录 / 注册</b>
      </button>
    </div>

    <div v-else ref="menuRoot" class="user-menu" @keydown.esc="closeMenu">
      <button class="user-menu-trigger user-avatar-trigger" type="button" :aria-label="authStore.user?.displayName || '账户菜单'" :aria-expanded="menuOpen" aria-haspopup="menu" @click="toggleMenu">
        <img v-if="authStore.userAvatarUrl" :src="authStore.userAvatarUrl" :alt="authStore.user?.displayName || '用户头像'" />
        <span v-else>{{ authStore.user?.avatarInitials }}</span>
        <i v-if="authStore.unreadCount" class="user-menu-badge">{{ authStore.unreadCount }}</i>
      </button>
      <div v-if="menuOpen" class="user-menu-panel" role="menu">
        <header>
          <img v-if="authStore.userAvatarUrl" :src="authStore.userAvatarUrl" :alt="authStore.user?.displayName || '用户头像'" />
          <span v-else>{{ authStore.user?.avatarInitials }}</span>
          <div>
            <strong>{{ authStore.user?.displayName }}</strong>
            <small>{{ authStore.user?.email || maskPhone(authStore.user?.phone || '') }}</small>
          </div>
        </header>
        <button type="button" role="menuitem" @click="openAccount('profile')"><UserOutlined />个人中心</button>
        <button type="button" role="menuitem" @click="openBilling"><CreditCardOutlined />会员订阅</button>
        <button type="button" role="menuitem" @click="openAccount('messages')"><BellOutlined />消息中心 <small v-if="authStore.unreadCount" class="user-menu-count">{{ authStore.unreadCount }}</small></button>
        <button type="button" role="menuitem" @click="openAccount('privacy')"><SettingOutlined />隐私设置</button>
        <div class="user-menu-divider" />
        <button v-if="authStore.isAdmin" type="button" role="menuitem" @click="openAdmin"><CrownOutlined />运营后台</button>
        <button class="disabled" type="button" role="menuitem" disabled aria-disabled="true" title="暂未开放"><QuestionCircleOutlined />帮助与支持</button>
        <div class="user-menu-divider" />
        <button class="danger" type="button" role="menuitem" @click="logout"><LogoutOutlined />退出登录</button>
      </div>
    </div>
  </div>
</template>
