<script setup lang="ts">
import { ref, watch } from 'vue'
import { useAuthStore } from './features/auth/auth-store'
import { RouterView } from 'vue-router'
import SiteFooter from './components/SiteFooter.vue'
const auth = useAuthStore()
const sessionRevision = ref(0)
watch(() => auth.user?.id, (next, previous) => {
  if (previous && previous !== next) sessionRevision.value++
}, { flush: 'sync' })
</script>

<template>
  <RouterView :key="sessionRevision" />
  <SiteFooter />
</template>

