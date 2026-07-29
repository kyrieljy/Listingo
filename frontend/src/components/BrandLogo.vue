<script setup lang="ts">
import logoUrl from '../assets/listingo-logo.png'
</script>

<template>
  <div class="brand-lockup" aria-label="Listingo">
    <img :src="logoUrl" alt="Listingo" />
  </div>
</template>

<style scoped>
.brand-lockup { display: flex; align-items: center; flex: 0 0 auto; min-width: 188px; }
.brand-lockup img { display: block; width: 170px; height: auto; max-height: 34px; object-fit: contain; }

@media (max-width: 760px) {
  .brand-lockup { min-width: 0; }
  .brand-lockup img { width: 146px; max-height: 30px; }
}
</style>
