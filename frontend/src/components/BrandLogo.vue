<script setup lang="ts">
import logoUrl from '../assets/listingo-logo.svg'
</script>

<template>
  <div class="brand-lockup" aria-label="Listingo">
    <img :src="logoUrl" alt="Listingo" />
  </div>
</template>

<style scoped>
.brand-lockup { display: flex; align-items: center; min-width: 164px; }
.brand-lockup img { display: block; width: 132px; height: auto; max-height: 34px; object-fit: contain; }
</style>
